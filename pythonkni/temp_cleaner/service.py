from __future__ import annotations

import logging
import os
import platform
import stat
from pathlib import Path

from .models import CleanPreview, CleanResult, CleanTarget

logger = logging.getLogger(__name__)


def _env_absolute_path(name: str) -> Path | None:
    """Return an absolute environment path, rejecting empty and relative values."""
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return None

    path = Path(raw_value).expanduser()
    return path if path.is_absolute() else None


def _is_link_or_reparse_stat(info: os.stat_result) -> bool:
    """Detect symbolic links and Windows reparse points without following them."""
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


def _path_chain_is_real(path: Path) -> bool:
    """Reject a path when any existing component is a symlink or reparse point."""
    path = path.expanduser()
    if not path.is_absolute():
        return False

    current = Path(path.anchor)
    parts = path.parts[1:] if path.anchor else path.parts
    for part in parts:
        current /= part
        try:
            info = current.lstat()
        except OSError:
            return False
        if _is_link_or_reparse_stat(info):
            return False
    return True


def _resolve_existing(path: Path) -> Path | None:
    """Resolve an existing directory only when its full path chain is non-reparse."""
    path = path.expanduser()
    if not _path_chain_is_real(path):
        return None

    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError:
        return None

    if not stat.S_ISDIR(info.st_mode):
        return None
    return resolved


def _resolved_path(path: Path) -> Path | None:
    """Resolve a path without accepting symlink/reparse components."""
    path = path.expanduser()
    if not path.is_absolute():
        return None

    try:
        if path.exists() and not _path_chain_is_real(path):
            return None
        return path.resolve()
    except OSError:
        return None


def _temp_candidates() -> list[CleanTarget]:
    if platform.system() != "Windows":
        return []

    targets: list[CleanTarget] = []
    for env_name in ("TEMP", "TMP"):
        env_path = _env_absolute_path(env_name)
        if env_path is not None:
            targets.append(CleanTarget(f"Temporal de usuario ({env_name})", env_path))
    return targets


def _browser_cache_root() -> Path:
    system = platform.system()
    home = Path.home()

    if system == "Windows":
        return _env_absolute_path("LOCALAPPDATA") or home / "AppData" / "Local"
    if system == "Darwin":
        return home / "Library" / "Caches"
    return _env_absolute_path("XDG_CACHE_HOME") or home / ".cache"


def _browser_cache_candidates() -> list[CleanTarget]:
    system = platform.system()
    cache_root = _browser_cache_root()

    if system == "Windows":
        targets = [
            CleanTarget(
                "Chrome Cache",
                cache_root / "Google" / "Chrome" / "User Data" / "Default" / "Cache",
            ),
            CleanTarget(
                "Edge Cache",
                cache_root / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache",
            ),
        ]
        firefox_profiles = cache_root / "Mozilla" / "Firefox" / "Profiles"
    elif system == "Darwin":
        targets = [
            CleanTarget("Chrome Cache", cache_root / "Google" / "Chrome" / "Default" / "Cache"),
            CleanTarget("Edge Cache", cache_root / "Microsoft Edge" / "Default" / "Cache"),
        ]
        firefox_profiles = cache_root / "Firefox" / "Profiles"
    else:
        targets = [
            CleanTarget("Chrome Cache", cache_root / "google-chrome" / "Default" / "Cache"),
            CleanTarget("Edge Cache", cache_root / "microsoft-edge" / "Default" / "Cache"),
        ]
        firefox_profiles = cache_root / "mozilla" / "firefox"

    resolved_profiles = _resolve_existing(firefox_profiles)
    if resolved_profiles is not None:
        try:
            profiles = list(resolved_profiles.iterdir())
        except OSError:
            profiles = []

        for profile in profiles:
            cache2 = profile / "cache2"
            if _resolve_existing(cache2) is not None:
                targets.append(CleanTarget("Firefox Cache", cache2))

    return targets


def _log_candidates() -> list[CleanTarget]:
    if platform.system() != "Windows":
        return []

    system_root = _env_absolute_path("SystemRoot")
    if system_root is None:
        system_root = Path("C:/Windows")
    return [CleanTarget("Windows Temp", system_root / "Temp")]


def _allowed_clean_containers() -> set[Path]:
    """Return broad containers used only to locate known clean targets."""
    containers: set[Path] = set()
    system = platform.system()
    home = _resolved_path(Path.home())

    if system == "Windows":
        local_app_data = _env_absolute_path("LOCALAPPDATA")
        if local_app_data is not None:
            resolved = _resolved_path(local_app_data)
            if resolved:
                containers.add(resolved)

        system_root = _env_absolute_path("SystemRoot") or Path("C:/Windows")
        resolved_system_root = _resolved_path(system_root)
        if resolved_system_root:
            containers.add(resolved_system_root)

        for env_name in ("TEMP", "TMP"):
            env_path = _env_absolute_path(env_name)
            if env_path is not None:
                resolved = _resolved_path(env_path)
                if resolved:
                    containers.add(resolved.parent)
    elif system == "Darwin":
        if home:
            cache_home = _resolved_path(home / "Library" / "Caches")
            if cache_home:
                containers.add(cache_home)
    else:
        cache_home = _resolved_path(_browser_cache_root())
        if cache_home:
            containers.add(cache_home)

    return containers


def _forbidden_clean_roots() -> set[Path]:
    """Return general-purpose roots that must never be emptied directly."""
    forbidden: set[Path] = set()
    home = _resolved_path(Path.home())
    if home:
        forbidden.add(home)
        if home.anchor:
            anchor = _resolved_path(Path(home.anchor))
            if anchor:
                forbidden.add(anchor)

    if platform.system() == "Windows":
        for env_name in ("LOCALAPPDATA", "SystemRoot"):
            env_path = _env_absolute_path(env_name)
            if env_path is not None:
                resolved = _resolved_path(env_path)
                if resolved:
                    forbidden.add(resolved)
                    if resolved.anchor:
                        anchor = _resolved_path(Path(resolved.anchor))
                        if anchor:
                            forbidden.add(anchor)

        for env_name in ("TEMP", "TMP"):
            env_path = _env_absolute_path(env_name)
            if env_path is not None:
                resolved = _resolved_path(env_path)
                if resolved:
                    forbidden.add(resolved.parent)
    else:
        forbidden.update(_allowed_clean_containers())

    return forbidden


def _allowed_exact_clean_targets() -> set[Path]:
    allowed: set[Path] = set()
    for target in _temp_candidates() + _browser_cache_candidates() + _log_candidates():
        resolved = _resolve_existing(target.path)
        if resolved:
            allowed.add(resolved)
    return allowed


def _is_safe_clean_root(path: Path) -> bool:
    """Allow only exact known cleanup targets, never links or broad containers."""
    resolved = _resolve_existing(path)
    if resolved is None or resolved in _forbidden_clean_roots():
        return False

    if resolved not in _allowed_exact_clean_targets():
        return False

    containers = _allowed_clean_containers()
    return any(container in resolved.parents for container in containers)


def _unique_safe_targets(targets: list[CleanTarget]) -> list[CleanTarget]:
    seen: set[Path] = set()
    safe_targets: list[CleanTarget] = []

    for target in targets:
        resolved = _resolve_existing(target.path)
        if resolved and resolved not in seen and _is_safe_clean_root(target.path):
            safe_targets.append(CleanTarget(target.label, resolved))
            seen.add(resolved)

    return safe_targets


def get_temp_targets() -> list[CleanTarget]:
    return _unique_safe_targets(_temp_candidates())


def get_browser_cache_targets() -> list[CleanTarget]:
    return _unique_safe_targets(_browser_cache_candidates())


def get_log_targets() -> list[CleanTarget]:
    return _unique_safe_targets(_log_candidates())


def _directory_identity(path: Path) -> tuple[int, int] | None:
    """Return a directory identity without following symlinks/reparse points."""
    try:
        info = path.lstat()
    except OSError:
        return None

    if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse_stat(info):
        return None
    return info.st_dev, info.st_ino


def _directory_matches(path: Path, expected_identity: tuple[int, int]) -> bool:
    return _directory_identity(path) == expected_identity


def _record_failure(result: CleanResult, path: Path, message: str) -> None:
    result.failed += 1
    result.errors.append(str(path))
    logger.warning("%s: %s", message, path)


def _remove_link_or_reparse(path: Path) -> None:
    """Remove the link/junction itself, never its target."""
    try:
        path.unlink()
    except (IsADirectoryError, PermissionError):
        path.rmdir()


def _delete_directory_contents(
    folder: Path,
    expected_identity: tuple[int, int],
    result: CleanResult,
    *,
    dry_run: bool,
) -> bool:
    """Delete one real directory tree while revalidating identities before mutations."""
    if not _directory_matches(folder, expected_identity):
        _record_failure(result, folder, "El directorio cambió durante la limpieza")
        return False

    try:
        entries = list(os.scandir(folder))
    except OSError:
        _record_failure(result, folder, "No se pudo enumerar el directorio")
        return False

    # scandir may have observed a path after it was replaced. Never act on those
    # entries until the root identity is checked again.
    if not _directory_matches(folder, expected_identity):
        _record_failure(result, folder, "El directorio cambió durante la enumeración")
        return False

    for entry in entries:
        if not _directory_matches(folder, expected_identity):
            _record_failure(result, folder, "La raíz cambió durante la limpieza")
            return False

        child = folder / entry.name
        try:
            info = child.lstat()
        except OSError:
            _record_failure(result, child, "No se pudo inspeccionar el elemento")
            continue

        if _is_link_or_reparse_stat(info):
            try:
                if not dry_run:
                    _remove_link_or_reparse(child)
                result.deleted += 1
            except OSError:
                _record_failure(result, child, "No se pudo eliminar el enlace/reparse point")
            continue

        if stat.S_ISDIR(info.st_mode):
            child_identity = (info.st_dev, info.st_ino)
            child_completed = _delete_directory_contents(
                child,
                child_identity,
                result,
                dry_run=dry_run,
            )
            if not child_completed:
                continue

            if not _directory_matches(folder, expected_identity):
                _record_failure(result, folder, "La raíz cambió antes de eliminar un directorio")
                return False

            if not _directory_matches(child, child_identity):
                _record_failure(result, child, "El subdirectorio fue sustituido")
                continue

            try:
                if not dry_run:
                    # Deliberately non-recursive: newly-arrived content makes this
                    # fail closed instead of being deleted unexpectedly.
                    child.rmdir()
                result.deleted += 1
            except OSError:
                _record_failure(result, child, "No se pudo eliminar el subdirectorio")
            continue

        try:
            if not dry_run:
                child.unlink()
            result.deleted += 1
        except OSError:
            _record_failure(result, child, "No se pudo eliminar el archivo")

    return _directory_matches(folder, expected_identity)


def _preview_directory(
    folder: Path,
    expected_identity: tuple[int, int],
    preview: CleanPreview,
) -> bool:
    """Preview without following links and abort traversal when identities change."""
    if not _directory_matches(folder, expected_identity):
        return False

    try:
        entries = list(os.scandir(folder))
    except OSError:
        return False

    if not _directory_matches(folder, expected_identity):
        return False

    for entry in entries:
        if not _directory_matches(folder, expected_identity):
            return False

        child = folder / entry.name
        try:
            info = child.lstat()
        except OSError:
            continue

        preview.items += 1
        if _is_link_or_reparse_stat(info):
            if not stat.S_ISDIR(info.st_mode):
                preview.bytes += info.st_size
            continue

        if stat.S_ISDIR(info.st_mode):
            _preview_directory(child, (info.st_dev, info.st_ino), preview)
        else:
            preview.bytes += info.st_size

    return _directory_matches(folder, expected_identity)


def build_preview(targets: list[CleanTarget]) -> CleanPreview:
    preview = CleanPreview()
    for target in targets:
        resolved = _resolve_existing(target.path)
        if resolved is None or not _is_safe_clean_root(target.path):
            continue

        identity = _directory_identity(resolved)
        if identity is None:
            continue

        preview.targets.append(CleanTarget(target.label, resolved))
        _preview_directory(resolved, identity, preview)

    return preview


def delete_folder_contents(folder, dry_run: bool = False) -> CleanResult:
    """Delete contents of an exact approved target without following links."""
    result = CleanResult()
    requested = Path(folder)
    if not _is_safe_clean_root(requested):
        return result

    resolved = _resolve_existing(requested)
    if resolved is None:
        return result

    identity = _directory_identity(resolved)
    if identity is None:
        return result

    _delete_directory_contents(resolved, identity, result, dry_run=dry_run)
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
