from __future__ import annotations
from .models import (
    CleanPreview,
    CleanResult,
    CleanTarget,
)
import logging
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from .models import (
    CleanPreview,
    CleanResult,
)

logger = logging.getLogger(__name__)
def _resolve_existing(path: Path) -> Path | None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    return resolved if resolved.exists() and resolved.is_dir() else None
def _resolved_path(path: Path) -> Path | None:
    try:
        return path.expanduser().resolve()
    except OSError:
        return None
def _temp_candidates() -> list[CleanTarget]:
    if platform.system() != "Windows":
        return []

    targets: list[CleanTarget] = []
    for env_name in ("TEMP", "TMP"):
        env_path = os.environ.get(env_name)
        if env_path:
            targets.append(CleanTarget(f"Temporal de usuario ({env_name})", Path(env_path)))
    return targets
def _browser_cache_candidates() -> list[CleanTarget]:
    system = platform.system()
    home = Path.home()

    if system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        targets = [
            CleanTarget(
                "Chrome Cache", local / "Google" / "Chrome" / "User Data" / "Default" / "Cache"
            ),
            CleanTarget(
                "Edge Cache", local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache"
            ),
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

    return targets
def _log_candidates() -> list[CleanTarget]:
    if platform.system() != "Windows":
        return []
    return [CleanTarget("Windows Temp", Path(os.environ.get("SystemRoot", "C:/Windows")) / "Temp")]
def _allowed_clean_containers() -> set[Path]:
    """Return broad containers used only to locate known clean targets.

    A container being present here never makes the container itself safe to empty.
    """
    containers: set[Path] = set()
    system = platform.system()
    home = _resolved_path(Path.home())

    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            resolved = _resolved_path(Path(local_app_data))
            if resolved:
                containers.add(resolved)

        system_root = _resolved_path(Path(os.environ.get("SystemRoot", "C:/Windows")))
        if system_root:
            containers.add(system_root)

        for env_name in ("TEMP", "TMP"):
            env_path = os.environ.get(env_name)
            if env_path:
                resolved = _resolved_path(Path(env_path))
                if resolved:
                    containers.add(resolved.parent)
    elif system == "Darwin":
        if home:
            cache_home = _resolved_path(home / "Library" / "Caches")
            if cache_home:
                containers.add(cache_home)
    else:
        cache_home = _resolved_path(
            Path(os.environ.get("XDG_CACHE_HOME", home / ".cache" if home else ""))
        )
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
            env_path = os.environ.get(env_name)
            if env_path:
                resolved = _resolved_path(Path(env_path))
                if resolved:
                    forbidden.add(resolved)
                    if resolved.anchor:
                        anchor = _resolved_path(Path(resolved.anchor))
                        if anchor:
                            forbidden.add(anchor)

        for env_name in ("TEMP", "TMP"):
            env_path = os.environ.get(env_name)
            if env_path:
                resolved = _resolved_path(Path(env_path))
                if resolved:
                    forbidden.add(resolved.parent)
    else:
        for container in _allowed_clean_containers():
            forbidden.add(container)

    return forbidden
def _allowed_exact_clean_targets() -> set[Path]:
    allowed: set[Path] = set()
    for target in _temp_candidates() + _browser_cache_candidates() + _log_candidates():
        resolved = _resolve_existing(target.path)
        if resolved:
            allowed.add(resolved)
    return allowed
def _is_safe_clean_root(path: Path) -> bool:
    """Allow only exact known cleanup targets, never their broad containers."""
    resolved = _resolve_existing(path)
    if resolved is None or resolved in _forbidden_clean_roots():
        return False

    allowed_targets = _allowed_exact_clean_targets()
    if resolved not in allowed_targets:
        return False

    containers = _allowed_clean_containers()
    return any(container in resolved.parents for container in containers)
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
    return _unique_safe_targets(_temp_candidates())
def get_browser_cache_targets() -> list[CleanTarget]:
    return _unique_safe_targets(_browser_cache_candidates())
def get_log_targets() -> list[CleanTarget]:
    return _unique_safe_targets(_log_candidates())
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
