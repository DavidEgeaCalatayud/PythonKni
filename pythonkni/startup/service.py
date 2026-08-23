from __future__ import annotations

import errno
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - only available on Windows
    winreg = None  # type: ignore

from .models import StartupItem

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DISABLED_REGISTRY_KEY = r"Software\PythonKni\DisabledStartup\Registry"

REGISTRY_LOCATIONS = [
    ("HKCU", "Registro usuario", "HKEY_CURRENT_USER", RUN_KEY),
    ("HKLM", "Registro máquina", "HKEY_LOCAL_MACHINE", RUN_KEY),
]

REGISTRY_ROOTS: dict[str, Any] = {}
if winreg is not None:
    REGISTRY_ROOTS = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
    }


class StartupTransactionError(RuntimeError):
    """Indica que una operación falló y su rollback tampoco pudo completarse."""


# ---------------------------------------------------------------------------
# Utilidades generales
# ---------------------------------------------------------------------------


def is_windows() -> bool:
    return platform.system().lower() == "windows" and winreg is not None


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def disabled_folder_root() -> Path:
    base = os.getenv("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "PythonKni" / "DisabledStartup" / "Folders"


def startup_user_folder() -> Path | None:
    appdata = os.getenv("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_common_folder() -> Path:
    program_data = os.getenv("PROGRAMDATA") or r"C:\ProgramData"
    return Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def open_folder(path: str | Path) -> None:
    """Open a folder with the platform shell without depending on Qt."""
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    if not folder.exists():
        raise FileNotFoundError(str(folder))

    system = platform.system()
    if system == "Windows":
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def run_regedit_at_key(root_name: str, key_path: str) -> None:
    """Abre regedit. Windows no permite navegar siempre a una clave exacta con fiabilidad.

    Como mínimo abre el editor para que el usuario pueda revisar la entrada.
    """
    if platform.system() != "Windows":
        return
    try:
        subprocess.Popen(["regedit.exe"])
    except Exception:
        pass


def expand_command(command: str) -> str:
    return os.path.expandvars((command or "").strip())


def extract_executable_path(command: str) -> str:
    """Intenta obtener la ruta principal de ejecución desde una entrada de inicio.

    Las claves Run pueden contener argumentos, comillas, variables de entorno o comandos
    intermedios como cmd.exe/powershell.exe. No es un parser perfecto, pero es suficiente
    para saber si el ejecutable principal existe y para abrir su ubicación.
    """
    expanded = expand_command(command)
    if not expanded:
        return ""

    if expanded.startswith('"'):
        end = expanded.find('"', 1)
        if end > 1:
            candidate = expanded[1:end]
        else:
            candidate = expanded.strip('"')
    else:
        match = re.match(
            r"(.+?\.(?:exe|bat|cmd|ps1|vbs|js|lnk|url))(?:\s|$)", expanded, re.IGNORECASE
        )
        if match:
            candidate = match.group(1)
        else:
            candidate = expanded.split()[0]

    candidate = candidate.strip().strip('"').strip("'").rstrip(",")

    # Si es un ejecutable sin ruta, intentamos resolverlo desde PATH.
    if candidate and not os.path.isabs(candidate):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    return candidate


def path_exists_from_command(command: str) -> str:
    candidate = extract_executable_path(command)
    if not candidate:
        return "No detectable"
    return "Sí" if Path(candidate).exists() else "No"


def calculate_risk(command: str, exists: str, active: bool = True) -> str:
    if not active:
        return "Desactivado"

    expanded = expand_command(command).lower()
    candidate = extract_executable_path(command).lower()

    suspicious_locations = [
        r"\appdata\local\temp",
        r"\windows\temp",
        "\\temp\\",
        "\\downloads\\",
        "\\users\\public\\",
    ]
    medium_locations = [
        "\\appdata\\roaming\\",
        "\\appdata\\local\\",
    ]
    suspicious_commands = [
        "powershell",
        "cmd.exe",
        "wscript",
        "cscript",
        "mshta",
        "regsvr32",
        "rundll32",
    ]

    if any(token in expanded for token in suspicious_locations):
        return "Alto"
    if exists == "No" and candidate:
        return "Medio"
    if any(token in expanded for token in suspicious_commands):
        if any(token in expanded for token in medium_locations + suspicious_locations):
            return "Alto"
        return "Medio"
    if any(token in expanded for token in medium_locations):
        return "Medio"
    return "Normal"


def item_from_basic(
    *,
    active: bool,
    name: str,
    source: str,
    command: str,
    item_type: str,
    origin_kind: str,
    root_name: str = "",
    key_path: str = "",
    value_name: str = "",
    value_type: int = 0,
    file_path: str = "",
    backup_path: str = "",
    metadata_path: str = "",
    disabled_id: str = "",
) -> StartupItem:
    exists = "Sí" if file_path and Path(file_path).exists() else path_exists_from_command(command)
    return StartupItem(
        active=active,
        name=name,
        source=source,
        command=command,
        item_type=item_type,
        exists=exists,
        risk=calculate_risk(command, exists, active),
        origin_kind=origin_kind,
        root_name=root_name,
        key_path=key_path,
        value_name=value_name,
        value_type=value_type,
        file_path=file_path,
        backup_path=backup_path,
        metadata_path=metadata_path,
        disabled_id=disabled_id,
    )


# ---------------------------------------------------------------------------
# Lectura de elementos de inicio
# ---------------------------------------------------------------------------


def read_registry_run_items() -> list[StartupItem]:
    items: list[StartupItem] = []
    if not is_windows():
        return items

    for root_name, source, _display_root, key_path in REGISTRY_LOCATIONS:
        root = REGISTRY_ROOTS[root_name]
        try:
            with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ) as key:
                index = 0
                while True:
                    try:
                        value_name, value_data, value_type = winreg.EnumValue(key, index)
                        index += 1
                    except OSError:
                        break

                    # Las entradas Run suelen ser REG_SZ o REG_EXPAND_SZ.
                    if isinstance(value_data, bytes):
                        command = value_data.decode(errors="ignore")
                    else:
                        command = str(value_data)

                    items.append(
                        item_from_basic(
                            active=True,
                            name=value_name,
                            source=source,
                            command=command,
                            item_type="Registro",
                            origin_kind="registry",
                            root_name=root_name,
                            key_path=key_path,
                            value_name=value_name,
                            value_type=int(value_type),
                        )
                    )
        except FileNotFoundError:
            continue
        except PermissionError:
            continue
        except OSError:
            continue

    return items


def read_startup_folder_items() -> list[StartupItem]:
    items: list[StartupItem] = []
    locations: list[tuple[str, Path | None]] = [
        ("Inicio usuario", startup_user_folder()),
        ("Inicio común", startup_common_folder()),
    ]

    for source, folder in locations:
        if folder is None or not folder.exists():
            continue
        try:
            for entry in folder.iterdir():
                if entry.name.lower() == "desktop.ini":
                    continue
                if entry.is_file() or entry.is_dir():
                    items.append(
                        item_from_basic(
                            active=True,
                            name=entry.name,
                            source=source,
                            command=str(entry),
                            item_type="Carpeta inicio",
                            origin_kind="folder",
                            file_path=str(entry),
                        )
                    )
        except PermissionError:
            continue
        except OSError:
            continue

    return items


def read_disabled_registry_items() -> list[StartupItem]:
    items: list[StartupItem] = []
    if not is_windows():
        return items

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, DISABLED_REGISTRY_KEY, 0, winreg.KEY_READ
        ) as root_key:
            index = 0
            while True:
                try:
                    disabled_id = winreg.EnumKey(root_key, index)
                    index += 1
                except OSError:
                    break

                try:
                    with winreg.OpenKey(root_key, disabled_id, 0, winreg.KEY_READ) as item_key:
                        name = str(winreg.QueryValueEx(item_key, "Name")[0])
                        command = str(winreg.QueryValueEx(item_key, "Command")[0])
                        original_root = str(winreg.QueryValueEx(item_key, "OriginalRoot")[0])
                        original_key = str(winreg.QueryValueEx(item_key, "OriginalKey")[0])
                        original_type = int(winreg.QueryValueEx(item_key, "OriginalValueType")[0])
                        source = str(winreg.QueryValueEx(item_key, "Source")[0])
                except OSError:
                    continue

                items.append(
                    item_from_basic(
                        active=False,
                        name=name,
                        source=f"{source} desactivado",
                        command=command,
                        item_type="Registro",
                        origin_kind="disabled_registry",
                        root_name=original_root,
                        key_path=original_key,
                        value_name=name,
                        value_type=original_type,
                        disabled_id=disabled_id,
                    )
                )
    except FileNotFoundError:
        pass
    except OSError:
        pass

    return items


def read_disabled_folder_items() -> list[StartupItem]:
    items: list[StartupItem] = []
    root = disabled_folder_root()
    if not root.exists():
        return items

    for metadata_file in root.glob("*.json"):
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            original_path = str(metadata.get("original_path") or "")
            backup_path = str(metadata.get("backup_path") or "")
            source = str(metadata.get("source") or "Inicio desactivado")
            name = str(metadata.get("name") or Path(original_path).name or Path(backup_path).name)
            items.append(
                item_from_basic(
                    active=False,
                    name=name,
                    source=f"{source} desactivado",
                    command=backup_path or original_path,
                    item_type="Carpeta inicio",
                    origin_kind="disabled_folder",
                    file_path=backup_path,
                    backup_path=backup_path,
                    metadata_path=str(metadata_file),
                )
            )
        except (OSError, json.JSONDecodeError):
            continue

    return items


def collect_startup_items() -> list[StartupItem]:
    items: list[StartupItem] = []
    items.extend(read_registry_run_items())
    items.extend(read_startup_folder_items())
    items.extend(read_disabled_registry_items())
    items.extend(read_disabled_folder_items())

    def sort_key(item: StartupItem) -> tuple[int, str, str]:
        return (0 if item.active else 1, item.source.lower(), item.name.lower())

    return sorted(items, key=sort_key)


# ---------------------------------------------------------------------------
# Acciones de activar/desactivar
# ---------------------------------------------------------------------------


def delete_disabled_registry_backup(disabled_id: str, *, missing_ok: bool = False) -> None:
    if not is_windows():
        return
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{DISABLED_REGISTRY_KEY}\\{disabled_id}")
    except FileNotFoundError:
        if not missing_ok:
            raise


def create_disabled_registry_backup(item: StartupItem) -> str:
    if not is_windows():
        raise RuntimeError("Esta función solo está disponible en Windows.")

    disabled_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, DISABLED_REGISTRY_KEY, 0, winreg.KEY_WRITE
        ) as root_key:
            with winreg.CreateKeyEx(root_key, disabled_id, 0, winreg.KEY_WRITE) as item_key:
                winreg.SetValueEx(item_key, "Name", 0, winreg.REG_SZ, item.value_name or item.name)
                winreg.SetValueEx(item_key, "Command", 0, winreg.REG_SZ, item.command)
                winreg.SetValueEx(item_key, "Source", 0, winreg.REG_SZ, item.source)
                winreg.SetValueEx(item_key, "OriginalRoot", 0, winreg.REG_SZ, item.root_name)
                winreg.SetValueEx(item_key, "OriginalKey", 0, winreg.REG_SZ, item.key_path)
                winreg.SetValueEx(
                    item_key,
                    "OriginalValueType",
                    0,
                    winreg.REG_DWORD,
                    int(item.value_type or winreg.REG_SZ),
                )
                winreg.SetValueEx(item_key, "DisabledAt", 0, winreg.REG_SZ, now_stamp())
    except Exception as error:
        try:
            delete_disabled_registry_backup(disabled_id, missing_ok=True)
        except Exception as rollback_error:
            raise StartupTransactionError(
                "No se pudo crear la copia de seguridad del registro y tampoco se pudo limpiar la copia parcial: "
                f"{rollback_error}"
            ) from error
        raise
    return disabled_id


def _delete_registry_value(item: StartupItem) -> None:
    root = REGISTRY_ROOTS[item.root_name]
    with winreg.OpenKey(root, item.key_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, item.value_name or item.name)


def _registry_value_exists(item: StartupItem) -> bool:
    root = REGISTRY_ROOTS[item.root_name]
    try:
        with winreg.OpenKey(root, item.key_path, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, item.value_name or item.name)
        return True
    except FileNotFoundError:
        return False


def _write_registry_value(item: StartupItem) -> None:
    root = REGISTRY_ROOTS[item.root_name]
    with winreg.CreateKeyEx(root, item.key_path, 0, winreg.KEY_SET_VALUE) as key:
        value_type = item.value_type or winreg.REG_SZ
        winreg.SetValueEx(key, item.value_name or item.name, 0, value_type, item.command)


def disable_registry_item(item: StartupItem) -> None:
    if not is_windows():
        raise RuntimeError("Esta función solo está disponible en Windows.")
    if item.root_name not in REGISTRY_ROOTS:
        raise RuntimeError("Raíz de registro no reconocida.")

    backup_id = create_disabled_registry_backup(item)
    try:
        _delete_registry_value(item)
    except Exception as error:
        try:
            delete_disabled_registry_backup(backup_id, missing_ok=True)
        except Exception as rollback_error:
            raise StartupTransactionError(
                "No se pudo desactivar la entrada de registro y tampoco se pudo retirar la copia de seguridad creada: "
                f"{rollback_error}"
            ) from error
        raise


def enable_registry_item(item: StartupItem) -> None:
    if not is_windows():
        raise RuntimeError("Esta función solo está disponible en Windows.")
    if item.root_name not in REGISTRY_ROOTS:
        raise RuntimeError("Raíz de registro no reconocida.")
    if not item.disabled_id:
        raise RuntimeError("La entrada desactivada no tiene identificador de copia de seguridad.")
    if _registry_value_exists(item):
        raise FileExistsError(
            f"Ya existe una entrada activa con el nombre {item.value_name or item.name!r}; no se sobrescribirá."
        )

    _write_registry_value(item)
    try:
        delete_disabled_registry_backup(item.disabled_id)
    except Exception as error:
        try:
            _delete_registry_value(item)
        except Exception as rollback_error:
            raise StartupTransactionError(
                "Se restauró la entrada de registro, pero no se pudo eliminar su copia desactivada ni revertir la restauración: "
                f"{rollback_error}"
            ) from error
        raise


def _move_path(source: Path, destination: Path) -> None:
    """Mueve sin sobrescribir; usa rename atómico cuando origen y destino comparten volumen."""
    if not source.exists():
        raise FileNotFoundError(str(source))
    if destination.exists():
        raise FileExistsError(str(destination))

    try:
        os.replace(str(source), str(destination))
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.move(str(source), str(destination))


def _write_pending_metadata(path: Path, metadata: dict[str, str]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())


def _cleanup_metadata_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        pass


def _preserve_disabled_folder_metadata(pending_path: Path, metadata_path: Path) -> None:
    """Intenta dejar una copia recuperable visible si el rollback del archivo falla."""
    if metadata_path.exists():
        return
    if pending_path.exists():
        os.replace(str(pending_path), str(metadata_path))


def disable_folder_item(item: StartupItem) -> None:
    original = Path(item.file_path or item.command)
    if not original.exists():
        raise FileNotFoundError(str(original))

    backup_root = disabled_folder_root()
    backup_root.mkdir(parents=True, exist_ok=True)

    unique_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    backup_name = f"{unique_id}_{original.name}"
    backup_path = backup_root / backup_name
    metadata_path = backup_root / f"{unique_id}.json"
    pending_metadata_path = backup_root / f".{unique_id}.json.tmp"

    metadata = {
        "name": item.name,
        "source": item.source,
        "original_path": str(original),
        "backup_path": str(backup_path),
        "disabled_at": now_stamp(),
    }

    moved = False
    _write_pending_metadata(pending_metadata_path, metadata)
    try:
        _move_path(original, backup_path)
        moved = True
        os.replace(str(pending_metadata_path), str(metadata_path))
    except Exception as error:
        if moved or (backup_path.exists() and not original.exists()):
            try:
                _move_path(backup_path, original)
            except Exception as rollback_error:
                try:
                    _preserve_disabled_folder_metadata(pending_metadata_path, metadata_path)
                except Exception as metadata_error:
                    raise StartupTransactionError(
                        "No se pudo desactivar la entrada, el archivo no pudo volver a su ruta original y tampoco se pudo "
                        f"conservar metadata recuperable. Rollback: {rollback_error}; metadata: {metadata_error}"
                    ) from error
                raise StartupTransactionError(
                    "No se pudo desactivar la entrada y tampoco se pudo devolver el archivo a su ruta original. "
                    f"La copia permanece en {backup_path} con metadata recuperable. Error de rollback: {rollback_error}"
                ) from error

        _cleanup_metadata_file(pending_metadata_path)
        _cleanup_metadata_file(metadata_path)
        raise


def enable_folder_item(item: StartupItem) -> None:
    backup = Path(item.backup_path or item.command)
    metadata_path = Path(item.metadata_path)
    if not backup.exists():
        raise FileNotFoundError(str(backup))
    if not metadata_path.exists():
        raise FileNotFoundError(str(metadata_path))

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    original_raw = str(metadata.get("original_path") or "").strip()
    if not original_raw:
        raise RuntimeError("No se pudo obtener la ruta original.")
    original_path = Path(original_raw)
    if original_path.exists():
        raise FileExistsError(f"Ya existe un archivo en la ruta original: {original_path}")

    original_path.parent.mkdir(parents=True, exist_ok=True)
    _move_path(backup, original_path)
    try:
        metadata_path.unlink()
    except Exception as error:
        try:
            _move_path(original_path, backup)
        except Exception as rollback_error:
            raise StartupTransactionError(
                "Se restauró el archivo, pero no se pudo eliminar su metadata ni devolverlo a la copia desactivada: "
                f"{rollback_error}"
            ) from error
        raise
