from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QObject, pyqtSignal

from pythonkni.converter import window as converter_window


class FakeWorker(QObject):
    progress = pyqtSignal(object)
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    cancelled = pyqtSignal()
    finished = pyqtSignal()

    created = []

    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.args = args
        self.kwargs = kwargs
        self.running = False
        self.cancel_requested = False
        self.deleted = False
        self.__class__.created.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancel_requested = True

    def deleteLater(self):
        self.deleted = True


class CloseEventStub:
    def __init__(self):
        self.ignored = False

    def ignore(self):
        self.ignored = True


def _tool(qtbot):
    tool = converter_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_start_conversion_wires_worker_progress_result_and_finish(qtbot, monkeypatch):
    FakeWorker.created.clear()
    monkeypatch.setattr(converter_window, "Worker", FakeWorker)
    info = []
    warnings = []
    monkeypatch.setattr(
        converter_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )
    monkeypatch.setattr(
        converter_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    tool = _tool(qtbot)

    convert = lambda *_args, **_kwargs: None
    tool._start_conversion("Trabajando...", convert, ("a", "b"), "Hecho")

    worker = FakeWorker.created[-1]
    assert worker.args[0] is converter_window.conversion_task
    assert worker.args[1] is convert
    assert worker.args[2] == ("a", "b")
    assert worker.running
    assert tool.task_status.text() == "Trabajando..."
    assert tool.btn_cancel.isEnabled()

    worker.progress.emit({"message": "Mitad"})
    assert tool.task_status.text() == "Mitad"
    worker.progress.emit("Casi")
    assert tool.task_status.text() == "Casi"

    worker.result.emit(converter_window.ConversionResult.completed(["out.txt"]))
    assert info[-1][1:] == ("Conversión completada", "Hecho")
    assert not warnings

    worker.running = False
    worker.finished.emit()
    assert tool._worker is None
    assert not tool.btn_cancel.isEnabled()
    assert tool.task_status.text() == ""
    assert worker.deleted


def test_start_conversion_and_batch_reject_overlapping_worker(qtbot, monkeypatch):
    tool = _tool(qtbot)
    running = SimpleNamespace(isRunning=lambda: True)
    tool._worker = running
    calls = []
    monkeypatch.setattr(
        converter_window.QMessageBox,
        "information",
        lambda *args: calls.append(args),
    )

    tool._start_conversion("one", lambda: None, (), "done")
    tool._start_batch_conversion("many", lambda: None, [], "done")

    assert len(calls) == 2
    assert all("curso" in call[2] for call in calls)
    assert tool._worker is running


def test_start_batch_conversion_uses_batch_task(qtbot, monkeypatch):
    FakeWorker.created.clear()
    monkeypatch.setattr(converter_window, "Worker", FakeWorker)
    tool = _tool(qtbot)
    convert = lambda *_args, **_kwargs: None
    jobs = [("a.txt", "a.kml")]

    tool._start_batch_conversion("Batch", convert, jobs, "done")

    worker = FakeWorker.created[-1]
    assert worker.args[0] is converter_window.batch_conversion_task
    assert worker.args[1] is convert
    assert worker.args[2] == jobs
    worker.running = False
    worker.finished.emit()


def test_conversion_done_covers_callable_warning_plain_result_and_failure(qtbot, monkeypatch):
    tool = _tool(qtbot)
    info = []
    warnings = []
    feedback = []
    monkeypatch.setattr(
        converter_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )
    monkeypatch.setattr(
        converter_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    monkeypatch.setattr(
        converter_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool._conversion_done(lambda outputs: f"{len(outputs)} outputs", "legacy.txt")
    assert info[-1][2] == "1 outputs"

    result = converter_window.ConversionResult.completed(["a", "b"], warnings=["fallback"])
    tool._conversion_done(lambda outputs: f"{len(outputs)} outputs", result)
    assert warnings[-1][1] == "Conversión completada con avisos"
    assert "2 outputs" in warnings[-1][2]
    assert "fallback" in warnings[-1][2]

    tool._conversion_done("unused", converter_window.ConversionResult(False))
    assert feedback[-1][0][1] == "Conversión fallida"
    assert feedback[-1][1]["details"] is None


def test_conversion_error_string_and_cancelled_state(qtbot, monkeypatch):
    tool = _tool(qtbot)
    feedback = []
    monkeypatch.setattr(
        converter_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool._conversion_error("plain diagnostic")
    assert feedback[-1][1]["details"] == "plain diagnostic"
    tool._conversion_cancelled()
    assert tool.task_status.text() == "Conversión cancelada"


def test_cancel_and_close_request_running_worker(qtbot):
    tool = _tool(qtbot)
    worker = FakeWorker(parent=tool)
    worker.running = True
    tool._worker = worker
    tool.btn_cancel.setEnabled(True)

    tool.cancel_conversion()
    assert worker.cancel_requested
    assert not tool.btn_cancel.isEnabled()
    assert tool.task_status.text() == "Cancelando..."

    worker.cancel_requested = False
    event = CloseEventStub()
    tool.closeEvent(event)
    assert event.ignored
    assert worker.cancel_requested
    assert tool._close_when_worker_finishes
    assert tool.task_status.text() == "Cancelando antes de cerrar..."


def test_finished_preserves_cancelled_status_and_schedules_deferred_close(qtbot, monkeypatch):
    tool = _tool(qtbot)
    worker = FakeWorker(parent=tool)
    tool._worker = worker
    tool.task_status.setText("Conversión cancelada")
    tool._close_when_worker_finishes = True
    callbacks = []
    monkeypatch.setattr(
        converter_window,
        "QTimer",
        SimpleNamespace(singleShot=lambda _delay, callback: callbacks.append(callback)),
    )
    closed = []
    monkeypatch.setattr(tool, "close", lambda: closed.append(True))

    tool._conversion_finished(worker)

    assert tool.task_status.text() == "Conversión cancelada"
    assert not tool._close_when_worker_finishes
    assert callbacks
    callbacks[0]()
    assert closed == [True]


@pytest.mark.parametrize(
    ("method_name", "source_title", "output_path", "expected_function", "expected_label"),
    [
        ("convert_text_to_docx", "source.txt", "result.docx", "text_to_docx", "Creando DOCX..."),
        ("convert_docx_to_text", "source.docx", "result.txt", "docx_to_text", "Extrayendo texto..."),
        ("convert_docx_to_pdf", "source.docx", "result.pdf", "docx_to_pdf", "Creando PDF..."),
    ],
)
def test_single_file_conversion_dialog_flows(
    qtbot,
    monkeypatch,
    method_name,
    source_title,
    output_path,
    expected_function,
    expected_label,
):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (source_title, ""),
    )
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (output_path, ""),
    )
    monkeypatch.setattr(tool, "_start_conversion", lambda *args: calls.append(args))

    getattr(tool, method_name)()

    assert calls[0][0] == expected_label
    assert calls[0][1] is getattr(converter_window, expected_function)
    assert calls[0][2] == (source_title, output_path)
    assert output_path in calls[0][3]


def test_images_and_pdf_dialog_flows(qtbot, monkeypatch):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(tool, "_start_conversion", lambda *args: calls.append(args))

    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (["a.png", "b.jpg"], ""),
    )
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("images.pdf", ""),
    )
    tool.convert_images_to_pdf()
    assert calls[-1][1] is converter_window.images_to_pdf
    assert calls[-1][2] == (["a.png", "b.jpg"], "images.pdf")

    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("source.pdf", ""),
    )
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "images",
    )
    tool.convert_pdf_to_images()
    assert calls[-1][1] is converter_window.pdf_to_images
    assert calls[-1][2] == ("source.pdf", "images")
    assert calls[-1][3](["1.png", "2.png"]).startswith("Se han guardado 2 imágenes")


def test_dialog_cancellation_does_not_start_conversion(qtbot, monkeypatch):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(tool, "_start_conversion", lambda *args: calls.append(args))
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([], ""),
    )
    tool.convert_images_to_pdf()

    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("source.txt", ""),
    )
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool.convert_text_to_docx()

    assert calls == []


def test_files_with_extension_filters_case_insensitively(qtbot, monkeypatch):
    tool = _tool(qtbot)
    monkeypatch.setattr(converter_window.os, "listdir", lambda _path: ["a.TXT", "b.txt", "c.kml"])

    assert tool._files_with_extension("folder", ".txt") == [
        converter_window.os.path.join("folder", "a.TXT"),
        converter_window.os.path.join("folder", "b.txt"),
    ]


@pytest.mark.parametrize(
    ("method_name", "extension", "source_function", "output_extension"),
    [
        ("convert_text_to_kml", ".txt", "text_to_kml", ".kml"),
        ("convert_kml_to_text", ".kml", "kml_to_text", ".txt"),
    ],
)
def test_batch_folder_conversion_builds_jobs(
    qtbot,
    monkeypatch,
    method_name,
    extension,
    source_function,
    output_extension,
):
    tool = _tool(qtbot)
    directories = iter(["source", "destination"])
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: next(directories),
    )
    sources = [f"source/a{extension}", f"source/b{extension}"]
    monkeypatch.setattr(tool, "_files_with_extension", lambda *_args: sources)
    calls = []
    monkeypatch.setattr(tool, "_start_batch_conversion", lambda *args: calls.append(args))

    getattr(tool, method_name)()

    assert calls[0][1] is getattr(converter_window, source_function)
    assert calls[0][2] == [
        (sources[0], converter_window.os.path.join("destination", f"a{output_extension}")),
        (sources[1], converter_window.os.path.join("destination", f"b{output_extension}")),
    ]
    assert calls[0][3](["one", "two"]).startswith("Se convirtieron 2 archivos")


@pytest.mark.parametrize(
    ("method_name", "extension"),
    [("convert_text_to_kml", ".txt"), ("convert_kml_to_text", ".kml")],
)
def test_batch_folder_conversion_warns_when_folder_has_no_matching_files(
    qtbot, monkeypatch, method_name, extension
):
    tool = _tool(qtbot)
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "source",
    )
    monkeypatch.setattr(tool, "_files_with_extension", lambda *_args: [])
    warnings = []
    monkeypatch.setattr(
        converter_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    getattr(tool, method_name)()

    assert warnings
    assert extension in warnings[-1][2]


@pytest.mark.parametrize(
    ("method_name", "source", "output", "source_function"),
    [
        ("convert_text_to_kml", "one.txt", "one.kml", "text_to_kml"),
        ("convert_kml_to_text", "one.kml", "one.txt", "kml_to_text"),
    ],
)
def test_batch_capable_conversion_falls_back_to_single_file(
    qtbot, monkeypatch, method_name, source, output, source_function
):
    tool = _tool(qtbot)
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "",
    )
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (source, ""),
    )
    monkeypatch.setattr(
        converter_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (output, ""),
    )
    calls = []
    monkeypatch.setattr(tool, "_start_conversion", lambda *args: calls.append(args))

    getattr(tool, method_name)()

    assert calls[0][1] is getattr(converter_window, source_function)
    assert calls[0][2] == (source, output)
