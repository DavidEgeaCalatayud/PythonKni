from __future__ import annotations

import logging
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PyQt5.QtWidgets import QCheckBox, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget


logger = logging.getLogger(__name__)


@dataclass
class CleanResult:
    deleted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def add(self, other: "CleanResult") -> None:
        self.deleted += other.deleted
        self.failed += other.failed
        self.errors.extend(other.errors)


@dataclass(frozen=True)
class CleanTarget:
    label: str
    path: Path


@dataclass
class CleanPreview:
    targets: list[CleanTarget] = field(default_factory=list)
    items: int = 0
    bytes: int = 0


def _resolve_existing(path: Path) -> Path | None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    return resolved if resolved.exists() and resolved.is_dir() else None


def _is_safe_clean_root(path: Path) -> bool:
    """Permite solo cachés y temporales acotados; nunca raíces generales del sistema."""
    resolved = _resolve_existing(path)
    if resolved is None:
        return False

    system = platform.system()
    home = Path.home().resolve()
    safe_roots: list[Path] = []

    if system == "Windows":
        for env_name in ("TEMP", "TMP", "LOCALAPPDATA"):
            env_path = os.environ.get(env_name)
            if env_path:
                root = _resolve_existing(Path(env_path))
                if root:
                    safe_roots.append(root)

        windows_temp = _resolve_existing(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Temp")
        if windows_temp:
            safe_roots.append(windows_temp)
    else:
        for candidate in (
            home / ".cache",
            home / "Library" / "Caches",
            Path(os.environ.get("XDG_CACHE_HOME", "")),
        ):
            root = _resolve_existing(candidate)
            if root:
                safe_roots.append(root)

    return any(resolved == root or root in resolved.parents for root in safe_roots)


def _unique_safe_targets(targets: list[CleanTarget]) -> list[CleanTarget]:
    seen: set[Path] = set()
    safe_targets: list[CleanTarget] = []

    for target in targets:
        resolved = _resolve_existing(target.path)
        if resolved and resolved not in seen and _is_safe_clean_root(resolved):
            safe_targets.append(CleanTarget(target.label, resolved))
            seen.add(resolved)

    return safe_targets


def get_temp_targets() -> list[CleanTarget]:
    if platform.system() != "Windows":
        return []

    targets = []
    for env_name in ("TEMP", "TMP"):
        env_path = os.environ.get(env_name)
        if env_path:
            targets.append(CleanTarget(f"Temporal de usuario ({env_name})", Path(env_path)))
    return _unique_safe_targets(targets)


def get_browser_cache_targets() -> list[CleanTarget]:
    system = platform.system()
    home = Path.home()

    if system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        targets = [
            CleanTarget("Chrome Cache", local / "Google" / "Chrome" / "User Data" / "Default" / "Cache"),
            CleanTarget("Edge Cache", local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache"),
        ]
        firefox_profiles = local / "Mozilla" / "Firefox" / "Profiles"
    elif system == "Darwin":
        cache_home = home / "Library" / "Caches"
        targets = [
            CleanTarget("Chrome Cache", cache_home / "Google" / "Chrome" / "Default" / "Cache"),
            CleanTarget("Edge Cache", cache_home / "Microsoft Edge" / "Default" / "Cache"),
        ]
        firefox_profiles = cache_home / "Firefox" / "Profiles"
    else:
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
        targets = [
            CleanTarget("Chrome Cache", cache_home / "google-chrome" / "Default" / "Cache"),
            CleanTarget("Edge Cache", cache_home / "microsoft-edge" / "Default" / "Cache"),
        ]
        firefox_profiles = cache_home / "mozilla" / "firefox"

    if firefox_profiles.exists():
        targets.extend(
            CleanTarget("Firefox Cache", profile / "cache2")
            for profile in firefox_profiles.iterdir()
            if (profile / "cache2").is_dir()
        )

    return _unique_safe_targets(targets)


def get_log_targets() -> list[CleanTarget]:
    if platform.system() != "Windows":
        return []
    return _unique_safe_targets(
        [CleanTarget("Windows Temp", Path(os.environ.get("SystemRoot", "C:/Windows")) / "Temp")]
    )


def build_preview(targets: list[CleanTarget]) -> CleanPreview:
    preview = CleanPreview(targets=targets)
    for target in targets:
        for root, dirs, files in os.walk(target.path):
            preview.items += len(dirs) + len(files)
            for file_name in files:
                try:
                    preview.bytes += (Path(root) / file_name).stat().st_size
                except OSError:
                    pass
    return preview


def delete_folder_contents(folder, dry_run: bool = False) -> CleanResult:
    """Borra todos los archivos y carpetas dentro de una ruta segura."""
    result = CleanResult()
    folder = Path(folder)
    if not _is_safe_clean_root(folder):
        return result

    for root, dirs, files in os.walk(folder, topdown=False):
        for file_name in files:
            path = Path(root) / file_name
            try:
                if not dry_run:
                    path.unlink()
                result.deleted += 1
            except Exception:
                result.failed += 1
                result.errors.append(str(path))
                logger.warning("No se pudo borrar %s", path, exc_info=True)

        for dir_name in dirs:
            path = Path(root) / dir_name
            try:
                if not dry_run:
                    shutil.rmtree(path)
                result.deleted += 1
            except Exception:
                result.failed += 1
                result.errors.append(str(path))
                logger.warning("No se pudo borrar %s", path, exc_info=True)

    return result


def clean_targets(targets: list[CleanTarget], dry_run: bool = False) -> CleanResult:
    result = CleanResult()
    for target in targets:
        result.add(delete_folder_contents(target.path, dry_run=dry_run))
    return result


def clean_temp(dry_run: bool = False) -> CleanResult:
    return clean_targets(get_temp_targets(), dry_run=dry_run)


def clean_browser_cache(dry_run: bool = False) -> CleanResult:
    return clean_targets(get_browser_cache_targets(), dry_run=dry_run)


def clean_logs(dry_run: bool = False) -> CleanResult:
    return clean_targets(get_log_targets(), dry_run=dry_run)


class Tool(QMainWindow):
    name = "Limpieza de Temporales"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 400, 300)

        layout = QVBoxLayout()

        self.chk_temp = QCheckBox("Archivos temporales seguros")
        self.chk_temp.setChecked(True)
        layout.addWidget(self.chk_temp)

        self.chk_cache = QCheckBox("Cache de navegadores (Chrome, Edge, Firefox)")
        layout.addWidget(self.chk_cache)

        self.chk_logs = QCheckBox("Temporales de Windows")
        layout.addWidget(self.chk_logs)

        btn_clean = QPushButton("Vista previa y limpieza")
        btn_clean.clicked.connect(self.clean_action)
        layout.addWidget(btn_clean)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def clean_action(self):
        targets = []

        if self.chk_temp.isChecked():
            targets.extend(get_temp_targets())
        if self.chk_cache.isChecked():
            targets.extend(get_browser_cache_targets())
        if self.chk_logs.isChecked():
            targets.extend(get_log_targets())

        preview = build_preview(targets)
        if not preview.targets:
            QMessageBox.information(
                self,
                "Sin rutas seguras",
                "No hay rutas de limpieza seguras para las opciones seleccionadas.",
            )
            return

        detail = "\n".join(f"- {target.label}: {target.path}" for target in preview.targets)
        size_mb = preview.bytes / (1024 * 1024)
        confirm = QMessageBox.question(
            self,
            "Confirmar limpieza",
            "Vista previa de limpieza:\n"
            f"{detail}\n\n"
            f"Elementos detectados: {preview.items}\n"
            f"Tamano aproximado: {size_mb:.2f} MB\n\n"
            "Deseas borrar el contenido de estas rutas?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            QMessageBox.information(self, "Simulacion completada", "No se ha borrado ningun archivo.")
            return

        result = clean_targets(preview.targets)

        QMessageBox.information(
            self,
            "Limpieza completada",
            f"Se han eliminado {result.deleted} archivos/carpetas temporales.\n"
            f"No se pudieron eliminar {result.failed} elementos.",
        )
