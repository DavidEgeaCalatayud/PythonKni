import csv
import json
import threading
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QThread

from pythonkni.camera_auditor import window
from pythonkni.camera_auditor.models import (
    AuditProgress,
    CameraDevice,
    CameraServiceFinding,
    RiskLevel,
)


def make_device(ip="192.168.1.21", vendor="Reolink"):
    return CameraDevice(
        ip=ip,
        vendor=vendor,
        name="Front Door",
        hardware="RLC-810A",
        services=(
            CameraServiceFinding(
                "HTTP",
                80,
                endpoint=f"http://{ip}:80/",
                status="HTTP/1.0 401 Unauthorized",
                auth_required=True,
                cleartext=True,
                evidence=vendor,
            ),
            CameraServiceFinding(
                "RTSP",
                554,
                endpoint=f"rtsp://{ip}:554/",
                status="RTSP/1.0 401 Unauthorized",
                auth_required=True,
                cleartext=True,
            ),
        ),
        onvif=True,
        confidence="Alta",
        risk=RiskLevel.MEDIUM,
        risk_reasons=("HTTP cleartext", "RTSP exposed"),
        onvif_scopes=("onvif://www.onvif.org/name/Front_Door",),
        onvif_xaddrs=(f"http://{ip}/onvif/device_service",),
    )


def test_helpers_render_auth_serialization_and_report():
    device = make_device()
    assert window._auth_label(True) == "Requerida"
    assert window._auth_label(False) == "No requerida"
    assert window._auth_label(None) == "No determinada"
    serialized = window._device_to_dict(device)
    assert serialized["risk"] == "MEDIUM"
    assert serialized["services"][0]["protocol"] == "HTTP"
    report = window._device_report(device)
    assert "Front Door" in report
    assert "Autenticación: Requerida" in report
    assert "ONVIF XAddrs" in report


def test_device_report_uses_fallbacks_for_missing_optional_metadata():
    device = CameraDevice(
        ip="192.168.1.5",
        vendor="Unknown",
        name="",
        hardware="",
        services=(CameraServiceFinding("ONVIF", 3702),),
        onvif=True,
        confidence="Alta",
        risk=RiskLevel.LOW,
    )
    report = window._device_report(device)
    assert "Name: No anunciado" in report
    assert "Hardware: No anunciado" in report
    assert "Estado: Detectado" in report
    assert "Endpoint: No anunciado" in report


def test_default_scope_uses_interface_caps_large_network_and_falls_back(monkeypatch):
    monkeypatch.setattr(
        window,
        "detect_default_network",
        lambda: SimpleNamespace(cidr="192.168.4.0/24", address="192.168.4.20"),
    )
    assert window._default_scope() == "192.168.4.0/24"

    monkeypatch.setattr(
        window,
        "detect_default_network",
        lambda: SimpleNamespace(cidr="10.0.0.0/16", address="10.0.4.20"),
    )
    assert window._default_scope() == "10.0.4.0/24"

    def fail():
        raise RuntimeError("no interface")

    monkeypatch.setattr(window, "detect_default_network", fail)
    assert window._default_scope() == "192.168.1.0/24"


def test_run_audit_reuses_worker_cancellation_and_progress(monkeypatch):
    captured = {}

    def fake_audit(scope, protocols, stop_event, on_progress):
        captured.update(
            scope=scope,
            protocols=protocols,
            stop_event=stop_event,
            on_progress=on_progress,
        )
        return [make_device()]

    monkeypatch.setattr(window, "audit_camera_exposure", fake_audit)
    progress = []
    worker = SimpleNamespace(cancel_event=threading.Event(), report_progress=progress.append)
    result = window._run_audit(worker, "192.168.1.0/24", ("ONVIF",))
    assert result[0].ip == "192.168.1.21"
    assert captured["scope"] == "192.168.1.0/24"
    assert captured["stop_event"] is worker.cancel_event
    assert captured["on_progress"] == progress.append


@pytest.fixture
def tool(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    monkeypatch.setattr(window, "CAMERA_REPORTS_DIR", tmp_path / "camera_audits")
    monkeypatch.setattr(window, "ensure_app_dirs", lambda: None)
    instance = window.Tool()
    qtbot.addWidget(instance)
    return instance


def test_tool_initial_state_and_protocol_selection(tool):
    assert tool.scope_input.text() == "192.168.1.0/24"
    assert tool._selected_protocols() == ("HTTP", "HTTPS", "RTSP", "ONVIF")
    assert not tool.stop_button.isEnabled()
    assert not tool.export_button.isEnabled()
    tool._set_running(True)
    assert not tool.scope_input.isEnabled()
    assert tool.stop_button.isEnabled()
    tool._set_running(False)
    assert tool.scope_input.isEnabled()


def test_start_audit_rejects_invalid_scope_and_empty_protocols(tool, monkeypatch):
    warnings = []
    monkeypatch.setattr(window, "show_warning", lambda *args: warnings.append(args))
    tool.scope_input.setText("8.8.8.0/24")
    tool.start_audit()
    assert warnings

    warnings.clear()
    tool.scope_input.setText("192.168.1.0/24")
    for check in tool.protocol_checks.values():
        check.setChecked(False)
    tool.start_audit()
    assert warnings
    assert "al menos un protocolo" in warnings[0][2]


def test_start_audit_wires_managed_worker_without_starting_network(tool, monkeypatch):
    started = []

    def fake_start(worker, *, cancel=None):
        started.append((worker, cancel))
        return worker

    monkeypatch.setattr(tool, "start_managed_worker", fake_start)
    tool.start_audit()
    assert len(started) == 1
    worker, cancel = started[0]
    assert isinstance(worker, QThread)
    assert cancel == worker.cancel
    assert tool.worker is worker
    assert tool.stop_button.isEnabled()
    assert "Auditando 192.168.1.0/24" in tool.status_label.text()


def test_start_audit_ignores_duplicate_running_worker(tool):
    class RunningWorker:
        @staticmethod
        def isRunning():
            return True

    tool.worker = RunningWorker()
    tool.start_audit()
    assert tool.worker.__class__ is RunningWorker


def test_progress_upserts_sorts_updates_selection_and_results(tool):
    second = make_device("192.168.1.44", "Hikvision")
    first = make_device("192.168.1.21", "Reolink")
    tool._handle_progress(AuditProgress("status", 0, 254, "Buscando ONVIF..."))
    assert tool.status_label.text() == "Buscando ONVIF..."

    tool._handle_progress(AuditProgress("device", 1, 254, device=second))
    tool._handle_progress(AuditProgress("device", 2, 254, device=first))
    assert [device.ip for device in tool.devices] == ["192.168.1.21", "192.168.1.44"]
    assert tool.table.rowCount() == 2
    assert tool.export_button.isEnabled()

    updated = make_device("192.168.1.21", "Reolink Updated")
    tool._upsert_device(updated)
    assert tool.devices[0].vendor == "Reolink Updated"
    assert tool.table.item(0, 1).text() == "Reolink Updated"

    tool.table.selectRow(0)
    tool._selection_changed()
    assert "192.168.1.21" in tool.detail_area.toPlainText()
    assert tool.report_button.isEnabled()

    tool._audit_finished([second])
    assert tool.table.rowCount() == 1
    assert "1 candidatos" in tool.status_label.text()


def test_selection_and_worker_terminal_states(tool, monkeypatch):
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: None)
    assert tool._selected_ip() is None
    assert tool._selected_device() is None
    tool._selection_changed()
    assert not tool.report_button.isEnabled()

    tool.devices = [make_device()]
    tool._audit_cancelled()
    assert "cancelada" in tool.status_label.text().lower()
    assert tool.export_button.isEnabled()

    tool._audit_failed(ValueError("boom"))
    assert "error" in tool.status_label.text().lower()
    tool._worker_finished()
    assert tool.worker is None


def test_audit_failed_supports_non_exception_error(tool, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: calls.append((args, kwargs)))
    tool._audit_failed("technical failure")
    assert calls[0][1]["details"] == "technical failure"


def test_stop_audit_cancels_running_worker(tool):
    class RunningWorker:
        def __init__(self):
            self.cancelled = False

        @staticmethod
        def isRunning():
            return True

        def cancel(self):
            self.cancelled = True

    worker = RunningWorker()
    tool.worker = worker
    tool.stop_button.setEnabled(True)
    tool.stop_audit()
    assert worker.cancelled
    assert not tool.stop_button.isEnabled()
    assert "Cancelando" in tool.status_label.text()


def test_stop_audit_is_noop_without_running_worker(tool):
    tool.worker = None
    tool.stop_audit()
    assert not tool.stop_button.isEnabled()


def test_detailed_report_requires_selection_and_renders_json(tool, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "show_feedback", lambda *args: calls.append(args))
    tool.show_detailed_report()
    assert calls == []

    tool.devices = [make_device()]
    tool._rebuild_table()
    tool.table.selectRow(0)
    tool.show_detailed_report()
    assert len(calls) == 1
    feedback = calls[0][1]
    assert "192.168.1.21" in feedback.title
    assert '"vendor": "Reolink"' in feedback.details


def test_export_results_warns_when_empty_or_dialog_cancelled(tool, monkeypatch):
    warnings = []
    monkeypatch.setattr(window, "show_warning", lambda *args: warnings.append(args))
    tool.export_results()
    assert warnings

    tool.devices = [make_device()]
    monkeypatch.setattr(window.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    tool.export_results()


def test_export_results_writes_json_and_csv_safely(tool, monkeypatch, tmp_path):
    dangerous = make_device(vendor='=WEBSERVICE("https://example.invalid")')
    tool.devices = [dangerous]

    json_path = tmp_path / "audit"
    monkeypatch.setattr(
        window.QFileDialog,
        "getSaveFileName",
        lambda *args: (str(json_path), "JSON (*.json)"),
    )
    tool.export_results()
    payload = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert payload[0]["ip"] == "192.168.1.21"

    csv_path = tmp_path / "audit.csv"
    monkeypatch.setattr(
        window.QFileDialog,
        "getSaveFileName",
        lambda *args: (str(csv_path), "CSV (*.csv)"),
    )
    tool.export_results()
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "ip"
    assert rows[1][1].startswith("'")


def test_export_results_reports_unsupported_format_and_write_errors(tool, monkeypatch, tmp_path):
    tool.devices = [make_device()]
    errors = []
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: errors.append((args, kwargs)))
    monkeypatch.setattr(
        window.QFileDialog,
        "getSaveFileName",
        lambda *args: (str(tmp_path / "audit.txt"), "JSON (*.json)"),
    )
    tool.export_results()
    assert errors

    errors.clear()
    target = tmp_path / "missing" / "audit.json"
    monkeypatch.setattr(
        window.QFileDialog,
        "getSaveFileName",
        lambda *args: (str(target), "JSON (*.json)"),
    )
    tool.export_results()
    assert errors
