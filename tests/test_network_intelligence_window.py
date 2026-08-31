from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QThread

from pythonkni.camera_auditor.models import CameraDevice, RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence import window
from pythonkni.network_intelligence.models import DeviceKind, NetworkIntelligenceDevice


def make_device(ip="192.168.1.21", kind=DeviceKind.CAMERA):
    camera = None
    if kind == DeviceKind.CAMERA:
        camera = CameraDevice(
            ip=ip,
            vendor="Reolink",
            name="Patio",
            hardware="RLC",
            services=(),
            onvif=True,
            confidence="Alta",
            risk=RiskLevel.MEDIUM,
            risk_reasons=("RTSP expuesto",),
        )
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip=ip, hostname="device.local", mac="AA:BB:CC:DD:EE:FF"),
        kind=kind,
        open_ports=(554,) if kind == DeviceKind.CAMERA else (3389,),
        services=("RTSP",) if kind == DeviceKind.CAMERA else ("RDP",),
        evidence=("classified",),
        risk=RiskLevel.MEDIUM if kind == DeviceKind.CAMERA else RiskLevel.LOW,
        camera=camera,
    )


def test_default_scope_uses_interface_and_caps_large_network(monkeypatch):
    monkeypatch.setattr(
        window,
        "detect_default_network",
        lambda: SimpleNamespace(cidr="10.0.0.0/16", address="10.0.5.20"),
    )
    assert window._default_scope() == "10.0.5.0/24"


def test_default_scope_falls_back(monkeypatch):
    monkeypatch.setattr(
        window,
        "detect_default_network",
        lambda: (_ for _ in ()).throw(RuntimeError("no interface")),
    )
    assert window._default_scope() == "192.168.1.0/24"


@pytest.fixture
def tool(qtbot, monkeypatch):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    instance = window.Tool()
    qtbot.addWidget(instance)
    return instance


def test_initial_state(tool):
    assert tool.name == "Network Intelligence"
    assert tool.scope_input.text() == "192.168.1.0/24"
    assert not tool.stop_button.isEnabled()
    assert not tool.camera_button.isEnabled()
    assert tool.table.columnCount() == 6


def test_start_scan_rejects_public_scope(tool, monkeypatch):
    warnings = []
    monkeypatch.setattr(window, "show_warning", lambda *args, **kwargs: warnings.append(args))
    tool.scope_input.setText("8.8.8.0/24")
    tool.start_scan()
    assert warnings
    assert tool.worker is None


def test_start_scan_uses_managed_worker(tool, monkeypatch):
    started = []

    def fake_start(worker, *, cancel=None):
        started.append((worker, cancel))
        return worker

    monkeypatch.setattr(tool, "start_managed_worker", fake_start)
    tool.start_scan()
    assert len(started) == 1
    worker, cancel = started[0]
    assert isinstance(worker, QThread)
    assert cancel == worker.cancel
    assert tool.worker is worker
    assert tool.stop_button.isEnabled()


def test_progress_upserts_and_sorts_devices(tool):
    second = make_device("192.168.1.44", DeviceKind.PC)
    first = make_device("192.168.1.21", DeviceKind.CAMERA)
    tool._handle_progress({"message": "working", "device": second})
    tool._handle_progress({"device": first})
    assert tool.status_label.text() == "working"
    assert [item.host.ip for item in tool.devices] == ["192.168.1.21", "192.168.1.44"]
    assert tool.table.item(0, 3).text() == "Camera"


def test_selection_enables_camera_action_only_for_camera(tool):
    camera = make_device("192.168.1.21", DeviceKind.CAMERA)
    pc = make_device("192.168.1.44", DeviceKind.PC)
    tool._scan_finished([camera, pc])

    tool.table.selectRow(0)
    tool._selection_changed()
    assert tool.camera_button.isEnabled()
    assert "Camera evidence" in tool.detail_area.toPlainText()

    tool.table.selectRow(1)
    tool._selection_changed()
    assert not tool.camera_button.isEnabled()


def test_open_selected_camera_sets_single_host_scope_and_starts(tool, monkeypatch):
    camera = make_device()
    tool._scan_finished([camera])
    tool.table.selectRow(0)
    tool._selection_changed()

    opened = []

    class FakeInput:
        value = ""

        def setText(self, value):
            self.value = value

    class FakeCameraTool:
        def __init__(self):
            self.scope_input = FakeInput()
            self.shown = False
            self.started = False
            opened.append(self)

        def show(self):
            self.shown = True

        def start_audit(self):
            self.started = True

    import pythonkni.camera_auditor.window as camera_window

    monkeypatch.setattr(camera_window, "Tool", FakeCameraTool)
    tool.open_selected_camera()
    assert opened[0].scope_input.value == "192.168.1.21/32"
    assert opened[0].shown is True
    assert opened[0].started is True
    assert opened[0] in tool._camera_windows


def test_finished_cancelled_failed_and_worker_terminal_states(tool, monkeypatch):
    device = make_device()
    tool._scan_finished([device])
    assert "Camera: 1" in tool.status_label.text()

    tool._scan_cancelled()
    assert "cancelado" in tool.status_label.text()

    errors = []
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: errors.append((args, kwargs)))
    tool._scan_failed(RuntimeError("boom"))
    assert errors

    tool.worker = object()
    tool._set_running(True)
    tool._worker_finished()
    assert tool.worker is None
    assert tool.discover_button.isEnabled()
