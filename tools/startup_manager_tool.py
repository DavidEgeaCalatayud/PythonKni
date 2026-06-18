from __future__ import annotations

import csv
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - solo existe en Windows
    winreg = None  # type: ignore

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from tools.theme_manager import ThemeManager


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


@dataclass
class StartupItem:
    active: bool
    name: str
    source: str
    command: str
    item_type: str
    exists: str
    risk: str
    origin_kind: str
    root_name: str = ""
    key_path: str = ""
    value_name: str = ""
    value_type: int = 0
    file_path: str = ""
    backup_path: str = ""
    metadata_path: str = ""
    disabled_id: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


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
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    if not folder.exists():
        raise FileNotFoundError(str(folder))

    if platform.system() == "Windows":
        os.startfile(str(folder))  # type: ignore[attr-defined]
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))



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
        match = re.match(r"(.+?\.(?:exe|bat|cmd|ps1|vbs|js|lnk|url))(?:\s|$)", expanded, re.IGNORECASE)
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
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DISABLED_REGISTRY_KEY, 0, winreg.KEY_READ) as root_key:
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


def create_disabled_registry_backup(item: StartupItem) -> str:
    if not is_windows():
        raise RuntimeError("Esta función solo está disponible en Windows.")

    disabled_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, DISABLED_REGISTRY_KEY, 0, winreg.KEY_WRITE) as root_key:
        with winreg.CreateKeyEx(root_key, disabled_id, 0, winreg.KEY_WRITE) as item_key:
            winreg.SetValueEx(item_key, "Name", 0, winreg.REG_SZ, item.value_name or item.name)
            winreg.SetValueEx(item_key, "Command", 0, winreg.REG_SZ, item.command)
            winreg.SetValueEx(item_key, "Source", 0, winreg.REG_SZ, item.source)
            winreg.SetValueEx(item_key, "OriginalRoot", 0, winreg.REG_SZ, item.root_name)
            winreg.SetValueEx(item_key, "OriginalKey", 0, winreg.REG_SZ, item.key_path)
            winreg.SetValueEx(item_key, "OriginalValueType", 0, winreg.REG_DWORD, int(item.value_type or winreg.REG_SZ))
            winreg.SetValueEx(item_key, "DisabledAt", 0, winreg.REG_SZ, now_stamp())
    return disabled_id



def delete_disabled_registry_backup(disabled_id: str) -> None:
    if not is_windows():
        return
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{DISABLED_REGISTRY_KEY}\\{disabled_id}")
    except OSError:
        pass



def disable_registry_item(item: StartupItem) -> None:
    if not is_windows():
        raise RuntimeError("Esta función solo está disponible en Windows.")
    if item.root_name not in REGISTRY_ROOTS:
        raise RuntimeError("Raíz de registro no reconocida.")

    create_disabled_registry_backup(item)
    root = REGISTRY_ROOTS[item.root_name]
    with winreg.OpenKey(root, item.key_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, item.value_name)



def enable_registry_item(item: StartupItem) -> None:
    if not is_windows():
        raise RuntimeError("Esta función solo está disponible en Windows.")
    if item.root_name not in REGISTRY_ROOTS:
        raise RuntimeError("Raíz de registro no reconocida.")

    root = REGISTRY_ROOTS[item.root_name]
    with winreg.CreateKeyEx(root, item.key_path, 0, winreg.KEY_SET_VALUE) as key:
        value_type = item.value_type or winreg.REG_SZ
        winreg.SetValueEx(key, item.value_name or item.name, 0, value_type, item.command)

    delete_disabled_registry_backup(item.disabled_id)



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

    shutil.move(str(original), str(backup_path))

    metadata = {
        "name": item.name,
        "source": item.source,
        "original_path": str(original),
        "backup_path": str(backup_path),
        "disabled_at": now_stamp(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")



def enable_folder_item(item: StartupItem) -> None:
    backup = Path(item.backup_path or item.command)
    metadata_path = Path(item.metadata_path)
    if not backup.exists():
        raise FileNotFoundError(str(backup))
    if not metadata_path.exists():
        raise FileNotFoundError(str(metadata_path))

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    original_path = Path(str(metadata.get("original_path") or ""))
    if not original_path:
        raise RuntimeError("No se pudo obtener la ruta original.")
    if original_path.exists():
        raise FileExistsError(f"Ya existe un archivo en la ruta original: {original_path}")

    original_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(backup), str(original_path))
    metadata_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Interfaz PyQt5
# ---------------------------------------------------------------------------


class Tool(QMainWindow):
    name = "Gestor de Inicio de Windows"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(220, 220, 1250, 650)
        ThemeManager.apply_theme(self)

        self.items_by_id: dict[str, StartupItem] = {}
        self.items: list[StartupItem] = []

        layout = QVBoxLayout()
        layout.addWidget(
            QLabel(
                "Revisa los programas que arrancan con Windows. "
                "Las desactivaciones se guardan como copia recuperable, no se eliminan definitivamente."
            )
        )

        self.status_label = QLabel("Pulsa Actualizar para cargar las entradas de inicio.")
        layout.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Activo", "Nombre", "Origen", "Comando / Ruta", "Tipo", "Existe archivo", "Riesgo"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        button_layout = QHBoxLayout()

        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.clicked.connect(self.load_items)
        button_layout.addWidget(self.btn_refresh)

        self.btn_disable = QPushButton("Desactivar")
        self.btn_disable.clicked.connect(self.disable_selected)
        button_layout.addWidget(self.btn_disable)

        self.btn_enable = QPushButton("Activar")
        self.btn_enable.clicked.connect(self.enable_selected)
        button_layout.addWidget(self.btn_enable)

        self.btn_open = QPushButton("Abrir ubicación")
        self.btn_open.clicked.connect(self.open_selected_location)
        button_layout.addWidget(self.btn_open)

        self.btn_copy = QPushButton("Copiar ruta")
        self.btn_copy.clicked.connect(self.copy_selected_command)
        button_layout.addWidget(self.btn_copy)

        self.btn_export = QPushButton("Exportar CSV")
        self.btn_export.clicked.connect(self.export_csv)
        button_layout.addWidget(self.btn_export)

        layout.addLayout(button_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.load_items()

    def load_items(self) -> None:
        if not is_windows():
            self.table.setRowCount(0)
            self.status_label.setText("Esta herramienta solo funciona en Windows.")
            QMessageBox.warning(self, self.name, "Esta herramienta solo funciona en Windows.")
            return

        self.items = collect_startup_items()
        self.items_by_id = {item.id: item for item in self.items}
        self.fill_table(self.items)
        active_count = sum(1 for item in self.items if item.active)
        disabled_count = len(self.items) - active_count
        self.status_label.setText(
            f"Entradas activas: {active_count} | Entradas desactivadas recuperables: {disabled_count}"
        )

    def fill_table(self, items: list[StartupItem]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))

        for row, item in enumerate(items):
            active_item = QTableWidgetItem("Sí" if item.active else "No")
            active_item.setData(Qt.UserRole, item.id)
            self.table.setItem(row, 0, active_item)
            self.table.setItem(row, 1, QTableWidgetItem(item.name))
            self.table.setItem(row, 2, QTableWidgetItem(item.source))
            self.table.setItem(row, 3, QTableWidgetItem(item.command))
            self.table.setItem(row, 4, QTableWidgetItem(item.item_type))
            self.table.setItem(row, 5, QTableWidgetItem(item.exists))
            self.table.setItem(row, 6, QTableWidgetItem(item.risk))

        self.table.setSortingEnabled(True)

    def selected_item(self) -> StartupItem | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, self.name, "Selecciona una entrada primero.")
            return None
        id_item = self.table.item(row, 0)
        if id_item is None:
            return None
        item_id = id_item.data(Qt.UserRole)
        return self.items_by_id.get(str(item_id))

    def disable_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        if not item.active:
            QMessageBox.information(self, self.name, "Esta entrada ya está desactivada.")
            return

        extra_warning = ""
        if item.root_name == "HKLM":
            extra_warning = "\n\nEsta entrada pertenece a HKEY_LOCAL_MACHINE y puede requerir ejecutar la app como administrador."

        response = QMessageBox.question(
            self,
            "Confirmar desactivación",
            f"¿Quieres desactivar esta entrada de inicio?\n\nNombre: {item.name}\nOrigen: {item.source}\n\n"
            "Se guardará una copia para poder restaurarla después."
            f"{extra_warning}",
        )
        if response != QMessageBox.Yes:
            return

        try:
            if item.origin_kind == "registry":
                disable_registry_item(item)
            elif item.origin_kind == "folder":
                disable_folder_item(item)
            else:
                QMessageBox.warning(self, self.name, "Este tipo de entrada no se puede desactivar.")
                return

            QMessageBox.information(self, self.name, "Entrada desactivada correctamente.")
            self.load_items()
        except PermissionError as error:
            QMessageBox.critical(
                self,
                "Permisos insuficientes",
                f"No se pudo desactivar la entrada. Prueba a ejecutar PythonKni como administrador.\n\n{error}",
            )
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo desactivar la entrada:\n{error}")

    def enable_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        if item.active:
            QMessageBox.information(self, self.name, "Esta entrada ya está activa.")
            return

        response = QMessageBox.question(
            self,
            "Confirmar activación",
            f"¿Quieres restaurar esta entrada de inicio?\n\nNombre: {item.name}\nOrigen original: {item.source}",
        )
        if response != QMessageBox.Yes:
            return

        try:
            if item.origin_kind == "disabled_registry":
                enable_registry_item(item)
            elif item.origin_kind == "disabled_folder":
                enable_folder_item(item)
            else:
                QMessageBox.warning(self, self.name, "Este tipo de entrada no se puede activar.")
                return

            QMessageBox.information(self, self.name, "Entrada restaurada correctamente.")
            self.load_items()
        except PermissionError as error:
            QMessageBox.critical(
                self,
                "Permisos insuficientes",
                f"No se pudo restaurar la entrada. Prueba a ejecutar PythonKni como administrador.\n\n{error}",
            )
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo restaurar la entrada:\n{error}")

    def open_selected_location(self) -> None:
        item = self.selected_item()
        if item is None:
            return

        path_to_open = ""
        if item.origin_kind in {"folder", "disabled_folder"}:
            path_to_open = item.file_path or item.backup_path or item.command
        else:
            path_to_open = extract_executable_path(item.command)

        try:
            if path_to_open and Path(path_to_open).exists():
                open_folder(path_to_open)
            elif item.origin_kind in {"registry", "disabled_registry"}:
                run_regedit_at_key(item.root_name, item.key_path)
            else:
                QMessageBox.warning(self, self.name, "No se pudo localizar una carpeta válida.")
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo abrir la ubicación:\n{error}")

    def copy_selected_command(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        QApplication.clipboard().setText(item.command)
        QMessageBox.information(self, self.name, "Ruta/comando copiado al portapapeles.")

    def export_csv(self) -> None:
        if not self.items:
            QMessageBox.warning(self, "Exportar", "No hay datos para exportar.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar CSV",
            "programas_inicio_windows.csv",
            "CSV (*.csv)",
        )
        if not file_path:
            return

        with open(file_path, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.writer(csv_file, delimiter=";")
            writer.writerow(["Activo", "Nombre", "Origen", "Comando / Ruta", "Tipo", "Existe archivo", "Riesgo"])
            for item in self.items:
                writer.writerow(
                    [
                        "Sí" if item.active else "No",
                        item.name,
                        item.source,
                        item.command,
                        item.item_type,
                        item.exists,
                        item.risk,
                    ]
                )

        QMessageBox.information(self, "Exportado", "CSV generado correctamente.")
