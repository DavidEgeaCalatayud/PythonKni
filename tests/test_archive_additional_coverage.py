import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from pythonkni.archive import service as archive
from pythonkni.core.tasks import WorkerCancelled
from pythonkni.infrastructure.archives import ArchiveLimits, ArchiveMember, ArchiveSecurityError


class RecordingWorker:
    def __init__(self, cancel=False):
        self.cancel = cancel
        self.progress = []
        self.checks = 0

    def check_cancelled(self):
        self.checks += 1
        if self.cancel:
            raise WorkerCancelled()

    def report_progress(self, payload):
        self.progress.append(payload)


def test_require_streaming_7z_factory_fails_closed(monkeypatch):
    monkeypatch.setattr(archive, "HAS_STREAMING_7Z_FACTORY", False)
    monkeypatch.setattr(archive.py7zr, "__version__", "0.22.0", raising=False)

    with pytest.raises(RuntimeError, match="py7zr >= 1.0.0"):
        archive._require_streaming_7z_factory()


def test_require_streaming_7z_factory_returns_when_available(monkeypatch):
    monkeypatch.setattr(archive, "HAS_STREAMING_7Z_FACTORY", True)
    archive._require_streaming_7z_factory()


def test_report_builds_plain_and_capped_percent_payloads():
    worker = RecordingWorker()

    archive._report(worker, "plain")
    archive._report(worker, "done", current=5, total=2)

    assert worker.progress == [
        {"message": "plain"},
        {"message": "done", "percent": 100},
    ]


def test_temporary_output_and_publish_file(tmp_path):
    destination = tmp_path / "nested" / "archive.zip"
    staging = archive._temporary_output(destination)
    assert staging.exists()
    assert staging.parent == destination.parent

    staging.write_bytes(b"archive")
    worker = RecordingWorker()
    result = archive._publish_file(staging, destination, worker)

    assert result == destination
    assert destination.read_bytes() == b"archive"
    assert worker.checks == 1


def test_archive_input_size_skips_missing_files(tmp_path):
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"abc")
    second.write_bytes(b"12345")

    assert archive._archive_input_size([str(first), str(tmp_path / "missing"), str(second)]) == 8


def test_create_zip_task_publishes_valid_archive(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    destination = tmp_path / "bundle.zip"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    worker = RecordingWorker()

    result = archive.create_zip_task(worker, [str(first), str(second)], destination)

    assert result == destination
    with archive.zipfile.ZipFile(destination) as zipped:
        assert sorted(zipped.namelist()) == ["first.txt", "second.txt"]
        assert zipped.read("first.txt") == b"one"
    assert worker.progress


def test_create_zip_task_rejects_non_file_and_removes_staging(tmp_path):
    destination = tmp_path / "bundle.zip"

    with pytest.raises(OSError, match="No se puede comprimir"):
        archive.create_zip_task(RecordingWorker(), [str(tmp_path / "missing.txt")], destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".bundle.zip.pythonkni-*.tmp"))


def test_create_zip_task_cancellation_does_not_publish(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "bundle.zip"
    source.write_text("content", encoding="utf-8")

    with pytest.raises(WorkerCancelled):
        archive.create_zip_task(RecordingWorker(cancel=True), [str(source)], destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".bundle.zip.pythonkni-*.tmp"))


def test_cancellable_reader_tracks_read_and_readinto(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"abcdef")
    worker = RecordingWorker()
    tracked = []

    raw = source.open("rb", buffering=0)
    with archive._CancellableReader(
        raw,
        worker,
        lambda count, label: tracked.append((count, label)),
        "copy",
    ) as reader:
        assert reader.read(2) == b"ab"
        buffer = bytearray(2)
        assert reader.readinto(buffer) == 2
        assert bytes(buffer) == b"cd"
        assert reader.read() == b"ef"

    assert tracked == [(2, "copy"), (2, "copy"), (2, "copy")]
    assert worker.checks == 3


def test_create_7z_task_uses_cancellable_reader_and_publishes(monkeypatch, tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "bundle.7z"
    source.write_text("payload", encoding="utf-8")
    seen = []

    class FakeSevenZipFile:
        def __init__(self, path, mode):
            assert mode == "w"
            self.path = Path(path)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def writef(self, reader, arcname):
            seen.append((arcname, reader.read()))

    monkeypatch.setattr(archive.py7zr, "SevenZipFile", FakeSevenZipFile)
    worker = RecordingWorker()

    result = archive.create_7z_task(worker, [str(source)], destination)

    assert result == destination
    assert destination.exists()
    assert seen == [("source.txt", b"payload")]
    assert worker.progress[-1]["percent"] == 100


def test_create_7z_task_rejects_missing_source_and_cleans_temp(monkeypatch, tmp_path):
    destination = tmp_path / "bundle.7z"

    class FakeSevenZipFile:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(archive.py7zr, "SevenZipFile", FakeSevenZipFile)

    with pytest.raises(OSError, match="No se puede comprimir"):
        archive.create_7z_task(RecordingWorker(), [str(tmp_path / "missing")], destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".bundle.7z.pythonkni-*.tmp"))


def test_extract_zip_task_handles_directories_and_files(tmp_path):
    source = tmp_path / "source.zip"
    destination = tmp_path / "out"
    with archive.zipfile.ZipFile(source, "w") as zipped:
        zipped.writestr("folder/", b"")
        zipped.writestr("folder/data.txt", b"payload")
    worker = RecordingWorker()

    result = archive.extract_zip_task(worker, source, destination)

    assert result == destination
    assert (destination / "folder" / "data.txt").read_bytes() == b"payload"
    assert worker.progress[-1]["percent"] == 100


def test_extract_zip_task_rejects_encrypted_member(monkeypatch, tmp_path):
    source = tmp_path / "source.zip"
    source.write_bytes(b"stub")
    info = archive.zipfile.ZipInfo("secret.txt")
    info.file_size = 1
    info.compress_size = 1
    info.flag_bits = 0x1

    class FakeZip:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def infolist(self):
            return [info]

    monkeypatch.setattr(archive.zipfile, "ZipFile", lambda *_args, **_kwargs: FakeZip())

    with pytest.raises(ArchiveSecurityError, match="cifrados"):
        archive.extract_zip_task(RecordingWorker(), source, tmp_path / "out")


def test_extract_zip_task_rejects_more_data_than_declared_and_cleans_staging(monkeypatch, tmp_path):
    source = tmp_path / "source.zip"
    source.write_bytes(b"stub")
    info = archive.zipfile.ZipInfo("data.txt")
    info.file_size = 1
    info.compress_size = 1

    class FakeZip:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def infolist(self):
            return [info]

        def open(self, *_args, **_kwargs):
            return io.BytesIO(b"ab")

    monkeypatch.setattr(archive.zipfile, "ZipFile", lambda *_args, **_kwargs: FakeZip())
    destination = tmp_path / "out"

    with pytest.raises(ArchiveSecurityError, match="más datos"):
        archive.extract_zip_task(RecordingWorker(), source, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".out.pythonkni-*"))


def test_seven_zip_writer_supports_io_contract_and_size_limit(tmp_path):
    calls = []
    factory = SimpleNamespace(worker=RecordingWorker(), record=lambda count: calls.append(count))
    writer = archive._SevenZipWriter(tmp_path / "data.bin", 3, factory)

    assert writer.write(b"ab") == 2
    assert writer.size() == 2
    writer.flush()
    assert writer.seek(0) == 0
    assert writer.read(1) == b"a"

    with pytest.raises(ArchiveSecurityError, match="más datos"):
        writer.write(b"cd")

    writer.close()
    writer.close()
    assert calls == [2]


def test_seven_zip_factory_validates_members_records_and_closes(tmp_path):
    member = ArchiveMember("folder/data.bin", 3, 3)
    limits = ArchiveLimits(max_total_uncompressed=10)
    worker = RecordingWorker()
    factory = archive._SevenZipFactory(
        tmp_path,
        [member],
        {"folder/data.bin": Path("folder/data.bin")},
        worker,
        limits,
    )

    with pytest.raises(ArchiveSecurityError, match="no validado"):
        factory.create("other.bin")

    writer = factory.create("folder/data.bin")
    writer.write(b"abc")
    assert factory.total_written == 3
    assert worker.progress[-1]["percent"] == 100
    factory.record(0)
    factory.close_all()
    assert writer._file.closed


def test_seven_zip_factory_enforces_real_total_limit(tmp_path):
    member = ArchiveMember("data.bin", 5, 5)
    factory = archive._SevenZipFactory(
        tmp_path,
        [member],
        {"data.bin": Path("data.bin")},
        RecordingWorker(),
        ArchiveLimits(max_total_uncompressed=1),
    )

    with pytest.raises(ArchiveSecurityError, match="tamaño total"):
        factory.record(2)


def test_extract_7z_task_requires_streaming_factory_before_opening(monkeypatch, tmp_path):
    monkeypatch.setattr(archive, "HAS_STREAMING_7Z_FACTORY", False)
    source = tmp_path / "source.7z"
    source.write_bytes(b"stub")

    with pytest.raises(RuntimeError, match="extracción 7Z segura"):
        archive.extract_7z_task(RecordingWorker(), source, tmp_path / "out")
