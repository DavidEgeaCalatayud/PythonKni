from __future__ import annotations

from types import SimpleNamespace

from pythonkni.web_recon import intelligence
from pythonkni.web_recon.models import PortResult


def test_nerva_enriches_matching_ports(monkeypatch):
    monkeypatch.setattr(
        intelligence,
        "fingerprint_open_ports",
        lambda *args, **kwargs: [
            SimpleNamespace(
                port=443,
                protocol="https",
                product="nginx",
                version="1.26",
            )
        ],
    )
    result = intelligence.enrich_ports_with_nerva(
        "example.com",
        (PortResult(443, "HTTPS"), PortResult(8080, "HTTP-ALT")),
    )
    assert result[0].product == "nginx"
    assert "https" in result[0].fingerprint
    assert result[1].product == ""


def test_nerva_unavailable_preserves_port_scan(monkeypatch):
    monkeypatch.setattr(
        intelligence,
        "fingerprint_open_ports",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            intelligence.FingerprintEngineUnavailable("missing")
        ),
    )
    ports = (PortResult(443, "HTTPS"),)
    assert intelligence.enrich_ports_with_nerva("example.com", ports) == ports
    assert intelligence.enrich_ports_with_nerva("example.com", ()) == ()
