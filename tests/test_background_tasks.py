from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PyPDF2 import PdfWriter

from tools.pdf_merge_tool import Tool as PdfTool
from tools.pdf_tasks import extract_text_task, preview_text_task, split_pdf_task
from tools.process_manager_tool import Tool as ProcessTool
from tools.process_manager_tool import VirusTotalResult, analyze_process_task
from tools.worker import WorkerCancelled


class FakeWorker:
    def __init__(self):
        self.progress = []
        self.cancelled = False

    def check_cancelled(self):
        if self.cancelled:
            raise WorkerCancelled()

    def report_progress(self, value):
        self.check_cancelled()
        self.progress.append(value)


class CancelAfterProgressWorker(FakeWorker):
    def report_progress(self, value):
        super().report_progress(value)
        self.cancelled = True


def make_pdf(path, pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    with path.open("wb") as file:
        writer.write(file)


def test_split_pdf_task_runs_without_gui_and_reports_progress(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "out"
    output.mkdir()
    make_pdf(source, pages=3)
    worker = FakeWorker()

    result = split_pdf_task(worker, str(source), str(output), "individual", "")

    assert len(result["outputs"]) == 3
    assert all((output / f"source_p{page}.pdf").exists() for page in (1, 2, 3))
    assert worker.progress[-1]["percent"] == 100


def test_split_pdf_task_removes_outputs_after_cancellation(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "out"
    output.mkdir()
    make_pdf(source, pages=3)
    worker = CancelAfterProgressWorker()

    with pytest.raises(WorkerCancelled):
        split_pdf_task(worker, str(source), str(output), "individual", "")

    assert list(output.glob("*.pdf")) == []


def test_extract_text_task_processes_pages_off_gui_thread(tmp_path):
    source = tmp_path / "source.pdf"
    target = tmp_path / "text.md"
    make_pdf(source, pages=2)
    worker = FakeWorker()

    result = extract_text_task(
        worker,
        str(source),
        "",
        False,
        True,
        False,
        True,
        60,
        None,
        str(target),
    )

    assert target.exists()
    assert "## Página 1" in target.read_text(encoding="utf-8")
    assert result["total"] == 2
    assert result["empty_ratio"] == 100
    assert worker.progress[-1]["percent"] == 100


def test_pdf_preview_callback_dispatches_background_task(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    start_task = Mock()
    window = SimpleNamespace(
        require_pypdf=lambda: True,
        text_src=SimpleNamespace(text=lambda: str(source)),
        _start_task=start_task,
        _text_preview_done=Mock(),
    )

    PdfTool._text_preview(window)

    args = start_task.call_args.args
    assert args[1] is preview_text_task
    assert args[3] == str(source)


def test_virustotal_task_hashes_and_queries_in_worker(tmp_path):
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"pythonkni")
    response = Mock(status_code=200)
    response.json.return_value = {
        "data": {
            "attributes": {
                "last_analysis_stats": {"malicious": 1, "undetected": 3},
                "last_analysis_results": {"Engine": {"category": "malicious", "result": "Example"}},
            }
        }
    }
    process = Mock()
    process.exe.return_value = str(executable)
    worker = FakeWorker()

    with ExitStack() as stack:
        stack.enter_context(
            patch("tools.process_manager_tool.psutil.Process", return_value=process)
        )
        request = stack.enter_context(
            patch("tools.process_manager_tool.requests.get", return_value=response)
        )
        result = analyze_process_task(worker, 1234, "secret")

    assert isinstance(result, VirusTotalResult)
    assert result.status == "found"
    assert result.positives == 1
    assert result.total == 4
    request.assert_called_once()
    assert worker.progress


def test_virustotal_gui_callback_only_starts_worker():
    class Signal:
        def connect(self, callback):
            self.callback = callback

    class FakeAsyncWorker:
        def __init__(self, task, *args, parent=None):
            self.task = task
            self.args = args
            self.parent = parent
            self.progress = Signal()
            self.result = Signal()
            self.error = Signal()
            self.cancelled = Signal()
            self.finished = Signal()
            self.started = False

        def isRunning(self):
            return False

        def start(self):
            self.started = True

        def cancel(self):
            pass

    status = Mock()
    cancel_button = Mock()

    def start_managed_worker(worker, *, cancel=None):
        worker.start()
        return worker

    managed_start = Mock(side_effect=start_managed_worker)
    window = SimpleNamespace(
        _analysis_worker=None,
        analysis_status=status,
        btn_cancel_analysis=cancel_button,
        _analysis_progress=Mock(),
        _analysis_result=Mock(),
        _analysis_error=Mock(),
        _analysis_cancelled=Mock(),
        _analysis_finished=Mock(),
        start_managed_worker=managed_start,
    )

    with ExitStack() as stack:
        stack.enter_context(patch("tools.process_manager_tool.get_vt_api_key", return_value="key"))
        worker_class = stack.enter_context(
            patch("tools.process_manager_tool.Worker", side_effect=FakeAsyncWorker)
        )
        request = stack.enter_context(patch("tools.process_manager_tool.requests.get"))
        ProcessTool.analyze_process(window, 99)

    request.assert_not_called()
    worker_class.assert_called_once()
    worker = window._analysis_worker
    assert worker.task is analyze_process_task
    assert worker.args == (99, "key")
    assert worker.started
    managed_start.assert_called_once()
    assert managed_start.call_args.args == (worker,)
    assert managed_start.call_args.kwargs["cancel"] == worker.cancel
