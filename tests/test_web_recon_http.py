from __future__ import annotations

from types import SimpleNamespace

from pythonkni.web_recon import http
from pythonkni.web_recon.models import CookieAssessment, HttpSummary
from pythonkni.web_recon.service import normalize_target


class RawHeaders:
    def getlist(self, name):
        assert name == "Set-Cookie"
        return ["sid=abc; Secure; HttpOnly; SameSite=Lax"]


class FakeResponse:
    def __init__(self):
        self.status_code = 200
        self.headers = http.requests.structures.CaseInsensitiveDict(
            {
                "Strict-Transport-Security": "max-age=31536000",
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Permissions-Policy": "camera=()",
                "Server": "nginx",
                "CF-Ray": "abc",
            }
        )
        self.raw = SimpleNamespace(headers=RawHeaders())
        self.closed = False

    def close(self):
        self.closed = True


def test_inspect_http_builds_security_checks_and_cookies(monkeypatch):
    response = FakeResponse()
    monkeypatch.setattr(
        http,
        "fetch_target",
        lambda target: (response, target.url, "<html>wp-content/x</html>"),
    )
    summary = http.inspect_http(normalize_target("example.com"))
    assert summary.status_code == 200
    assert all(check.passed for check in summary.checks)
    assert summary.cookies[0].name == "sid"
    assert response.closed is True


def test_detect_technologies_uses_headers_html_and_cookies():
    summary = HttpSummary(
        headers=(("Server", "nginx"), ("X-Powered-By", "PHP/8.3"), ("CF-Ray", "x")),
        body_text="<link href='/wp-content/theme.css'>",
        cookies=(CookieAssessment("PHPSESSID", True, True, "Lax"),),
    )
    names = {item.name for item in http.detect_technologies(summary)}
    assert "nginx" in names
    assert "PHP/8.3" in names
    assert "Cloudflare" in names
    assert "WordPress" in names
    assert "PHP" in names


def test_inspect_http_returns_request_error(monkeypatch):
    monkeypatch.setattr(
        http,
        "fetch_target",
        lambda target: (_ for _ in ()).throw(http.requests.RequestException("boom")),
    )
    assert "boom" in http.inspect_http(normalize_target("example.com")).error


def test_same_host_requires_same_hostname():
    target = normalize_target("https://example.com")
    assert http._same_host("https://example.com/a", target) is True
    assert http._same_host("https://evil.example.net/a", target) is False


class StreamingResponse:
    def __init__(self, status=200, headers=None, chunks=(), encoding="utf-8"):
        self.status_code = status
        self.headers = http.requests.structures.CaseInsensitiveDict(headers or {})
        self._chunks = list(chunks)
        self.encoding = encoding
        self.is_redirect = status in {301, 302, 303, 307, 308}
        self.closed = False
        self.raw = SimpleNamespace(headers=SimpleNamespace(getlist=lambda _name: []))

    def iter_content(self, chunk_size=16384):
        yield from self._chunks

    def close(self):
        self.closed = True


def test_fetch_target_follows_same_host_redirect_and_stops_external(monkeypatch):
    first = StreamingResponse(302, {"Location": "/home"}, [b""])
    second = StreamingResponse(200, {}, [b"ok"])
    calls = []

    class Session:
        def get(self, url, **kwargs):
            calls.append(url)
            return first if len(calls) == 1 else second

    monkeypatch.setattr(http.requests, "Session", Session)
    response, final_url, body = http.fetch_target(
        normalize_target("https://example.com")
    )
    assert response is second
    assert final_url == "https://example.com/home"
    assert body == "ok"
    assert first.closed is True

    external = StreamingResponse(
        302, {"Location": "https://evil.test/"}, [b"redirect"]
    )
    monkeypatch.setattr(
        http.requests,
        "Session",
        lambda: SimpleNamespace(get=lambda *args, **kwargs: external),
    )
    response, final_url, body = http.fetch_target(
        normalize_target("https://example.com")
    )
    assert response is external
    assert final_url == "https://example.com/"
    assert body == "redirect"


def test_read_bounded_caps_response_body(monkeypatch):
    monkeypatch.setattr(http, "MAX_HTTP_BODY_BYTES", 5)
    response = StreamingResponse(chunks=[b"abc", b"def", b"ghi"])
    assert http._read_bounded(response) == b"abcde"


def test_cookie_parser_falls_back_to_combined_header():
    response = StreamingResponse(
        headers={"Set-Cookie": "token=1; SameSite=Strict"},
        chunks=[],
    )
    response.raw = SimpleNamespace(headers=object())
    cookies = http._cookies(response)
    assert cookies[0].name == "token"
    assert cookies[0].secure is False
    assert cookies[0].httponly is False
    assert cookies[0].samesite == "Strict"


def test_detect_technologies_covers_framework_cookie_markers():
    summary = HttpSummary(
        cookies=(
            CookieAssessment("JSESSIONID", True, True),
            CookieAssessment("ASP.NET_SessionId", True, True),
            CookieAssessment("laravel_session", True, True),
        )
    )
    names = {item.name for item in http.detect_technologies(summary)}
    assert {"Java/Jakarta", "ASP.NET", "Laravel"} <= names
