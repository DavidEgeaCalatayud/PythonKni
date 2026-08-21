from __future__ import annotations

import logging
import os
import platform
import stat
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


def _env_path(name: str) -> Path | None:
    """Devuelve una ruta absoluta de entorno o None si falta, esta vacia o es relativa."""
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return None

    path = Path(raw_value).expanduser()
    return path if path.is_absolute() else None


def _resolve_existing(path: Path) -> Path | None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    return resolved if resolved.exists() and resolved.is_dir() else None


def _resolve_descendant(path: Path, boundary: Path) -> Path | None:
    """Resuelve una carpeta existente y exige que permanezca dentro de su limite esperado."""
    resolved = _resolve_existing(path)
    if resolved is None:
        return None

    try:
        resolved_boundary = boundary.expanduser().resolve()
    except OSError:
        return None

    if resolved == resolved_boundary or resolved_boundary not in resolved.parents:
        return None
    return resolved


def _broad_roots() -> set[Path]:
    """Raices que nunca deben convertirse directamente en un destino destructivo."""
    candidates = [Path.home()]

    for env_name in ("USERPROFILE", "LOCALAPPDATA", "APPDATA", "SystemRoot"):
        env_path = _env_path(env_name)
        if env_path is not None:
            candidates.append(env_path)

    if platform.system() == "Windows":
        home = Path.home()
        candidates.extend((home / "AppData" / "Local", home / "AppData" / "Roaming"))

    roots: set[Path] = set()
    for candidate in candidates:
        resolved = _resolve_existing(candidate)
        if resolved is not None:
            roots.add(resolved)
    return roots


def _make_exact_target(
    label: str,
    path: Path,
    *,
    within: Path | None = None,
    reject_broad_root: bool = False,
) -> CleanTarget | None:
    if within is None:
        resolved = _resolve_existing(path)
    else:
        resolved = _resolve_descendant(path, within)

    if resolved is None:
        return None

    if resolved == resolved.parent:
        return None

    if reject_broad_root and resolved in _broad_roots():
        return None

    return CleanTarget(label, resolved)


def _unique_targets(targets: list[CleanTarget | None]) -> list[CleanTarget]:
    seen: set[Path] = set()
    unique: list[CleanTarget] = []

    for target in targets:
        if target is None or target.path in seen:
            continue
        unique.append(target)
        seen.add(target.path)

    return unique


def get_temp_targets() -> list[CleanTarget]:
    if platform.system() != "Windows":
        return []

    targets: list[CleanTarget | None] = []
    for env_name in ("TEMP", "TMP"):
        env_path = _env_path(env_name)
        if env_path is None:
            continue
        targets.append(
            _make_exact_target(
                f"Temporal de usuario ({env_name})",
                env_path,
                reject_broad_root=True,
            )
        )
    return _unique_targets(targets)


def _cache_home_for_current_platform() -> Path:
    system = platform.system()
    home = Path.home()

    if system == "Windows":
        return _env_path("LOCALAPPDATA") or (home / "AppData" / "Local")
    if system == "Darwin":
        return home / "Library" / "Caches"

    # XDG_CACHE_HOME vacio o relativo no debe convertirse nunca en Path("") / cwd.
    return _env_path("XDG_CACHE_HOME") or (home / ".cache")


def get_browser_cache_targets() -> list[CleanTarget]:
    system = platform.system()
    cache_home = _cache_home_for_current_platform()

    if system == "Windows":
        candidates = [
            ("Chrome Cache", cache_home / "Google" / "Chrome" / "User Data" / "Default" / "Cache"),
            ("Edge Cache", cache_home / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache"),
        ]
        firefox_profiles = cache_home / "Mozilla" / "Firefox" / "Profiles"
    elif system == "Darwin":
        candidates = [
            ("Chrome Cache", cache_home / "Google" / "Chrome" / "Default" / "Cache"),
            ("Edge Cache", cache_home / "Microsoft Edge" / "Default" / "Cache"),
        ]
        firefox_profiles = cache_home / "Firefox" / "Profiles"
    else:
        candidates = [
            ("Chrome Cache", cache_home / "google-chrome" / "Default" / "Cache"),
            ("Edge Cache", cache_home / "microsoft-edge" / "Default" / "Cache"),
        ]
        firefox_profiles = cache_home / "mozilla" / "firefox"

    targets: list[CleanTarget | None] = [
        _make_exact_target(label, path, within=cache_home) for label, path in candidates
    ]

    resolved_firefox_profiles = _resolve_descendant(firefox_profiles, cache_home)
    if resolved_firefox_profiles is not None:
        try:
            profiles = list(resolved_firefox_profiles.iterdir())
        except OSError:
            profiles = []

        for profile in profiles:
            targets.append(
                _make_exact_target(
                    "Firefox Cache",
                    profile / "cache2",
                    within=resolved_firefox_profiles,
                )
            )

    return _unique_targets(targets)


def get_log_targets() -> list[CleanTarget]:
    if platform.system() != "Windows":
        return []

    system_root = _env_path("SystemRoot") or Path("C:/Windows")
    return _unique_targets(
        [_make_exact_target("Windows Temp", system_root / "Temp", within=system_root)]
    )


def _declared_clean_targets() -> list[CleanTarget]:
    return _unique_targets(get_temp_targets() + get_browser_cache_targets() + get_log_targets())


def _resolve_allowed_target(path: Path) -> Path | None:
    """Solo autoriza coincidencias exactas con destinos declarados por el limpiador."""
    resolved = _resolve_existing(path)
    if resolved is None:
        return None

    allowed_paths = {target.path for target in _declared_clean_targets()}
    return resolved if resolved in allowed_paths else None


def _is_safe_clean_root(path: Path) -> bool:
    """Compatibilidad interna: seguro significa un destino declarado exacto, no una subruta cualquiera."""
    return _resolve_allowed_target(path) is not None


def _is_link_or_reparse_stat(info: os.stat_result) -> bool:
    """Detecta symlinks y, en Windows, junctions/reparse points sin seguir el destino."""
    if stat.S_ISLNK(info.st_mode):
        return True

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(info, "st_file_attributes", 0)
    return bool(reparse_flag and file_attributes & reparse_flag)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        return _is_link_or_reparse_stat(path.lstat())
    except OSError:
        return False


def _directory_identity(path: Path) -> tuple[int, int] | None:
    """Identidad del directorio sin seguir enlaces; permite detectar sustituciones del target."""
    try:
        info = path.lstat()
    except OSError:
        return None

    if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse_stat(info):
        return None
    return info.st_dev, info.st_ino


def _path_stays_within(path: Path, allowed_root: Path) -> bool:
    """Revalida que una raiz recorrida no se haya convertido en enlace hacia fuera."""
    if _is_link_or_reparse(path):
        return False

    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False

    return resolved == allowed_root or allowed_root in resolved.parents


def _supports_fd_walk() -> bool:
    """Usa descriptores cuando el SO permite borrar relativo a un directorio ya abierto."""
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    return (
        hasattr(os, "fwalk")
        and hasattr(os, "O_NOFOLLOW")
        and os.unlink in supports_dir_fd
        and os.rmdir in supports_dir_fd
        and os.stat in supports_dir_fd
    )


def _remove_link_like(path: Path) -> None:
    """Elimina el enlace/junction en si mismo, nunca su destino."""
    try:
        path.unlink()
    except (IsADirectoryError, PermissionError):
        # Los directory junctions de Windows se eliminan como directorios.
        path.rmdir()


def _record_failure(result: CleanResult, path: Path | str) -> None:
    result.failed += 1
    result.errors.append(str(path))
    logger.warning("No se pudo borrar %s", path, exc_info=True)


def _delete_with_fd_walk(
    folder: Path,
    expected_identity: tuple[int, int],
    *,
    dry_run: bool,
) -> CleanResult:
    """Borrado POSIX anclado a un dir_fd para evitar sustituciones de rutas."""
    result = CleanResult()
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY

    try:
        root_fd = os.open(folder, flags)
    except Exception:
        _record_failure(result, folder)
        return result

    try:
        root_info = os.fstat(root_fd)
        if (root_info.st_dev, root_info.st_ino) != expected_identity:
            result.failed += 1
            result.errors.append(str(folder))
            logger.warning("El destino de limpieza cambio antes de abrirse: %s", folder)
            return result

        iterator = os.fwalk(
            ".",
            topdown=False,
            follow_symlinks=False,
            dir_fd=root_fd,
        )
        for relative_root, dirs, files, dir_fd in iterator:
            root = folder if relative_root == "." else folder / relative_root

            for file_name in files:
                path = root / file_name
                try:
                    if not dry_run:
                        os.unlink(file_name, dir_fd=dir_fd)
                    result.deleted += 1
                except Exception:
                    _record_failure(result, path)

            for dir_name in dirs:
                path = root / dir_name
                try:
                    info = os.stat(dir_name, dir_fd=dir_fd, follow_symlinks=False)
                    if not dry_run:
                        if _is_link_or_reparse_stat(info):
                            os.unlink(dir_name, dir_fd=dir_fd)
                        else:
                            # rmdir es intencionadamente no recursivo: si aparece contenido nuevo,
                            # falla de forma cerrada en lugar de borrarlo.
                            os.rmdir(dir_name, dir_fd=dir_fd)
                    result.deleted += 1
                except Exception:
                    _record_failure(result, path)
    except Exception:
        _record_failure(result, folder)
    finally:
        os.close(root_fd)

    return result


def _delete_with_path_walk(
    folder: Path,
    expected_identity: tuple[int, int],
    *,
    dry_run: bool,
) -> CleanResult:
    """Fallback portable sin rmtree: revalida raices y solo hace unlink/rmdir superficiales."""
    result = CleanResult()

    for root, dirs, files in os.walk(folder, topdown=False, followlinks=False):
        root_path = Path(root)

        if _directory_identity(folder) != expected_identity or not _path_stays_within(
            root_path, folder
        ):
            result.failed += 1
            result.errors.append(str(root_path))
            logger.warning("Se omite una ruta que cambio durante la limpieza: %s", root_path)
            continue

        for file_name in files:
            path = root_path / file_name
            try:
                if not dry_run:
                    path.unlink()
                result.deleted += 1
            except Exception:
                _record_failure(result, path)

        for dir_name in dirs:
            path = root_path / dir_name
            try:
                link_like = _is_link_or_reparse(path)
                if not dry_run:
                    if link_like:
                        _remove_link_like(path)
                    else:
                        # Nunca rmtree: un directorio que haya recibido contenido nuevo no se
                        # elimina recursivamente por sorpresa.
                        path.rmdir()
                result.deleted += 1
            except Exception:
                _record_failure(result, path)

    return result


def build_preview(targets: list[CleanTarget]) -> CleanPreview:
    preview = CleanPreview(targets=targets)
    for target in targets:
        allowed_root = _resolve_allowed_target(target.path)
        if allowed_root is None:
            continue

        for root, dirs, files in os.walk(allowed_root, followlinks=False):
            root_path = Path(root)
            if not _path_stays_within(root_path, allowed_root):
                dirs[:] = []
                continue

            preview.items += len(dirs) + len(files)
            for file_name in files:
                try:
                    # lstat evita seguir un symlink de archivo fuera del target durante la preview.
                    preview.bytes += (root_path / file_name).lstat().st_size
                except OSError:
                    pass
    return preview


def delete_folder_contents(folder, dry_run: bool = False) -> CleanResult:
    """Borra solo el contenido de un CleanTarget exacto sin seguir enlaces fuera del target."""
    result = CleanResult()
    folder = _resolve_allowed_target(Path(folder))
    if folder is None:
        return result

    expected_identity = _directory_identity(folder)
    if expected_identity is None:
        return result

    if _supports_fd_walk():
        return _delete_with_fd_walk(folder, expected_identity, dry_run=dry_run)

    return _delete_with_path_walk(folder, expected_identity, dry_run=dry_run)


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
