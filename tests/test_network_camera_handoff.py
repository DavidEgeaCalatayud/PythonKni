from __future__ import annotations

from datetime import datetime, timezone

from PyQt5.QtWidgets import QLineEdit

from pythonkni.camera_auditor import window as camera_window
from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network import service as network_service
from pythonkni.network import window as base_network_window
from pythonkni.network.camera_handoff import match_persisted_cameras
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence.models import AssetRecord, DeviceKind
from tools import network_tool as network


NOW = datetime(2026, 9, 1, 7, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def asset(
    asset_id: str,
    ip: str,
    *,
    kind: DeviceKind = DeviceKind.CAMERA,
    mac: str = "AA:BB:CC:DD:EE:10",
    hostname: str = "camera.local",
    scope: str = SCOPE,
) -> AssetRecord:
    return AssetRecord(
        asset_id=asset_id,
        scope=scope,
        ip=ip,
        mac=mac,
        hostname=hostname,
        vendor="Reolink",
        kind=kind,
        services=("RTSP",),
        open_ports=(554,),
        evidence=("persisted classification",),
        risk=RiskLevel.MEDIUM,
        first_seen=NOW,
        last_seen=NOW,
        last_change=NOW,
        is_online=True,
    )


def history_stub():
    return type("History", (), {"append_to_history": lambda *_: None})()


def test_mac_identity_requires_current_mac_match():
    persisted = asset("mac:AA:BB:CC:DD:EE:10", "192.168.1.10")
    matching = DiscoveredHost("192.168.1.10", "camera", "aa-bb-cc-dd-ee-10")
    reassigned = DiscoveredHost("192.168.1.10", "different-host", "AA:BB:CC:DD:EE:99")

    candidates = match_persisted_cameras(SCOPE, [matching], [persisted])
    rejected = match_persisted_cameras(SCOPE, [reassigned], [persisted])

    assert [item.ip for item in candidates] == ["192.168.1.10"]
    assert "MAC identity" in candidates[0].identity_evidence
    assert rejected == ()


def test_ip_identity_matches_exact_current_ip_only():
    persisted = asset("ip:192.168.1.20", "192.168.1.20", mac="Unknown")
    host = DiscoveredHost("192.168.1.20", "camera", "No disponible")

    candidates = match_persisted_cameras(SCOPE, [host], [persisted])

    assert len(candidates) == 1
    assert candidates[0].asset_id == "ip:192.168.1.20"
    assert "IP-based" in candidates[0].identity_evidence


def test_non_camera_wrong_scope_and_unknown_identity_are_not_handoff_candidates():
    host = DiscoveredHost("192.168.1.30", "pc", "AA:BB:CC:DD:EE:30")
    pc = asset(
        "mac:AA:BB:CC:DD:EE:30",
        "192.168.1.30",
        kind=DeviceKind.PC,
        mac="AA:BB:CC:DD:EE:30",
    )
    wrong_scope = asset(
        "mac:AA:BB:CC:DD:EE:30",
        "192.168.1.30",
        mac="AA:BB:CC:DD:EE:30",
        scope="192.168.2.0/24",
    )
    unknown_identity = asset("legacy-camera-id", "192.168.1.30", mac="AA:BB:CC:DD:EE:30")

    assert match_persisted_cameras(SCOPE, [host], [pc, wrong_scope, unknown_identity]) == ()


def test_completed_discovery_enables_only_persisted_camera_matches(qtbot, monkeypatch):
    monkeypatch.setattr(network, "get_ipv4_interfaces", lambda: [])
    scanner = network.NetworkScanner(history_stub())
    qtbot.addWidget(scanner)
    scanner.cidr_input.setText(SCOPE)
    camera = asset("mac:AA:BB:CC:DD:EE:10", "192.168.1.10")
    pc = asset(
        "mac:AA:BB:CC:DD:EE:30",
        "192.168.1.30",
        kind=DeviceKind.PC,
        mac="AA:BB:CC:DD:EE:30",
    )
    monkeypatch.setattr(scanner, "_load_inventory_assets", lambda _scope: [camera, pc])

    scanner._scan_results_ready(
        [
            DiscoveredHost("192.168.1.10", "camera", "AA:BB:CC:DD:EE:10"),
            DiscoveredHost("192.168.1.30", "pc", "AA:BB:CC:DD:EE:30"),
        ]
    )

    assert scanner.camera_button.isEnabled()
    assert scanner.camera_combo.count() == 1
    assert scanner.camera_combo.currentData() == "192.168.1.10"
    assert "1 persisted camera" in scanner.result_area.toPlainText()


def test_camera_handoff_opens_exact_host_scope(qtbot, monkeypatch):
    monkeypatch.setattr(network, "get_ipv4_interfaces", lambda: [])
    scanner = network.NetworkScanner(history_stub())
    qtbot.addWidget(scanner)
    scanner._set_camera_candidates(
        match_persisted_cameras(
            SCOPE,
            [DiscoveredHost("192.168.1.10", "camera", "AA:BB:CC:DD:EE:10")],
            [asset("mac:AA:BB:CC:DD:EE:10", "192.168.1.10")],
        )
    )
    opened = []

    class FakeCameraAuditor:
        def __init__(self):
            self.scope_input = QLineEdit()
            self.shown = False
            self.started = False
            opened.append(self)

        def show(self):
            self.shown = True

        def start_audit(self):
            self.started = True

    monkeypatch.setattr(camera_window, "Tool", FakeCameraAuditor)

    scanner.open_selected_camera()

    assert len(opened) == 1
    assert opened[0].scope_input.text() == "192.168.1.10/32"
    assert opened[0].shown is True
    assert opened[0].started is True
    assert scanner._camera_windows == opened


def test_worker_success_emits_structured_results_without_extra_probe(monkeypatch):
    host = DiscoveredHost("192.168.1.10", "camera", "AA:BB:CC:DD:EE:10")

    def fake_scan(cidr, stop_event=None, on_found=None, on_checked=None, **kwargs):
        assert cidr == SCOPE
        on_checked(host.ip)
        on_found(host)
        return [host]

    monkeypatch.setattr(network, "scan_network_hosts", fake_scan)
    worker = network.NetworkScanWorker(SCOPE)
    structured_results = []
    summaries = []
    worker.results_ready.connect(structured_results.append)
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert structured_results == [[host]]
    assert "192.168.1.10" in summaries[0]


def test_cancelled_network_scan_never_emits_structured_handoff_results(monkeypatch):
    host = DiscoveredHost("192.168.1.10", "camera", "AA:BB:CC:DD:EE:10")

    def fake_scan(cidr, stop_event=None, on_found=None, on_checked=None, **kwargs):
        on_checked(host.ip)
        on_found(host)
        stop_event.set()
        return [host]

    monkeypatch.setattr(network, "scan_network_hosts", fake_scan)
    worker = network.NetworkScanWorker(SCOPE)
    structured_results = []
    summaries = []
    worker.results_ready.connect(structured_results.append)
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert structured_results == []
    assert summaries[0].startswith("[CANCELADO]")


def test_worker_failure_emits_failure_without_handoff_result(monkeypatch):
    def fail_scan(*args, **kwargs):
        raise OSError("discovery failed")

    monkeypatch.setattr(network, "scan_network_hosts", fail_scan)
    worker = network.NetworkScanWorker(SCOPE)
    failures = []
    structured_results = []
    summaries = []
    worker.failed.connect(failures.append)
    worker.results_ready.connect(structured_results.append)
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert failures and isinstance(failures[0], OSError)
    assert structured_results == []
    assert summaries == ["Escaneo de red fallido."]


def test_legacy_executor_patch_reaches_network_service(monkeypatch):
    class TrackingExecutor:
        pass

    monkeypatch.setattr(network, "ThreadPoolExecutor", TrackingExecutor)

    assert network_service.ThreadPoolExecutor is TrackingExecutor


def test_base_network_scanner_invalid_cidr_branch_remains_covered(qtbot, monkeypatch):
    monkeypatch.setattr(base_network_window, "get_ipv4_interfaces", lambda: [])
    scanner = base_network_window.NetworkScanner(history_stub())
    qtbot.addWidget(scanner)
    scanner.cidr_input.setText("not-a-network")

    scanner.scan_network()

    assert "Error:" in scanner.result_area.toPlainText()
    assert scanner.worker is None
