import threading
import zipfile
from pathlib import Path

import py7zr
import pytest

from pythonkni.core.tasks import WorkerCancelled
from tools.archive_tasks import create_zip_task, extract_7z_task, extract_zip_task


class FakeWorker:
    def __init__(self, cancel_after_progress=False):
        self.cancel_event = threading.Event()
        self.progress = []
        self.cancel_after_progress = cancel_after_progress

    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise WorkerCancelled()

    def report_progress(self, payload):
        self.progress.append(payload)
        if self.cancel_after_progress:
            self.cancel_event.set()


def test_zip_creation_cancellation_preserves_existing_destination(tmp_path):
    source = tmp_path / "large.bin"
    source.write_bytes(b"A" * (2 * 1024 * 1024))
    destination = tmp_path / "output.zip"
    destination.write_bytes(b"existing archive")
    worker = FakeWorker(cancel_after_progress=True)

    with pytest.raises(WorkerCancelled):
        create_zip_task(worker, [str(source)], destination)

    assert destination.read_bytes() == b"existing archive"
    assert not list(tmp_path.glob(".output.zip.pythonkni-*.tmp"))


def test_zip_extraction_cancellation_removes_staging(tmp_path):
    archive_path = tmp_path / "large.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("large.bin", b"B" * (2 * 1024 * 1024))
    destination = tmp_path / "out"
    worker = FakeWorker(cancel_after_progress=True)

    with pytest.raises(WorkerCancelled):
        extract_zip_task(worker, archive_path, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".out.pythonkni-*.tmp"))


def test_7z_streaming_extraction_reports_progress(tmp_path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload" * 100_000)
    archive_path = tmp_path / "payload.7z"
    destination = tmp_path / "out"
    with py7zr.SevenZipFile(archive_path, "w") as archive:
        archive.write(source, arcname="payload.bin")
    worker = FakeWorker()

    result = extract_7z_task(worker, archive_path, destination)

    assert result == destination
    assert (destination / "payload.bin").read_bytes() == source.read_bytes()
    assert worker.progress
    assert any("percent" in item for item in worker.progress)


def test_7z_streaming_extraction_cancellation_never_publishes(tmp_path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload" * 100_000)
    archive_path = tmp_path / "payload.7z"
    destination = tmp_path / "out"
    with py7zr.SevenZipFile(archive_path, "w") as archive:
        archive.write(source, arcname="payload.bin")
    worker = FakeWorker(cancel_after_progress=True)

    with pytest.raises(WorkerCancelled):
        extract_7z_task(worker, archive_path, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".out.pythonkni-*.tmp"))
