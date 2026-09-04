from __future__ import annotations

from types import SimpleNamespace

import pytest

from pythonkni.web_recon import dns
from pythonkni.web_recon.models import DnsRecord


def test_registrable_domain_candidate_handles_common_suffixes():
    assert dns.registrable_domain_candidate("www.example.com") == "example.com"
    assert dns.registrable_domain_candidate("a.b.example.co.uk") == "example.co.uk"
    assert dns.registrable_domain_candidate("example.es") == "example.es"


def test_resolve_addresses_deduplicates_ipv4_and_ipv6(monkeypatch):
    monkeypatch.setattr(
        dns.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (dns.socket.AF_INET, 1, 0, "", ("1.2.3.4", 0)),
            (dns.socket.AF_INET6, 1, 0, "", ("2001:db8::1", 0, 0, 0)),
            (dns.socket.AF_INET, 1, 0, "", ("1.2.3.4", 0)),
        ],
    )
    assert dns.resolve_addresses("example.com") == ("1.2.3.4", "2001:db8::1")


def test_query_windows_dns_validates_type_and_platform(monkeypatch):
    with pytest.raises(ValueError, match="Unsupported"):
        dns.query_windows_dns("example.com", "SRV")
    monkeypatch.setattr(dns.platform, "system", lambda: "Linux")
    monkeypatch.setattr(dns, "_powershell_executable", lambda: "/usr/bin/pwsh")
    assert dns.query_windows_dns("example.com", "MX") == ()


def test_query_windows_dns_parses_powershell_json(monkeypatch):
    monkeypatch.setattr(dns.platform, "system", lambda: "Windows")
    monkeypatch.setattr(dns, "_powershell_executable", lambda: "powershell.exe")
    payload = (
        '[{"Name":"example.com","NameExchange":"mx.example.com.","Preference":10},'
        '{"Name":"example.com","Strings":["v=spf1 ","-all"]}]'
    )
    monkeypatch.setattr(
        dns.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=payload),
    )
    mx = dns.query_windows_dns("example.com", "MX")
    txt = dns.query_windows_dns("example.com", "TXT")
    assert mx[0].value == "mx.example.com"
    assert mx[0].preference == 10
    assert txt[1].value == "v=spf1 -all"


def test_query_windows_dns_parses_dnskey_fields(monkeypatch):
    monkeypatch.setattr(dns.platform, "system", lambda: "Windows")
    monkeypatch.setattr(dns, "_powershell_executable", lambda: "powershell.exe")
    payload = '{"Name":"example.com","Key":"AQID","Algorithm":13}'
    monkeypatch.setattr(
        dns.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=payload),
    )

    records = dns.query_windows_dns("example.com", "DNSKEY")

    assert len(records) == 1
    assert records[0].record_type == "DNSKEY"
    assert records[0].name == "example.com"
    assert records[0].value == "algorithm=13; key=AQID"


def test_query_windows_dns_handles_command_and_json_failure(monkeypatch):
    monkeypatch.setattr(dns.platform, "system", lambda: "Windows")
    monkeypatch.setattr(dns, "_powershell_executable", lambda: "powershell.exe")
    monkeypatch.setattr(
        dns.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    assert dns.query_windows_dns("example.com", "TXT") == ()
    monkeypatch.setattr(
        dns.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not-json"),
    )
    assert dns.query_windows_dns("example.com", "TXT") == ()


def test_collect_dns_extracts_spf_dmarc_policy_and_dnssec(monkeypatch):
    def query(host, record_type):
        if host.startswith("_dmarc"):
            return (DnsRecord("TXT", host, "v=DMARC1; p=quarantine"),)
        if record_type == "TXT":
            return (DnsRecord("TXT", host, "v=spf1 -all"),)
        if record_type == "DNSKEY":
            return (DnsRecord("DNSKEY", host, "key"),)
        return ()

    monkeypatch.setattr(dns, "query_windows_dns", query)
    result = dns.collect_dns("www.example.com", ("1.2.3.4",), mail_domain="example.com")
    assert result.spf == ("v=spf1 -all",)
    assert result.dmarc_policy == "quarantine"
    assert result.dnssec_published is True
    assert any(item.record_type == "A" for item in result.records)


def test_collect_dns_returns_partial_result_on_query_error(monkeypatch):
    monkeypatch.setattr(
        dns,
        "query_windows_dns",
        lambda *args: (_ for _ in ()).throw(OSError("dns failed")),
    )
    result = dns.collect_dns("example.com", ("1.2.3.4",))
    assert "dns failed" in result.error
    assert result.records[0].value == "1.2.3.4"


def test_powershell_executable_returns_first_available(monkeypatch):
    monkeypatch.setattr(
        dns.shutil,
        "which",
        lambda name: "C:/pwsh.exe" if name == "pwsh" else None,
    )
    assert dns._powershell_executable() == "C:/pwsh.exe"
    monkeypatch.setattr(dns.shutil, "which", lambda name: None)
    assert dns._powershell_executable() is None


def test_record_value_supports_ip_host_and_missing_values():
    assert dns._record_value({"IPAddress": "1.2.3.4"}) == ("1.2.3.4", None)
    assert dns._record_value({"NameHost": "ns.example.com."}) == (
        "ns.example.com",
        None,
    )
    assert dns._record_value({"Strings": "v=spf1 -all"}) == ("v=spf1 -all", None)
    assert dns._record_value({}) == ("", None)


def test_collect_dns_reports_dnssec_false_when_dnskey_absent(monkeypatch):
    monkeypatch.setattr(dns, "query_windows_dns", lambda *args: ())
    result = dns.collect_dns("example.com", ())
    assert result.dnssec_published is False
    assert result.dmarc_policy == ""
