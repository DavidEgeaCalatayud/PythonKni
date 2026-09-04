from __future__ import annotations

import threading

import pytest

from pythonkni.web_recon import service
from pythonkni.web_recon.models import (
    CookieAssessment,
    DnsSummary,
    FindingSeverity,
    HttpCheck,
    HttpSummary,
    PortResult,
    ReconReport,
    SubdomainResult,
    TechnologyEvidence,
    TlsSummary,
    WhoisSummary,
)


def test_normalize_target_defaults_https_and_preserves_path():
    target = service.normalize_target("Example.COM/docs?q=1#frag")
    assert target.scheme == "https"
    assert target.hostname == "example.com"
    assert target.port == 443
    assert target.url == "https://example.com/docs?q=1"
    assert target.origin == "https://example.com"


def test_normalize_target_accepts_explicit_http_port():
    target = service.normalize_target("http://example.com:8080/a")
    assert target.port == 8080
    assert target.origin == "http://example.com:8080"


@pytest.mark.parametrize(
    "value, message",
    [
        ("", "Introduce"),
        ("ftp://example.com", "HTTP"),
        ("https://u:p@example.com", "credenciales"),
        ("https://bad_host.example", "hostname"),
        ("https://example.com:99999", "puerto"),
    ],
)
def test_normalize_target_rejects_unsafe_or_invalid_values(value, message):
    with pytest.raises(ValueError, match=message):
        service.normalize_target(value)


def test_build_findings_covers_dns_tls_headers_and_cookies():
    target = service.normalize_target("https://example.com")
    report = ReconReport(
        target=target,
        dns=DnsSummary(
            dmarc_policy="none",
            dmarc=("v=DMARC1; p=none",),
            dnssec_published=False,
        ),
        tls=TlsSummary(available=True, expires_in_days=10, not_after="soon"),
        http=HttpSummary(
            checks=(HttpCheck("CSP", False, "", "set CSP"),),
            cookies=(CookieAssessment("sid", False, False, ""),),
        ),
    )
    findings = service.build_findings(report)
    ids = {item.finding_id for item in findings}
    assert "web.dmarc.weak" in ids
    assert "web.dnssec.not-published" in ids
    assert "web.tls.expiring" in ids
    assert "web.http.csp" in ids
    assert "web.cookie.sid.attributes" in ids
    assert all(item.severity in FindingSeverity for item in findings)


def test_build_findings_marks_expired_cert_high():
    target = service.normalize_target("example.com")
    report = ReconReport(
        target=target,
        dns=DnsSummary(dmarc_policy="reject", dnssec_published=True),
        tls=TlsSummary(available=True, expires_in_days=-1, not_after="yesterday"),
    )
    findings = service.build_findings(report)
    assert findings[0].finding_id == "web.tls.expired"
    assert findings[0].severity is FindingSeverity.HIGH


def test_run_recon_orchestrates_optional_sources_active_scan_and_nerva(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "resolve_addresses", lambda host: ("203.0.113.10",))
    monkeypatch.setattr(
        service,
        "collect_dns",
        lambda host, addresses, mail_domain=None: DnsSummary(
            dmarc_policy="reject", dnssec_published=True
        ),
    )
    monkeypatch.setattr(
        service,
        "inspect_whois",
        lambda domain: WhoisSummary(registrar="Registrar"),
    )
    monkeypatch.setattr(
        service,
        "inspect_tls",
        lambda host, port: TlsSummary(available=True, version="TLSv1.3"),
    )
    monkeypatch.setattr(
        service,
        "inspect_http",
        lambda target: HttpSummary(
            status_code=200,
            final_url=target.url,
            body_text="<a href='/a'>a</a>",
        ),
    )
    monkeypatch.setattr(
        service,
        "detect_technologies",
        lambda summary: (TechnologyEvidence("nginx", "header"),),
    )
    monkeypatch.setattr(
        service,
        "certificate_transparency_subdomains",
        lambda domain: (SubdomainResult(f"api.{domain}"),),
    )
    monkeypatch.setattr(service, "wayback_urls", lambda host: ())
    monkeypatch.setattr(service, "crawl_same_origin", lambda target, body, stop_event=None: ())
    monkeypatch.setattr(service, "probe_common_paths", lambda target, stop_event=None: ())
    monkeypatch.setattr(
        service,
        "scan_common_ports",
        lambda host, stop_event=None: (PortResult(443, "HTTPS"),),
    )
    monkeypatch.setattr(
        service,
        "enrich_ports_with_nerva",
        lambda host, ports, stop_event=None: (
            PortResult(443, "HTTPS", fingerprint="https · nginx"),
        ),
    )

    report = service.run_recon(
        "https://www.example.com",
        include_external_sources=True,
        include_active_discovery=True,
        include_nerva=True,
        on_progress=lambda value: calls.append(value.stage),
    )
    assert report.addresses == ("203.0.113.10",)
    assert report.whois.registrar == "Registrar"
    assert report.subdomains[0].hostname == "api.example.com"
    assert report.ports[0].fingerprint.startswith("https")
    assert {
        "target",
        "dns",
        "whois",
        "tls",
        "http",
        "external",
        "crawl",
        "ports",
        "nerva",
    } <= set(calls)


def test_run_recon_skips_optional_sources_when_disabled(monkeypatch):
    monkeypatch.setattr(service, "resolve_addresses", lambda host: ())
    monkeypatch.setattr(service, "collect_dns", lambda *args, **kwargs: DnsSummary())
    monkeypatch.setattr(service, "inspect_whois", lambda domain: WhoisSummary())
    monkeypatch.setattr(service, "inspect_tls", lambda *args: TlsSummary())
    monkeypatch.setattr(service, "inspect_http", lambda target: HttpSummary())
    monkeypatch.setattr(service, "detect_technologies", lambda summary: ())
    monkeypatch.setattr(
        service,
        "certificate_transparency_subdomains",
        lambda domain: pytest.fail("external called"),
    )
    monkeypatch.setattr(
        service,
        "scan_common_ports",
        lambda *args, **kwargs: pytest.fail("active called"),
    )
    report = service.run_recon("example.com")
    assert report.subdomains == ()
    assert report.ports == ()


def test_run_recon_honours_preemptive_cancellation_after_resolution(monkeypatch):
    event = threading.Event()

    def resolve(_host):
        event.set()
        return ("203.0.113.10",)

    monkeypatch.setattr(service, "resolve_addresses", resolve)
    report = service.run_recon("example.com", stop_event=event)
    assert report.addresses == ("203.0.113.10",)
    assert report.dns.records == ()
