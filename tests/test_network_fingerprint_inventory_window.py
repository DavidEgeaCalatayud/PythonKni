from __future__ import annotations

from types import SimpleNamespace

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network import fingerprint_inventory_window as window
from pythonkni.network.models import DiscoveredHost, ServiceFingerprint
from pythonkni.network_intelligence.inventory import InventoryStore
from pythonkni.network_intelligence.models import DeviceKind, NetworkIntelligenceDevice

SCOPE = "192.168.1.0/24"
IP = "192.168.1.20"


def _device(*, mac: str = "00:11:22:33:44:55", scope_ip: str = IP) -> NetworkIntelligenceDevice:
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip=scope_ip, hostname="server.local", mac=mac),
        kind=DeviceKind.PC,
        open_ports=(22, 443),
        services=("SSH", "HTTPS"),
        evidence=("Base evidence",),
        risk=RiskLevel.MEDIUM,
        vendor="Example Vendor",
        classification_confidence=80,
    )


def _fingerprint(*, ip: str = IP, port: int = 22) -> ServiceFingerprint:
    return ServiceFingerprint(
        host="server.local",
        ip=ip,
        port=port,
        protocol="ssh" if port == 22 else "redis",
        product="OpenSSH" if port == 22 else "Redis",
        version="9.9" if port == 22 else "8.2",
    )


def _scanner(qtbot) -> window.PortScanner:
    history = window._base.HistoryTab()
    scanner = window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    return scanner


def test_apply_button_tracks_fingerprint_lifecycle(qtbot):
    scanner = _scanner(qtbot)

    assert scanner.apply_fingerprints_button.isEnabled() is False
    scanner._remember_fingerprints([_fingerprint()])
    scanner._set_running(False)
    assert scanner.apply_fingerprints_button.isEnabled() is True

    scanner._remember_open_ports([])
    scanner._set_running(False)
    assert scanner.apply_fingerprints_button.isEnabled() is False


def test_explicit_apply_updates_unique_online_inventory_asset(qtbot, monkeypatch, tmp_path):
    database = tmp_path / "inventory.sqlite3"
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", database)
    store = InventoryStore(database)
    asset = store.record_device(SCOPE, _device())
    scanner = _scanner(qtbot)
    scanner.fingerprints = (_fingerprint(),)
    scanner._set_running(False)

    scanner.apply_fingerprints_to_inventory()

    persisted = InventoryStore(database).get_asset(asset.asset_id)
    assert persisted is not None
    assert persisted.services == ("SSH (OpenSSH 9.9)", "HTTPS")
    assert persisted.risk is RiskLevel.MEDIUM
    assert scanner.apply_fingerprints_button.isEnabled() is False
    assert "riesgo medium sin modificar" in scanner.result_area.toPlainText().lower()
    events = InventoryStore(database).list_events(scope=SCOPE)
    assert any(event.event_type == "service_changed" for event in events)


def test_apply_refuses_missing_or_ambiguous_inventory_match(qtbot, monkeypatch, tmp_path):
    database = tmp_path / "inventory.sqlite3"
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", database)
    scanner = _scanner(qtbot)
    scanner.fingerprints = (_fingerprint(),)

    scanner.apply_fingerprints_to_inventory()
    assert "no existe un activo online" in scanner.result_area.toPlainText()

    store = InventoryStore(database)
    store.record_device(SCOPE, _device(mac="00:11:22:33:44:55"))
    store.record_device("192.168.1.0/25", _device(mac="66:77:88:99:AA:BB"))
    scanner.result_area.clear()

    scanner.apply_fingerprints_to_inventory()
    assert "asociación ambigua" in scanner.result_area.toPlainText()


def test_apply_refuses_fingerprints_without_one_resolved_ip(qtbot):
    scanner = _scanner(qtbot)
    scanner.fingerprints = (_fingerprint(ip=""),)

    scanner.apply_fingerprints_to_inventory()
    assert "sin una única IP resuelta" in scanner.result_area.toPlainText()

    scanner.result_area.clear()
    scanner.fingerprints = (_fingerprint(ip=IP), _fingerprint(ip="192.168.1.21"))
    scanner.apply_fingerprints_to_inventory()
    assert "sin una única IP resuelta" in scanner.result_area.toPlainText()


def test_apply_is_noop_without_results_or_while_worker_runs(qtbot):
    scanner = _scanner(qtbot)
    scanner.apply_fingerprints_to_inventory()
    assert scanner.result_area.toPlainText() == ""

    scanner.fingerprints = (_fingerprint(),)
    scanner.worker = SimpleNamespace(isRunning=lambda: True)
    scanner.apply_fingerprints_to_inventory()
    assert scanner.result_area.toPlainText() == ""


def test_apply_failure_uses_structured_feedback(qtbot, monkeypatch, tmp_path):
    database = tmp_path / "inventory.sqlite3"
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", database)
    InventoryStore(database).record_device(SCOPE, _device())
    scanner = _scanner(qtbot)
    scanner.fingerprints = (_fingerprint(),)
    captured = []
    monkeypatch.setattr(
        window._base._base,
        "_show_exception",
        lambda *args: captured.append(args),
    )
    monkeypatch.setattr(
        window,
        "persist_asset_fingerprints",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    scanner.apply_fingerprints_to_inventory()

    assert captured[0][1] == "Aplicar fingerprints"
    assert isinstance(captured[0][-1], RuntimeError)
