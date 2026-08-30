from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QPlainTextEdit, QPushButton

from pythonkni.event_viewer import window as event_window
from pythonkni.event_viewer.models import EventItem, EventResult


def make_event(**overrides):
    values = {
        "date": "30/08/2026 10:00:00",
        "level": "Error",
        "level_number": 2,
        "provider": "Disk",
        "event_id": "7",
        "category": "Storage",
        "message": "Disk error",
        "risk": "Alto",
        "interpretation": "Check disk",
        "log_name": "System",
        "record_id": "42",
        "computer": "TEST-PC",
        "process_id": "4",
        "thread_id": "8",
        "raw_xml": "<Event />",
        "timestamp_sort": "20260830100000",
    }
    values.update(overrides)
    return EventItem(**values)


def build_tool(qtbot, monkeypatch):
    monkeypatch.setattr(event_window.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(event_window.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(event_window.QMessageBox, "critical", lambda *args, **kwargs: None)
    tool = event_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_event_worker_success_failure_and_cancel(qtbot, monkeypatch):
    expected = EventResult([make_event()], ["warning"])
    monkeypatch.setattr(event_window, "collect_events", lambda *args, **kwargs: expected)
    worker = event_window.EventWorker(["System"], 24, 10, False)
    results = []
    failures = []
    worker.result_ready.connect(results.append)
    worker.failed.connect(failures.append)

    worker.run()
    assert results == [expected]
    assert failures == []

    worker.cancel()
    assert worker._cancel_event.is_set()

    monkeypatch.setattr(
        event_window,
        "collect_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    failed_worker = event_window.EventWorker(["System"], 24, 10, False)
    failed_worker.failed.connect(failures.append)
    failed_worker.run()
    assert failures[-1] == "boom"


def test_event_detail_dialog_populates_and_copies(qtbot):
    item = make_event()
    dialog = event_window.EventDetailDialog(item)
    qtbot.addWidget(dialog)

    editor = dialog.findChild(QPlainTextEdit)
    button = dialog.findChild(QPushButton)
    assert editor is not None
    assert "Disk error" in editor.toPlainText()
    assert button is not None

    button.click()
    assert event_window.QApplication.clipboard().text() == item.detail_text()


def test_selected_logs_period_and_button_state(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    assert tool.selected_logs() == ["Application", "System"]

    tool.chk_application.setChecked(False)
    tool.chk_security.setChecked(True)
    assert tool.selected_logs() == ["System", "Security"]

    calls = []
    tool.refresh_events = lambda: calls.append("refresh")
    tool.set_period_and_refresh(24 * 7)
    assert tool.cmb_period.currentData() == 24 * 7
    assert calls == ["refresh"]

    tool.set_buttons_enabled(False)
    assert not tool.btn_refresh.isEnabled()
    assert not tool.btn_report.isEnabled()
    tool.set_buttons_enabled(True)
    assert tool.btn_refresh.isEnabled()
    assert tool.btn_report.isEnabled()


def test_refresh_events_requires_log_and_starts_worker(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    warnings = []
    monkeypatch.setattr(
        event_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    tool.chk_application.setChecked(False)
    tool.chk_system.setChecked(False)
    tool.chk_security.setChecked(False)
    tool.refresh_events()
    assert warnings

    class Signal:
        def __init__(self):
            self.callback = None

        def connect(self, callback):
            self.callback = callback

    class FakeWorker:
        def __init__(self, logs, hours, max_events, include_info):
            self.args = (logs, hours, max_events, include_info)
            self.result_ready = Signal()
            self.failed = Signal()
            self.started = False
            self.cancelled = False

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(event_window, "EventWorker", FakeWorker)
    tool.chk_system.setChecked(True)
    tool.chk_info.setChecked(True)
    tool.spn_max.setValue(40)
    tool.refresh_events()

    assert tool.worker.args == (["System"], 24, 40, True)
    assert tool.worker.started
    assert not tool.btn_refresh.isEnabled()
    assert not tool.btn_cancel.isHidden()
    assert tool.status.text() == "Leyendo eventos de Windows..."
    assert tool.worker.result_ready.callback == tool.on_events_loaded
    assert tool.worker.failed.callback == tool.on_events_failed

    tool.cancel_loading()
    assert tool.worker.cancelled
    assert tool.btn_cancel.isHidden()
    assert tool.status.text() == "Cancelando lectura..."

    tool.worker = None
    tool.cancel_loading()
    assert tool.status.text() == "Cancelando lectura..."


def test_loaded_failed_filtering_summary_and_styles(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    events = [
        make_event(provider="Disk", risk="Alto", level="Error", level_number=2),
        make_event(
            provider="DNS Client Events",
            event_id="1014",
            risk="Medio",
            level="Advertencia",
            level_number=3,
            message="DNS warning",
            interpretation="Check DNS",
        ),
        make_event(
            provider="Kernel-Power",
            event_id="41",
            risk="Bajo",
            level="Crítico",
            level_number=1,
            message="Power",
        ),
    ]
    result = EventResult(events, ["first warning", "second", "third", "fourth"])
    tool.on_events_loaded(result)

    assert tool.table.rowCount() == 3
    assert tool.visible_events == events
    assert "Eventos: 3" in tool.lbl_summary.text()
    assert "1 avisos más" in tool.status.text()
    assert tool.btn_refresh.isEnabled()
    assert not tool.btn_cancel.isVisible()

    risk_item = tool.table.item(0, 7)
    assert risk_item.background().color() == event_window.RISK_COLORS["Alto"]
    plain = event_window.QTableWidgetItem("x")
    tool.apply_risk_style(plain, "Unknown")
    assert plain.background().color() != QColor("#ffcccc")

    tool.cmb_filter_level.setCurrentIndex(tool.cmb_filter_level.findData("Advertencia"))
    assert tool.table.rowCount() == 1
    assert tool.visible_events[0].provider == "DNS Client Events"

    tool.cmb_filter_level.setCurrentIndex(0)
    tool.cmb_filter_risk.setCurrentIndex(tool.cmb_filter_risk.findData("Alto"))
    assert tool.table.rowCount() == 1
    assert tool.visible_events[0].risk == "Alto"

    tool.cmb_filter_risk.setCurrentIndex(0)
    tool.txt_search.setText("kernel-power")
    assert tool.table.rowCount() == 1
    assert tool.visible_events[0].provider == "Kernel-Power"
    assert "mostrando 1" in tool.build_summary()

    tool.events = []
    tool.visible_events = []
    assert tool.build_summary() == "Sin eventos cargados."

    critical = []
    monkeypatch.setattr(
        event_window.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical.append(args[-1]),
    )
    tool.on_events_failed("access denied")
    assert tool.events == []
    assert tool.table.rowCount() == 0
    assert tool.lbl_summary.text() == "Error al cargar eventos."
    assert critical == ["access denied"]


def test_selected_event_detail_copy_and_no_selection(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    item = make_event()
    tool.events = [item]
    tool.populate_table()
    info = []
    monkeypatch.setattr(
        event_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )

    assert tool.selected_event() is None
    tool.show_detail()
    tool.copy_selected_event()
    assert len(info) == 2

    tool.table.selectRow(0)
    assert tool.selected_event() is item

    executed = []

    class FakeDialog:
        def __init__(self, event, parent):
            executed.append((event, parent))

        def exec_(self):
            executed.append("exec")

    monkeypatch.setattr(event_window, "EventDetailDialog", FakeDialog)
    tool.show_detail()
    assert executed[-1] == "exec"

    tool.copy_selected_event()
    assert event_window.QApplication.clipboard().text() == item.detail_text()
    assert tool.status.text() == "Evento copiado al portapapeles."

    tool.visible_events = []
    assert tool.selected_event() is None


def test_exports_cover_empty_cancel_success_and_pdf_errors(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    info = []
    warnings = []
    critical = []
    monkeypatch.setattr(
        event_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )
    monkeypatch.setattr(
        event_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    monkeypatch.setattr(
        event_window.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical.append(args[-1]),
    )

    tool.events = []
    tool.export_csv()
    tool.export_html()
    tool.export_pdf()
    assert len(info) == 3

    item = make_event(provider="=Formula", message="+danger")
    tool.events = [item]
    monkeypatch.setattr(
        event_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool.export_csv()
    tool.export_html()

    csv_path = tmp_path / "events.csv"
    monkeypatch.setattr(
        event_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(csv_path), ""),
    )
    tool.export_csv()
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "'=Formula" in content
    assert "'+danger" in content

    html_path = tmp_path / "events.html"
    monkeypatch.setattr(event_window, "events_to_html", lambda events: "<html>ok</html>")
    monkeypatch.setattr(
        event_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(html_path), ""),
    )
    tool.export_html()
    assert html_path.read_text(encoding="utf-8") == "<html>ok</html>"

    monkeypatch.setattr(event_window, "_REPORTLAB_AVAILABLE", False)
    tool.export_pdf()
    assert warnings

    monkeypatch.setattr(event_window, "_REPORTLAB_AVAILABLE", True)
    monkeypatch.setattr(
        event_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool.export_pdf()

    pdf_path = tmp_path / "events.pdf"
    pdf_calls = []
    monkeypatch.setattr(
        event_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(pdf_path), ""),
    )
    monkeypatch.setattr(
        event_window,
        "events_to_pdf",
        lambda events, summary, path: pdf_calls.append((events, summary, path)),
    )
    tool.export_pdf()
    assert pdf_calls and pdf_calls[0][2] == str(pdf_path)

    monkeypatch.setattr(
        event_window,
        "events_to_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pdf failed")),
    )
    tool.export_pdf()
    assert "pdf failed" in critical[-1]


def test_open_event_viewer_and_add_to_report(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    info = []
    critical = []
    monkeypatch.setattr(
        event_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )
    monkeypatch.setattr(
        event_window.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical.append(args[-1]),
    )

    popen_calls = []
    monkeypatch.setattr(
        event_window.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )
    tool.open_windows_event_viewer()
    assert popen_calls

    monkeypatch.setattr(
        event_window.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing")),
    )
    tool.open_windows_event_viewer()
    assert "missing" in critical[-1]

    tool.events = []
    tool.add_to_technical_report()
    assert any("No hay eventos" in message for message in info)

    events = [
        make_event(provider="Disk", risk="Alto", level_number=2, record_id="1"),
        make_event(provider="Disk", risk="Medio", level_number=3, record_id="2"),
        make_event(provider="DNS", risk="Normal", level_number=4, record_id="3"),
    ]
    tool.events = events
    snapshot = tmp_path / "snapshot.json"
    captured = []

    def save(selected, summary):
        captured.append((selected, summary))
        return snapshot

    monkeypatch.setattr(event_window, "save_events_snapshot", save)
    tool.add_to_technical_report()

    assert captured
    selected, summary = captured[0]
    assert selected[0].risk == "Alto"
    assert summary["total"] == 3
    assert summary["errors"] == 1
    assert summary["warnings"] == 1
    assert summary["high_risk"] == 1
    assert summary["medium_risk"] == 1
    assert summary["top_providers"][0] == {"provider": "Disk", "count": 2}
    assert str(snapshot) in info[-1]
