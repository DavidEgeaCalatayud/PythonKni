from pythonkni.pdf import window as pdf_window


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class FakeWorker:
    def __init__(self, task=None, *args, parent=None, running=False):
        self.task = task
        self.args = args
        self.parent = parent
        self.running = running
        self.started = False
        self.cancelled_flag = False
        self.deleted = False
        self.progress = Signal()
        self.result = Signal()
        self.error = Signal()
        self.cancelled = Signal()
        self.finished = Signal()

    def isRunning(self):
        return self.running

    def start(self):
        self.started = True
        self.running = True

    def cancel(self):
        self.cancelled_flag = True

    def deleteLater(self):
        self.deleted = True


def build_tool(qtbot, monkeypatch):
    monkeypatch.setattr(pdf_window.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_window.QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_window.QMessageBox, "critical", lambda *args, **kwargs: None)
    tool = pdf_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_require_pypdf_and_pick_pdf(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    monkeypatch.setattr(pdf_window, "require_pypdf_available", lambda: True)
    assert tool.require_pypdf()

    critical = []
    monkeypatch.setattr(pdf_window, "require_pypdf_available", lambda: False)
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical.append(args[-1]),
    )
    assert not tool.require_pypdf()
    assert "pypdf" in critical[-1]

    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("C:/file.pdf", ""),
    )
    assert tool.pick_pdf() == "C:/file.pdf"
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )
    assert tool.pick_pdf() is None


def test_start_task_busy_and_signal_wiring(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    info = []
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )
    tool._worker = FakeWorker(running=True)
    assert not tool._start_task("Busy", lambda: None, lambda _result: None)
    assert info
    tool._worker = None

    created = []

    def factory(task, *args, parent=None):
        worker = FakeWorker(task, *args, parent=parent)
        created.append(worker)
        return worker

    monkeypatch.setattr(pdf_window, "Worker", factory)
    handler = lambda result: result
    assert tool._start_task("Working", str, handler, "value")
    worker = created[0]

    assert worker.task is str
    assert worker.args == ("value",)
    assert worker.parent is tool
    assert worker.started
    assert not tool.tabs.isEnabled()
    assert tool.btn_cancel_task.isEnabled()
    assert tool.task_status.text() == "Working"
    assert worker.progress.callbacks == [tool._task_progress]
    assert worker.result.callbacks == [handler]
    assert len(worker.error.callbacks) == 1
    assert worker.cancelled.callbacks == [tool._task_cancelled]
    assert len(worker.finished.callbacks) == 1


def test_task_progress_error_cancel_finish_and_close(qtbot, monkeypatch):
    tool = build_tool(qtbot, monkeypatch)
    critical = []
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "critical",
        lambda *args, **kwargs: critical.append(args[-1]),
    )

    tool._task_progress({"message": "Half", "percent": 50})
    assert tool.task_status.text() == "Half (50%)"
    tool._task_progress({"message": "Already 20%", "percent": 20})
    assert tool.task_status.text() == "Already 20%"
    tool._task_progress({})
    assert tool.task_status.text() == "Procesando..."
    tool._task_progress("plain")
    assert tool.task_status.text() == "plain"

    tool._task_error("Merge", "failure")
    assert "[Merge][ERROR] failure" in tool.log_box.toPlainText()
    assert critical[-1] == "failure"

    tool._task_cancelled()
    assert tool.task_status.text() == "Operación cancelada"
    assert "cancelada" in tool.log_box.toPlainText()

    worker = FakeWorker(running=True)
    tool._worker = worker
    tool.btn_cancel_task.setEnabled(True)
    tool._cancel_task()
    assert worker.cancelled_flag
    assert not tool.btn_cancel_task.isEnabled()
    assert tool.task_status.text() == "Cancelando..."

    worker.running = False
    tool._worker = worker
    tool.task_status.setText("Done")
    tool._task_finished(worker)
    assert tool._worker is None
    assert tool.tabs.isEnabled()
    assert not tool.btn_cancel_task.isEnabled()
    assert tool.task_status.text() == ""
    assert worker.deleted

    worker2 = FakeWorker(running=False)
    tool._worker = None
    tool._close_when_worker_finishes = True
    scheduled = []
    monkeypatch.setattr(
        pdf_window.QTimer,
        "singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )
    tool._task_finished(worker2)
    assert not tool._close_when_worker_finishes
    assert scheduled and scheduled[0][0] == 0

    class CloseEvent:
        def __init__(self):
            self.ignored = False

        def ignore(self):
            self.ignored = True

    running = FakeWorker(running=True)
    tool._worker = running
    event = CloseEvent()
    tool.closeEvent(event)
    assert running.cancelled_flag
    assert tool._close_when_worker_finishes
    assert event.ignored
    assert tool.task_status.text() == "Cancelando antes de cerrar..."


def test_split_actions_and_results(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    tool.require_pypdf = lambda: True
    tool._set_split_mode("rangos")
    assert tool.split_mode.text() == "rangos"
    assert "rangos" in tool.log_box.toPlainText()

    tool.pick_pdf = lambda *_args: str(tmp_path / "picked.pdf")
    tool._split_pick()
    assert tool.split_path.text().endswith("picked.pdf")

    warnings = []
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    tool.split_path.setText("")
    tool._split_run()
    assert warnings

    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    tool.split_path.setText(str(source))
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "",
    )
    tool._split_run()

    calls = []
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(out_dir),
    )
    tool._start_task = lambda *args: calls.append(args) or True
    tool.split_ranges.setText("1-2")
    tool._split_run()
    assert calls[0][0] == "Dividiendo PDF..."
    assert calls[0][-2:] == ("rangos", "1-2")

    info = []
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )
    tool._split_done({"outputs": ["a.pdf", "b.pdf"], "out_dir": str(out_dir)})
    assert "Generados 2 PDFs" in tool.log_box.toPlainText()
    assert info[-1] == "Generados 2 PDFs."


def test_text_pick_preview_run_and_result_messages(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    tool.require_pypdf = lambda: True
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    tool.pick_pdf = lambda *_args: str(source)
    tool._text_pick()
    assert tool.text_src.text() == str(source)

    warnings = []
    info = []
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "information",
        lambda *args, **kwargs: info.append(args[-1]),
    )

    calls = []
    tool._start_task = lambda *args: calls.append(args) or True
    tool.text_src.setText("")
    tool._text_preview()
    assert warnings

    tool.text_src.setText(str(source))
    tool._text_preview()
    assert calls[-1][0] == "Generando vista previa..."
    tool._text_preview_done({"preview": "hello", "pages": 2})
    assert info[-1] == "hello"

    tool.text_src.setText("")
    tool._text_run_md()
    tool.text_src.setText(str(source))

    tool.chk_one_file_per_page.setChecked(True)
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "",
    )
    before = len(calls)
    tool._text_run_md()
    assert len(calls) == before

    output_dir = tmp_path / "markdown"
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(output_dir),
    )
    tool._text_run_md()
    assert calls[-1][0] == "Extrayendo texto..."
    assert calls[-1][-2] == str(output_dir)
    assert calls[-1][-1] is None

    tool.chk_one_file_per_page.setChecked(False)
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "text"), ""),
    )
    tool._text_run_md()
    assert calls[-1][-1].endswith("text.md")

    result = {
        "logs": ["line one"],
        "ocr_warning": "OCR unavailable",
        "empty_ratio": 80,
        "threshold": 60,
        "empty_pages": 4,
        "total": 5,
    }
    tool._text_extract_done(result)
    assert any("OCR unavailable" in message for message in warnings)
    assert any("probablemente es escaneado" in message for message in warnings)
    assert "Probablemente escaneado" in tool.log_box.toPlainText()

    result.update({"ocr_warning": "", "empty_ratio": 20, "empty_pages": 1})
    tool._text_extract_done(result)
    assert "Páginas vacías: 1/5" in tool.log_box.toPlainText()


def test_extract_pages_actions(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    tool.require_pypdf = lambda: True
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    tool.pick_pdf = lambda *_args: str(source)
    tool._extract_pick()
    assert tool.extract_path.text() == str(source)

    warnings = []
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    tool.extract_path.setText("")
    tool._extract_run()
    tool.extract_path.setText(str(source))
    tool.extract_spec.setText("")
    tool._extract_run()
    assert len(warnings) >= 2

    tool.extract_spec.setText("1,3")
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool._extract_run()

    calls = []
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "extract"), ""),
    )
    tool._start_task = lambda *args: calls.append(args) or True
    tool._extract_run()
    assert calls[-1][-1].endswith("extract.pdf")

    tool._extract_done({"save_path": "extract.pdf", "page_count": 2})
    assert "páginas: 2" in tool.log_box.toPlainText()


def test_reorder_actions(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    tool.require_pypdf = lambda: True
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")

    tool.pick_pdf = lambda *_args: None
    tool._reorder_pick()
    assert tool.reorder_src.text() == ""

    calls = []
    tool.pick_pdf = lambda *_args: str(source)
    tool._start_task = lambda *args: calls.append(args) or True
    tool._reorder_pick()
    assert calls[-1][0] == "Leyendo páginas..."

    tool._reorder_loaded({"src": str(source), "page_count": 3})
    assert tool.page_list.count() == 3
    assert tool.page_list.item(2).text() == "Página 3"

    warnings = []
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    tool.reorder_src.setText("")
    tool._reorder_save()
    tool.reorder_src.setText(str(source))
    tool.page_list.clear()
    tool._reorder_save()
    assert len(warnings) >= 2

    tool._reorder_loaded({"src": str(source), "page_count": 3})
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "reordered"), ""),
    )
    tool._reorder_save()
    assert calls[-1][-2] == [1, 2, 3]
    assert calls[-1][-1].endswith("reordered.pdf")

    tool._reorder_done({"save_path": "reordered.pdf"})
    assert "reordered.pdf" in tool.log_box.toPlainText()


def test_merge_add_remove_move_run_and_done(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch)
    tool.require_pypdf = lambda: True
    first = tmp_path / "one.pdf"
    second = tmp_path / "two.pdf"
    third = tmp_path / "three.pdf"
    for path in (first, second, third):
        path.write_bytes(b"pdf")

    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(first), str(second), str(first)], ""),
    )
    tool._merge_add()
    assert tool._merge_paths == [str(first), str(second)]
    assert tool.merge_list.count() == 2

    tool.merge_list.setCurrentRow(0)
    tool._move_item(tool.merge_list, -1)
    assert tool._merge_paths == [str(first), str(second)]
    tool._move_item(tool.merge_list, 1)
    assert tool._merge_paths == [str(second), str(first)]

    tool.merge_list.setCurrentRow(1)
    tool._merge_remove()
    assert tool._merge_paths == [str(second)]

    warnings = []
    monkeypatch.setattr(
        pdf_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[-1]),
    )
    tool._merge_run()
    assert warnings

    tool._merge_paths = [str(first), str(second), str(third)]
    tool._merge_refresh()
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool._merge_run()

    calls = []
    monkeypatch.setattr(
        pdf_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "combined"), ""),
    )
    tool._start_task = lambda *args: calls.append(args) or True
    tool._merge_run()
    assert calls[-1][-2] == [str(first), str(second), str(third)]
    assert calls[-1][-1].endswith("combined.pdf")

    tool._merge_done({"save_path": "combined.pdf"})
    assert "combined.pdf" in tool.log_box.toPlainText()
