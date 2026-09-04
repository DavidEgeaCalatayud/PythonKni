from __future__ import annotations

from contextlib import nullcontext

from pythonkni.web_recon import tls, whois


def test_whois_follows_iana_referral_and_parses_fields(monkeypatch):
    responses = {
        "whois.iana.org": "refer: whois.example.net\n",
        "whois.example.net": (
            "Registrar: Example Registrar\nCreation Date: 2020-01-01\n"
            "Registry Expiry Date: 2030-01-01\nName Server: NS1.EXAMPLE.COM.\n"
            "Domain Status: ok\n"
        ),
    }
    monkeypatch.setattr(whois, "_query", lambda server, query: responses[server])
    result = whois.inspect_whois("example.com")
    assert result.registrar == "Example Registrar"
    assert result.expires == "2030-01-01"
    assert result.nameservers == ("NS1.EXAMPLE.COM",)
    assert result.referral_server == "whois.example.net"


def test_whois_returns_error(monkeypatch):
    monkeypatch.setattr(
        whois,
        "_query",
        lambda *args: (_ for _ in ()).throw(OSError("offline")),
    )
    assert "offline" in whois.inspect_whois("example.com").error


class FakeTlsSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getpeercert(self):
        return {
            "subject": ((("commonName", "example.com"),),),
            "issuer": ((("commonName", "Example CA"),),),
            "serialNumber": "123",
            "notBefore": "Jan  1 00:00:00 2026 GMT",
            "notAfter": "Jan  1 00:00:00 2030 GMT",
            "subjectAltName": (("DNS", "example.com"), ("DNS", "www.example.com")),
        }

    def cipher(self):
        return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)

    def version(self):
        return "TLSv1.3"


class FakeContext:
    def wrap_socket(self, _raw, server_hostname=None):
        assert server_hostname == "example.com"
        return FakeTlsSocket()


def test_tls_inspection_parses_certificate(monkeypatch):
    monkeypatch.setattr(tls.ssl, "create_default_context", lambda: FakeContext())
    monkeypatch.setattr(
        tls.socket,
        "create_connection",
        lambda *args, **kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(tls.ssl, "cert_time_to_seconds", lambda value: 1893456000.0)
    result = tls.inspect_tls("example.com", 443)
    assert result.available is True
    assert result.version == "TLSv1.3"
    assert result.cipher == "TLS_AES_256_GCM_SHA384"
    assert "commonName=example.com" in result.subject
    assert result.sans == ("example.com", "www.example.com")


def test_tls_inspection_reports_handshake_error(monkeypatch):
    monkeypatch.setattr(
        tls.socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("refused")),
    )
    result = tls.inspect_tls("example.com", 443)
    assert result.available is False
    assert "refused" in result.error


class FakeWhoisSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, _value):
        pass

    def sendall(self, value):
        self.sent = value

    def recv(self, _size):
        return self.chunks.pop(0) if self.chunks else b""


def test_whois_query_is_bounded_and_sends_crlf(monkeypatch):
    sock = FakeWhoisSocket([b"Registrar: Test\n", b""])
    monkeypatch.setattr(
        whois.socket,
        "create_connection",
        lambda *args, **kwargs: sock,
    )
    text = whois._query("whois.test", "example.com")
    assert "Registrar: Test" in text
    assert sock.sent == b"example.com\r\n"


def test_whois_strips_scheme_from_referral_and_can_use_iana_only(monkeypatch):
    calls = []

    def query(server, domain):
        calls.append(server)
        if server == "whois.iana.org":
            return "whois: whois://whois.example.net/path\n"
        return "Registrar Name: Registry Registrar\n"

    monkeypatch.setattr(whois, "_query", query)
    result = whois.inspect_whois("example.com")
    assert result.referral_server == "whois.example.net"
    assert result.registrar == "Registry Registrar"

    monkeypatch.setattr(
        whois,
        "_query",
        lambda server, domain: "Registrar: IANA Only\n",
    )
    result = whois.inspect_whois("example.com")
    assert result.registrar == "IANA Only"
    assert result.referral_server == ""


def test_tls_bad_expiry_string_does_not_break_summary(monkeypatch):
    class BadExpirySocket(FakeTlsSocket):
        def getpeercert(self):
            value = super().getpeercert()
            value["notAfter"] = "not a date"
            return value

    class BadContext(FakeContext):
        def wrap_socket(self, _raw, server_hostname=None):
            return BadExpirySocket()

    monkeypatch.setattr(tls.ssl, "create_default_context", lambda: BadContext())
    monkeypatch.setattr(
        tls.socket,
        "create_connection",
        lambda *args, **kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(
        tls.ssl,
        "cert_time_to_seconds",
        lambda value: (_ for _ in ()).throw(ValueError("bad")),
    )
    result = tls.inspect_tls("example.com", 443)
    assert result.available is True
    assert result.expires_in_days is None
