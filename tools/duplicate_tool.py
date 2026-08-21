from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool


logger = logging.getLogger(__name__)
DUPLICATES_DIR_NAME = "DuplicadosEncontrados"
RESTORE_MANIFEST_PREFIX = "restauracion_duplicados"
HASH_CHUNK_SIZE = 1024 * 1024
QUICK_SAMPLE_SIZE = 64 * 1024


def hash_file(file_path: str | Path) -> str | None:
    """Return the SHA-256 digest for a file, or None when it cannot be read."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as file:
            for chunk in iter(lambda: file.read(HASH_CHUNK_SIZE), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def quick_hash_file(file_path: str | Path, sample_size: int = QUICK_SAMPLE_SIZE) -> str | None:
    """Hash only file edges with BLAKE2b to cheaply narrow same-size candidates."""
    path = Path(file_path)
    try:
        size = path.stat().st_size
        hasher = hashlib.blake2b(digest_size=16)
        hasher.update(size.to_bytes(8, "little", signed=False))
        with path.open("rb") as file:
            hasher.update(file.read(sample_size))
            if size > sample_size:
                file.seek(max(0, size - sample_size))
                hasher.update(file.read(sample_size))
    except OSError:
        return None
    return hasher.hexdigest()


def files_equal(first_path: str | Path, second_path: str | Path) -> bool:
    """Compare two files byte for byte after checking their current sizes."""
    first = Path(first_path)
    second = Path(second_path)
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        with first.open("rb") as first_file, second.open("rb") as second_file:
            while True:
                first_chunk = first_file.read(HASH_CHUNK_SIZE)
                second_chunk = second_file.read(HASH_CHUNK_SIZE)
                if first_chunk != second_chunk:
                    return False
                if not first_chunk:
                    return True
    except OSError:
        return False


def _iter_scan_files(folder_path: str | Path):
    base = Path(folder_path)
    excluded_name = DUPLICATES_DIR_NAME.casefold()
    for root, directories, filenames in os.walk(base):
        directories[:] = [name for name in directories if name.casefold() != excluded_name]
        for filename in filenames:
            path = Path(root) / filename
            if path.is_symlink():
                continue
            yield path


def _group_readable_files_by_size(folder_path: str | Path) -> dict[int, list[Path]]:
    groups: dict[int, list[Path]] = defaultdict(list)
    for path in _iter_scan_files(folder_path):
        try:
            groups[path.stat().st_size].append(path)
        except OSError:
            logger.debug("No se pudo leer el tamaño de %s", path, exc_info=True)
    return groups


def _verified_byte_groups(paths: list[Path]) -> list[list[Path]]:
    """Split a secure-hash group into byte-identical groups."""
    groups: list[list[Path]] = []
    for path in sorted(paths, key=lambda item: str(item).casefold()):
        for group in groups:
            if files_equal(group[0], path):
                group.append(path)
                break
        else:
            groups.append([path])
    return [group for group in groups if len(group) > 1]


def find_duplicates(folder_path: str | Path) -> dict[str, list[str]]:
    """Find duplicates with size, quick hash, SHA-256 and byte comparison stages."""
    size_groups = _group_readable_files_by_size(folder_path)
    quick_groups: dict[tuple[int, str], list[Path]] = defaultdict(list)

    for size, paths in size_groups.items():
        if len(paths) < 2:
            continue
        for path in paths:
            quick_hash = quick_hash_file(path)
            if quick_hash is not None:
                quick_groups[(size, quick_hash)].append(path)

    secure_groups: dict[str, list[Path]] = defaultdict(list)
    for paths in quick_groups.values():
        if len(paths) < 2:
            continue
        for path in paths:
            secure_hash = hash_file(path)
            if secure_hash is not None:
                secure_groups[secure_hash].append(path)

    duplicates: dict[str, list[str]] = {}
    for secure_hash, paths in secure_groups.items():
        if len(paths) < 2:
            continue
        verified_groups = _verified_byte_groups(paths)
        for index, group in enumerate(verified_groups, start=1):
            key = secure_hash if index == 1 else f"{secure_hash}:{index}"
            duplicates[key] = [str(path) for path in group]

    return duplicates


def _unique_destination(target_folder: Path, filename: str) -> Path:
    destination = target_folder / filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while destination.exists():
        destination = target_folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return destination


def _new_manifest_path(target_folder: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = target_folder / f"{RESTORE_MANIFEST_PREFIX}_{timestamp}.json"
    counter = 1
    while candidate.exists():
        candidate = target_folder / f"{RESTORE_MANIFEST_PREFIX}_{timestamp}_{counter}.json"
        counter += 1
    return candidate


def _write_manifest_atomic(manifest_path: Path, manifest: dict) -> None:
    temporary = manifest_path.with_name(f"{manifest_path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, manifest_path)


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def move_duplicates(duplicates, base_folder):
    """Move revalidated copies and create an atomic restoration manifest."""
    base = Path(base_folder)
    target_folder = base / DUPLICATES_DIR_NAME
    target_folder.mkdir(parents=True, exist_ok=True)
    manifest_path = _new_manifest_path(target_folder)
    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_folder": str(base.resolve(strict=False)),
        "duplicates_folder": str(target_folder.resolve(strict=False)),
        "status": "in_progress",
        "restore_instructions": "Move each existing destination back to its source path.",
        "moves": [],
    }
    _write_manifest_atomic(manifest_path, manifest)

    moved_count = 0
    for paths in duplicates.values():
        if len(paths) < 2:
            continue

        original = Path(paths[0])
        if not original.exists() or _is_inside(original, target_folder):
            continue

        for file_path in paths[1:]:
            source = Path(file_path)
            if not source.exists() or source.is_symlink() or _is_inside(source, target_folder):
                continue

            source_hash = hash_file(source)
            original_hash = hash_file(original)
            if source_hash is None or original_hash is None or source_hash != original_hash:
                logger.warning("Se omite %s porque ya no coincide con %s", source, original)
                continue

            if not files_equal(original, source):
                logger.warning("Se omite %s porque falla la comparación final con %s", source, original)
                continue

            destination = _unique_destination(target_folder, source.name)
            try:
                size = source.stat().st_size
            except OSError:
                continue

            entry = {
                "source": str(source.resolve(strict=False)),
                "destination": str(destination.resolve(strict=False)),
                "retained_original": str(original.resolve(strict=False)),
                "sha256": source_hash,
                "size": size,
                "status": "planned",
            }
            manifest["moves"].append(entry)
            _write_manifest_atomic(manifest_path, manifest)

            try:
                shutil.move(str(source), str(destination))
            except Exception as error:
                entry["status"] = "failed"
                entry["error"] = str(error)
                _write_manifest_atomic(manifest_path, manifest)
                logger.warning("No se pudo mover %s", source, exc_info=True)
                continue

            entry["status"] = "moved"
            entry["moved_at"] = datetime.now(timezone.utc).isoformat()
            moved_count += 1
            _write_manifest_atomic(manifest_path, manifest)

    manifest["status"] = "complete"
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["moved_count"] = moved_count
    _write_manifest_atomic(manifest_path, manifest)
    return moved_count


class DuplicateFinderThread(QThread):
    scan_finished = pyqtSignal(dict)

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = folder_path

    def run(self):
        duplicates = find_duplicates(self.folder_path)
        self.scan_finished.emit(duplicates)


class Tool(BaseTool):
    name = "Buscador de Archivos Duplicados"
    description = "Localiza y gestiona archivos duplicados."
    category = "Archivos"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 600, 400)

        self.folder_path = None
        self.duplicates = {}
        self.thread: DuplicateFinderThread | None = None

        layout = QVBoxLayout()

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        layout.addWidget(self.result_box)

        btn_select_folder = QPushButton("Seleccionar Carpeta")
        btn_select_folder.clicked.connect(self.select_folder)
        layout.addWidget(btn_select_folder)

        self.btn_move = QPushButton("Mover duplicados a subcarpeta")
        self.btn_move.setEnabled(False)
        self.btn_move.clicked.connect(self.move_duplicates_action)
        layout.addWidget(self.btn_move)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta")
        if not folder_path:
            return

        self.folder_path = folder_path
        self.result_box.clear()
        self.result_box.setPlainText("Buscando duplicados, por favor espere...")

        self.thread = DuplicateFinderThread(folder_path)
        self.thread.scan_finished.connect(self.on_duplicates_found)
        self.thread.start()

    def on_duplicates_found(self, duplicates):
        self.duplicates = duplicates

        if not self.duplicates:
            QMessageBox.information(self, "Resultado", "No se encontraron archivos duplicados.")
            self.btn_move.setEnabled(False)
            self.result_box.clear()
            return

        result_text = "Archivos duplicados encontrados:\n\n"
        for secure_hash, paths in self.duplicates.items():
            result_text += f"SHA-256 {secure_hash}:\n"
            for path in paths:
                result_text += f"   - {path}\n"
            result_text += "\n"

        self.result_box.setPlainText(result_text)
        self.btn_move.setEnabled(True)

    def move_duplicates_action(self):
        if not self.duplicates or not self.folder_path:
            return
        moved_count = move_duplicates(self.duplicates, self.folder_path)
        QMessageBox.information(
            self,
            "Duplicados movidos",
            f"Se han movido {moved_count} archivos duplicados a la carpeta "
            f"'{DUPLICATES_DIR_NAME}'. Se ha creado un manifiesto JSON de restauración.",
        )
        self.btn_move.setEnabled(False)
