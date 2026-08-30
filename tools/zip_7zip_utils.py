from __future__ import annotations

import logging
import os
import sys
import types
import zipfile

import py7zr
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from pythonkni.infrastructure import archives as _archives
from pythonkni.infrastructure.archives import (
    COPY_CHUNK_SIZE,
    DEFAULT_LIMITS,
    ArchiveLimits,
    ArchiveMember,
    ArchiveSecurityError,
    _default_extract_path,
    _open_7z_for_read,
    _publish_staging,
    _safe_relative_path,
    _seven_zip_member,
    _staging_directory,
    _verify_extracted_tree,
    _zip_member,
    safe_extract_7z,
    safe_extract_zip,
    validate_archive_members,
)

logger = logging.getLogger(__name__)

__all__ = [
    "COPY_CHUNK_SIZE",
    "DEFAULT_LIMITS",
    "ArchiveLimits",
    "ArchiveMember",
    "ArchiveSecurityError",
    "_default_extract_path",
    "_open_7z_for_read",
    "_publish_staging",
    "_safe_relative_path",
    "_seven_zip_member",
    "_staging_directory",
    "_verify_extracted_tree",
    "_zip_member",
    "create_7z",
    "create_zip",
    "extract_7z",
    "extract_zip",
    "safe_extract_7z",
    "safe_extract_zip",
    "validate_archive_members",
]


def _show_extraction_error(kind: str, error: Exception) -> None:
    logger.warning("No se pudo extraer %s", kind, exc_info=True)
    QMessageBox.critical(None, "Extracción bloqueada", f"No se pudo extraer {kind}:\n{error}")


# Legacy dialog helpers are intentionally kept in tools/. The extraction policy and
# filesystem implementation live in pythonkni.infrastructure.archives.
def extract_zip():
    file_path, _ = QFileDialog.getOpenFileName(
        None, "Seleccionar archivo ZIP", "", "Zip Files (*.zip)"
    )
    if not file_path:
        return

    extract_path = _default_extract_path(file_path)
    try:
        safe_extract_zip(file_path, extract_path)
    except (ArchiveSecurityError, OSError, zipfile.BadZipFile, RuntimeError) as error:
        _show_extraction_error("ZIP", error)
        return

    QMessageBox.information(None, "Éxito", f"Archivos extraídos en:\n{extract_path}")


def create_zip():
    files, _ = QFileDialog.getOpenFileNames(None, "Seleccionar archivos para comprimir")
    if not files:
        return

    save_path, _ = QFileDialog.getSaveFileName(None, "Guardar ZIP", "", "Zip Files (*.zip)")
    if not save_path:
        return

    with zipfile.ZipFile(save_path, "w") as archive:
        for file_path in files:
            archive.write(file_path, os.path.basename(file_path))

    QMessageBox.information(None, "Éxito", f"ZIP creado en:\n{save_path}")


def extract_7z():
    file_path, _ = QFileDialog.getOpenFileName(
        None, "Seleccionar archivo 7z", "", "7z Files (*.7z)"
    )
    if not file_path:
        return

    extract_path = _default_extract_path(file_path)
    try:
        safe_extract_7z(file_path, extract_path)
    except (ArchiveSecurityError, OSError, RuntimeError) as error:
        _show_extraction_error("7Z", error)
        return
    except Exception as error:
        # py7zr exposes different exception classes across supported versions.
        _show_extraction_error("7Z", error)
        return

    QMessageBox.information(None, "Éxito", f"Archivos extraídos en:\n{extract_path}")


def create_7z():
    files, _ = QFileDialog.getOpenFileNames(None, "Seleccionar archivos para comprimir")
    if not files:
        return

    save_path, _ = QFileDialog.getSaveFileName(None, "Guardar 7z", "", "7z Files (*.7z)")
    if not save_path:
        return

    with py7zr.SevenZipFile(save_path, "w") as archive:
        for file_path in files:
            archive.write(file_path, arcname=os.path.basename(file_path))

    QMessageBox.information(None, "Éxito", f"7z creado en:\n{save_path}")


class _CompatibilityModule(types.ModuleType):
    """Forward legacy monkeypatches of archive internals to the infrastructure module."""

    def __setattr__(self, name, value):
        if hasattr(_archives, name):
            setattr(_archives, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_archives, name):
            delattr(_archives, name)
        super().__delattr__(name)


sys.modules[__name__].__class__ = _CompatibilityModule
