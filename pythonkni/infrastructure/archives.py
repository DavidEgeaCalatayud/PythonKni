from __future__ import annotations

import inspect
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import py7zr


class ArchiveSecurityError(ValueError):
    """Raised when an archive violates extraction safety policy."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int = 10_000
    max_total_uncompressed: int = 2 * 1024 * 1024 * 1024
    max_single_file: int = 512 * 1024 * 1024
    max_compression_ratio: float = 250.0
    max_path_depth: int = 32
    max_path_length: int = 512


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    uncompressed_size: int
    compressed_size: int | None
    is_directory: bool = False
    is_symlink: bool = False
    is_regular: bool = True


DEFAULT_LIMITS = ArchiveLimits()
COPY_CHUNK_SIZE = 1024 * 1024
WINDOWS_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _safe_relative_path(member_name: str, limits: ArchiveLimits = DEFAULT_LIMITS) -> Path:
    if not member_name or "\x00" in member_name:
        raise ArchiveSecurityError("El archivo comprimido contiene una ruta vacía o inválida.")

    windows_path = PureWindowsPath(member_name)
    if windows_path.is_absolute() or windows_path.drive or member_name.startswith(("/", "\\")):
        raise ArchiveSecurityError(f"Ruta absoluta no permitida: {member_name}")

    normalized = member_name.replace("\\", "/")
    normalized = normalized[:-1] if normalized.endswith("/") else normalized
    parts = normalized.split("/")
    if not normalized or any(part in {"", ".", ".."} for part in parts):
        raise ArchiveSecurityError(f"Ruta insegura en el archivo comprimido: {member_name}")
    if len(parts) > limits.max_path_depth or len(normalized) > limits.max_path_length:
        raise ArchiveSecurityError(f"Ruta excesivamente profunda o larga: {member_name}")

    for part in parts:
        if ":" in part or part.endswith((" ", ".")):
            raise ArchiveSecurityError(f"Nombre de archivo ambiguo en Windows: {member_name}")
        stem = part.split(".", 1)[0].upper()
        if stem in WINDOWS_DEVICE_NAMES:
            raise ArchiveSecurityError(f"Nombre reservado de Windows no permitido: {member_name}")

    return Path(*parts)


def validate_archive_members(
    members: list[ArchiveMember],
    *,
    archive_size: int | None = None,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> dict[str, Path]:
    if len(members) > limits.max_files:
        raise ArchiveSecurityError(
            f"El archivo contiene {len(members)} entradas; el máximo permitido es {limits.max_files}."
        )

    total_uncompressed = 0
    normalized_paths: dict[str, Path] = {}
    file_count = 0

    for member in members:
        relative_path = _safe_relative_path(member.name, limits)
        canonical = relative_path.as_posix().casefold()
        if canonical in normalized_paths:
            raise ArchiveSecurityError(f"Ruta duplicada o ambigua: {member.name}")
        normalized_paths[canonical] = relative_path

        if member.is_symlink:
            raise ArchiveSecurityError(f"Los enlaces simbólicos no se extraen: {member.name}")
        if not member.is_directory and not member.is_regular:
            raise ArchiveSecurityError(f"Tipo de archivo especial no permitido: {member.name}")
        if member.is_directory:
            continue

        file_count += 1
        if file_count > limits.max_files:
            raise ArchiveSecurityError(
                f"El archivo supera el máximo de {limits.max_files} ficheros."
            )
        if member.uncompressed_size < 0:
            raise ArchiveSecurityError(f"Tamaño inválido declarado para {member.name}.")
        if member.uncompressed_size > limits.max_single_file:
            raise ArchiveSecurityError(
                f"{member.name} supera el tamaño máximo individual permitido."
            )

        total_uncompressed += member.uncompressed_size
        if total_uncompressed > limits.max_total_uncompressed:
            raise ArchiveSecurityError("El tamaño total descomprimido supera el límite permitido.")

        compressed = member.compressed_size
        if member.uncompressed_size and compressed == 0:
            raise ArchiveSecurityError(f"Ratio de compresión sospechoso para {member.name}.")
        if compressed is not None and compressed > 0:
            ratio = member.uncompressed_size / compressed
            if ratio > limits.max_compression_ratio:
                raise ArchiveSecurityError(
                    f"Ratio de compresión sospechoso ({ratio:.1f}:1) para {member.name}."
                )

    if archive_size is not None and archive_size > 0 and total_uncompressed:
        total_ratio = total_uncompressed / archive_size
        if total_ratio > limits.max_compression_ratio:
            raise ArchiveSecurityError(
                f"Ratio de compresión total sospechoso ({total_ratio:.1f}:1)."
            )

    return normalized_paths


def _zip_member(info: zipfile.ZipInfo) -> ArchiveMember:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    is_symlink = file_type == stat.S_IFLNK
    is_special = file_type not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK}
    return ArchiveMember(
        name=info.filename,
        uncompressed_size=info.file_size,
        compressed_size=info.compress_size,
        is_directory=info.is_dir(),
        is_symlink=is_symlink,
        is_regular=not is_special and not is_symlink,
    )


def _seven_zip_member(info) -> ArchiveMember:
    is_directory = bool(getattr(info, "is_directory", False))
    is_symlink = bool(getattr(info, "is_symlink", False))
    is_file = bool(getattr(info, "is_file", not is_directory and not is_symlink))
    return ArchiveMember(
        name=str(info.filename),
        uncompressed_size=int(getattr(info, "uncompressed", 0) or 0),
        compressed_size=getattr(info, "compressed", None),
        is_directory=is_directory,
        is_symlink=is_symlink,
        is_regular=is_file,
    )


def _staging_directory(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ArchiveSecurityError(
            f"La carpeta de destino ya existe: {destination}. Elimínala o renómbrala antes de extraer."
        )
    return Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.pythonkni-",
            suffix=".tmp",
            dir=destination.parent,
        )
    )


def _publish_staging(staging: Path, destination: Path) -> None:
    if destination.exists():
        raise ArchiveSecurityError(
            f"La carpeta de destino apareció durante la extracción: {destination}"
        )
    os.replace(staging, destination)


def _verify_extracted_tree(staging: Path, limits: ArchiveLimits) -> None:
    total_size = 0
    file_count = 0
    root = staging.resolve(strict=True)

    for path in staging.rglob("*"):
        try:
            metadata = path.lstat()
        except OSError as error:
            raise ArchiveSecurityError(f"No se pudo verificar {path}: {error}") from error

        resolved_parent = path.parent.resolve(strict=True)
        try:
            resolved_parent.relative_to(root)
        except ValueError as error:
            raise ArchiveSecurityError(f"Ruta extraída fuera del destino: {path}") from error

        if stat.S_ISLNK(metadata.st_mode):
            raise ArchiveSecurityError(f"Se detectó un enlace durante la extracción: {path.name}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ArchiveSecurityError(
                f"Se detectó un archivo especial durante la extracción: {path.name}"
            )

        file_count += 1
        total_size += metadata.st_size
        if file_count > limits.max_files:
            raise ArchiveSecurityError("La extracción real supera el límite de archivos.")
        if metadata.st_size > limits.max_single_file:
            raise ArchiveSecurityError(f"{path.name} supera el tamaño individual permitido.")
        if total_size > limits.max_total_uncompressed:
            raise ArchiveSecurityError("La extracción real supera el tamaño total permitido.")


def safe_extract_zip(
    file_path: str | Path,
    destination: str | Path,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> Path:
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

        staging = _staging_directory(destination_path)
        total_written = 0
        try:
            for info, member in zip(infos, members):
                relative = validated[_safe_relative_path(member.name, limits).as_posix().casefold()]
                output = staging / relative
                if member.is_directory:
                    output.mkdir(parents=True, exist_ok=True)
                    continue

                output.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info, "r") as source_file, output.open("xb") as target_file:
                    while True:
                        chunk = source_file.read(COPY_CHUNK_SIZE)
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
                        target_file.write(chunk)
                if written != member.uncompressed_size:
                    raise ArchiveSecurityError(
                        f"El tamaño extraído de {member.name} no coincide con sus metadatos."
                    )

            _verify_extracted_tree(staging, limits)
            _publish_staging(staging, destination_path)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    return destination_path


def _open_7z_for_read(file_path: Path, limits: ArchiveLimits):
    parameters = inspect.signature(py7zr.SevenZipFile).parameters
    kwargs = {}
    if "max_extract_size" in parameters:
        kwargs["max_extract_size"] = limits.max_total_uncompressed
    return py7zr.SevenZipFile(file_path, mode="r", **kwargs)


def safe_extract_7z(
    file_path: str | Path,
    destination: str | Path,
    *,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> Path:
    source = Path(file_path)
    destination_path = Path(destination)

    with _open_7z_for_read(source, limits) as archive:
        members = [_seven_zip_member(info) for info in archive.list()]
    validate_archive_members(
        members,
        archive_size=source.stat().st_size,
        limits=limits,
    )

    staging = _staging_directory(destination_path)
    try:
        with _open_7z_for_read(source, limits) as archive:
            archive.extractall(path=staging)
        _verify_extracted_tree(staging, limits)
        _publish_staging(staging, destination_path)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return destination_path


def _default_extract_path(file_path: str | Path) -> Path:
    path = Path(file_path)
    return path.with_name(f"{path.stem}_extracted")
