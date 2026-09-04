from __future__ import annotations

import threading
from types import SimpleNamespace

from pythonkni.web_recon import discovery
from pythonkni.web_recon.service import normalize_target


def test_certificate_transparency_is_bounded_and_scoped(monkeypatch):
    payload = [
        {"name_value": "api.example.com\n*.example.com"},
        {"name_value": "evil.test"},
    ]
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(discovery.requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        discovery.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 0, "", ("1.2.3.4", 0))],
    )
    results = discovery.certificate_transparency_subdomains("example.com")
    assert {item.hostname for item in results} == {"api.example.com", "example.com"}
    assert all("evil.test" != item.hostname for item in results)


def test_certificate_transparency_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(
        discovery.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(discovery.requests.RequestException()),
    )
    assert discovery.certificate_transparency_subdomains("example.com") == ()


def test_wayback_parses_deduplicates_and_caps(monkeypatch):
    payload = [
        ["original"],
        ["https://example.com/a"],
        ["https://example.com/a"],
        ["https://example.com/b"],
    ]
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(discovery.requests, "get", lambda *args, **kwargs: response)
    results = discovery.wayback_urls("example.com")
    assert [item.url for item in results] == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_crawl_same_origin_excludes_external_hosts_and_fragments():
    target = normalize_target("https://example.com")
    html = "<a href='/a#x'>A</a><script src='https://evil.test/x.js'></script>"
    results = discovery.crawl_same_origin(target, html, stop_event=threading.Event())
    assert [item.url for item in results] == ["https://example.com/a"]


def test_common_path_probe_suppresses_soft_404(monkeypatch):
    target = normalize_target("https://example.com")

    def fake_get(url):
        if "not-found-probe" in url:
            return 200, "x" * 100
        if url.endswith("robots.txt"):
            return 200, "x" * 102
        if url.endswith("sitemap.xml"):
            return 200, "real sitemap"
        return 404, ""

    monkeypatch.setattr(discovery, "_get_small", fake_get)
    results = discovery.probe_common_paths(target)
    assert len(results) == 1
    assert results[0].url.endswith("sitemap.xml")


def test_common_path_probe_honours_cancellation(monkeypatch):
    event = threading.Event()
    event.set()
    monkeypatch.setattr(discovery, "_get_small", lambda url: (404, ""))
    assert discovery.probe_common_paths(normalize_target("example.com"), stop_event=event) == ()


def test_scan_common_ports_reports_only_open_ports(monkeypatch):
    monkeypatch.setattr(discovery, "COMMON_PORTS", (80, 443, 8443))
    monkeypatch.setattr(
        discovery,
        "_port_open",
        lambda host, port: port in {80, 8443},
    )
    results = discovery.scan_common_ports("example.com")
    assert [item.port for item in results] == [80, 8443]
    assert results[0].service == "HTTP"


def test_ct_keeps_unresolved_name_with_empty_addresses(monkeypatch):
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: [{"name_value": "api.example.com"}],
    )
    monkeypatch.setattr(discovery.requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        discovery.socket,
        "getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )
    result = discovery.certificate_transparency_subdomains("example.com")
    assert result[0].addresses == ()


def test_wayback_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(
        discovery.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(discovery.requests.RequestException()),
    )
    assert discovery.wayback_urls("example.com") == ()


class RawBody:
    def read(self, amount, decode_content=True):
        assert decode_content is True
        return b"hello"[:amount]


class SmallResponse:
    status_code = 200
    encoding = "utf-8"
    raw = RawBody()

    def close(self):
        self.closed = True


def test_get_small_success_and_failure(monkeypatch):
    response = SmallResponse()
    monkeypatch.setattr(discovery.requests, "get", lambda *args, **kwargs: response)
    assert discovery._get_small("https://example.com") == (200, "hello")
    monkeypatch.setattr(
        discovery.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(discovery.requests.RequestException()),
    )
    assert discovery._get_small("https://example.com") == (None, "")


def test_crawl_fetches_followup_pages_but_stays_bounded(monkeypatch):
    target = normalize_target("https://example.com")
    pages = {
        "https://example.com/a": (200, "<a href='/b'>b</a>"),
        "https://example.com/b": (200, ""),
    }
    monkeypatch.setattr(
        discovery,
        "_get_small",
        lambda url: pages.get(url, (404, "")),
    )
    result = discovery.crawl_same_origin(target, "<a href='/a'>a</a>")
    assert {item.url for item in result} == {
        "https://example.com/a",
        "https://example.com/b",
    }


def test_port_open_uses_socket_connection(monkeypatch):
    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        discovery.socket,
        "create_connection",
        lambda *args, **kwargs: Ctx(),
    )
    assert discovery._port_open("example.com", 443) is True
    monkeypatch.setattr(
        discovery.socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )
    assert discovery._port_open("example.com", 443) is False


def test_scan_ports_can_stop_early(monkeypatch):
    event = threading.Event()
    monkeypatch.setattr(discovery, "COMMON_PORTS", (80, 443))

    def open_and_cancel(host, port):
        event.set()
        return True

    monkeypatch.setattr(discovery, "_port_open", open_and_cancel)
    assert discovery.scan_common_ports("example.com", stop_event=event) == ()
