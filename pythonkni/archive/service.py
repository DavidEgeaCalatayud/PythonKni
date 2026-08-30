from __future__ import annotations

import io
import logging
import os
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path

import py7zr

from pythonkni.infrastructure.archives import (
    COPY_CHUNK_SIZE,
    DEFAULT_LIMITS,
    ArchiveLimits,
    ArchiveMember,
    ArchiveSecurityError,
    _open_7z_for_read,
    _publish_staging,
    _safe_relative_path,
    _seven_zip_member,
    _staging_directory,
    _verify_extracted_tree,
    _zip_member,
    validate_archive_members,
)

try:
    from py7zr import Py7zIO as _Py7zIO
    from py7zr import WriterFactory as _WriterFactory
except ImportError:
    try:
        from py7zr.io import Py7zIO as _Py7zIO
        from py7zr.io import WriterFactory as _WriterFactory
    except ImportError:
        _Py7zIO = None
        _WriterFactory = None


HAS_STREAMING_7Z_FACTORY = _Py7zIO is not None and _WriterFactory is not None
_Py7zIOBase = _Py7zIO if _Py7zIO is not None else object
_WriterFactoryBase = _WriterFactory if _WriterFactory is not None else object


def _require_streaming_7z_factory() -> None:
    if HAS_STREAMING_7Z_FACTORY:
        return
    version = getattr(py7zr, "__version__", "desconocida")
    raise RuntimeError(
        "La extracción 7Z segura requiere py7zr >= 1.0.0 y Python >= 3.9. "
        f"La instalación actual usa py7zr {version} sin Py7zIO/WriterFactory. "
        "Actualiza Python y reinstala requirements.txt para habilitar esta operación."
    )


def _report(worker, message: str, current: int | None = None, total: int | None = None) -> None:
    payload: dict[str, object] = {"message": message}
    if current is not None and total:
        payload["percent"] = min(100, int((current / total) * 100))
    worker.report_progress(payload)


def _temporary_output(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{destination.name}.pythonkni-",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(handle)
    return Path(name)


def _publish_file(staging: Path, destination: Path, worker) -> Path:
    worker.check_cancelled()
    os.replace(staging, destination)
    return destination


def _archive_input_size(files: list[str]) -> int:
    total = 0
    for file_path in files:
        try:
            total += Path(file_path).stat().st_size
        except OSError:
            continue
    return total


def create_zip_task(worker, files: list[str], destination: str | Path) -> Path:
    """Create a ZIP in staging and atomically publish it after successful completion."""
    destination_path = Path(destination)
    staging = _temporary_output(destination_path)
    total = _archive_input_size(files)
    processed = 0
    try:
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, file_path in enumerate(files, start=1):
                worker.check_cancelled()
                source = Path(file_path)
                if not source.is_file():
                    raise OSError(f"No se puede comprimir el archivo: {source}")
                info = zipfile.ZipInfo.from_file(source, arcname=source.name)
                info.compress_type = zipfile.ZIP_DEFLATED
                with source.open("rb") as input_file, archive.open(info, "w") as output_file:
                    while True:
                        worker.check_cancelled()
                        chunk = input_file.read(COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        output_file.write(chunk)
                        processed += len(chunk)
                        _report(worker, f"Comprimiendo ZIP {index}/{len(files)}", processed, total)
        return _publish_file(staging, destination_path, worker)
    except Exception:
        staging.unlink(missing_ok=True)
        raise


class _CancellableReader(io.BufferedReader):
    def __init__(self, raw, worker, tracker, label: str):
        super().__init__(raw)
        self._worker = worker
        self._tracker = tracker
        self._label = label

    def read(self, size: int = -1) -> bytes:
        self._worker.check_cancelled()
        data = super().read(size)
        if data:
            self._tracker(len(data), self._label)
        return data

    def readinto(self, buffer) -> int:
        self._worker.check_cancelled()
        count = super().readinto(buffer)
        if count:
            self._tracker(count, self._label)
        return count


def create_7z_task(worker, files: list[str], destination: str | Path) -> Path:
    """Create a 7Z with cancellable source readers and atomic publication."""
    destination_path = Path(destination)
    staging = _temporary_output(destination_path)
    total = _archive_input_size(files)
    processed = 0
    lock = threading.Lock()

    def track(count: int, label: str) -> None:
        nonlocal processed
        with lock:
            processed += count
            current = processed
        _report(worker, label, current, total)

    try:
        with py7zr.SevenZipFile(staging, "w") as archive:
            for index, file_path in enumerate(files, start=1):
                worker.check_cancelled()
                source = Path(file_path)
                if not source.is_file():
                    raise OSError(f"No se puede comprimir el archivo: {source}")
                raw = source.open("rb", buffering=0)
                with _CancellableReader(
                    raw,
                    worker,
                    track,
                    f"Comprimiendo 7Z {index}/{len(files)}",
                ) as reader:
                    archive.writef(reader, arcname=source.name)
        return _publish_file(staging, destination_path, worker)
    except Exception:
        staging.unlink(missing_ok=True)
        raise


def extract_zip_task(
    worker,
    file_path: str | Path,
    destination: str | Path,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> Path:
    """Safely extract ZIP data with chunk-level cancellation and progress."""
    source = Path(file_path)
    destination_path = Path(destination)

    with zipfile.ZipFile(source, "r") as archive:
        infos = archive.infolist()
        members = [_zip_member(info) for info in infos]
        validated = validate_archive_members(
            members,
            archive_size=source.stat().st_size,
            limits=limits,
        )
        for info in infos:
            if info.flag_bits & 0x1:
                raise ArchiveSecurityError(
                    f"Los ZIP cifrados no están soportados por esta herramienta: {info.filename}"
                )

        total = sum(member.uncompressed_size for member in members if not member.is_directory)
        total_written = 0
        staging = _staging_directory(destination_path)
        try:
            for index, (info, member) in enumerate(zip(infos, members), start=1):
                worker.check_cancelled()
                relative = validated[_safe_relative_path(member.name, limits).as_posix().casefold()]
                output = staging / relative
                if member.is_directory:
                    output.mkdir(parents=True, exist_ok=True)
                    continue

                output.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info, "r") as input_file, output.open("xb") as output_file:
                    while True:
                        worker.check_cancelled()
                        chunk = input_file.read(COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        written += len(chunk)
                        total_written += len(chunk)
                        if written > limits.max_single_file or written > member.uncompressed_size:
                            raise ArchiveSecurityError(
                                f"{member.name} produce más datos de los declarados o permitidos."
                            )
                        if total_written > limits.max_total_uncompressed:
                            raise ArchiveSecurityError(
                                "La extracción supera el tamaño total descomprimido permitido."
                            )
                        output_file.write(chunk)
                        _report(
                            worker,
                            f"Extrayendo ZIP {index}/{len(members)}",
                            total_written,
                            total,
                        )
                if written != member.uncompressed_size:
                    raise ArchiveSecurityError(
                        f"El tamaño extraído de {member.name} no coincide con sus metadatos."
                    )

            worker.check_cancelled()
            _verify_extracted_tree(staging, limits)
            worker.check_cancelled()
            _publish_staging(staging, destination_path)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    return destination_path


class _SevenZipWriter(_Py7zIOBase):
    def __init__(self, output: Path, expected_size: int, factory: "_SevenZipFactory") -> None:
        self._output = output
        self._expected_size = expected_size
        self._factory = factory
        self._written = 0
        output.parent.mkdir(parents=True, exist_ok=True)
        self._file = output.open("xb+")

    def write(self, data: bytes | bytearray) -> int:
        self._factory.worker.check_cancelled()
        size = len(data)
        if self._written + size > self._expected_size:
            raise ArchiveSecurityError(f"{self._output.name} produce más datos de los declarados.")
        written = self._file.write(data)
        self._written += written
        self._factory.record(written)
        return written

    def read(self, size: int | None = None) -> bytes:
        return self._file.read(-1 if size is None else size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._file.seek(offset, whence)

    def flush(self) -> None:
        self._file.flush()

    def size(self) -> int:
        return self._written

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


class _SevenZipFactory(_WriterFactoryBase):
    def __init__(
        self,
        staging: Path,
        members: list[ArchiveMember],
        validated: dict[str, Path],
        worker,
        limits: ArchiveLimits,
    ) -> None:
        self.staging = staging
        self.worker = worker
        self.limits = limits
        self.validated = validated
        self.expected = {
            _safe_relative_path(member.name, limits).as_posix().casefold(): member.uncompressed_size
            for member in members
            if not member.is_directory
        }
        self.total_expected = sum(self.expected.values())
        self.total_written = 0
        self._last_percent = -1
        self._lock = threading.Lock()
        self._writers: list[_SevenZipWriter] = []

    def create(self, filename: str):
        self.worker.check_cancelled()
        key = _safe_relative_path(filename, self.limits).as_posix().casefold()
        relative = self.validated.get(key)
        if relative is None or key not in self.expected:
            raise ArchiveSecurityError(f"Miembro 7Z no validado: {filename}")
        writer = _SevenZipWriter(self.staging / relative, self.expected[key], self)
        self._writers.append(writer)
        return writer

    def record(self, count: int) -> None:
        with self._lock:
            self.total_written += count
            if self.total_written > self.limits.max_total_uncompressed:
                raise ArchiveSecurityError("La extracción real supera el tamaño total permitido.")
            percent = (
                int((self.total_written / self.total_expected) * 100)
                if self.total_expected
                else 100
            )
            if percent == self._last_percent:
                return
            self._last_percent = percent
            current = self.total_written
        _report(self.worker, "Extrayendo 7Z...", current, self.total_expected)

    def close_all(self) -> None:
        for writer in self._writers:
            writer.close()


def extract_7z_task(
    worker,
    file_path: str | Path,
    destination: str | Path,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> Path:
    """Safely extract 7Z data through a cancellable streaming writer factory."""
    _require_streaming_7z_factory()
    source = Path(file_path)
    destination_path = Path(destination)

    with _open_7z_for_read(source, limits) as archive:
        members = [_seven_zip_member(info) for info in archive.list()]
    validated = validate_archive_members(
        members,
        archive_size=source.stat().st_size,
        limits=limits,
    )

    worker.check_cancelled()
    staging = _staging_directory(destination_path)
    factory = _SevenZipFactory(staging, members, validated, worker, limits)
    try:
        with _open_7z_for_read(source, limits) as archive:
            archive.extractall(factory=factory)
        factory.close_all()
        worker.check_cancelled()
        _verify_extracted_tree(staging, limits)
        worker.check_cancelled()
        _publish_staging(staging, destination_path)
    except Exception:
        factory.close_all()
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return destination_path


logger = logging.getLogger(__name__)
