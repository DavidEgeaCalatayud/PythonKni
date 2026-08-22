from __future__ import annotations

import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt5.QtWidgets import (
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pythonkni.core.tasks import WorkerCancelled
from tools.base_tool import BaseTool
from tools.worker import Worker


NETSH_TIMEOUT_SECONDS = 10.0


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise WorkerCancelled()


def _run_netsh(args: list[str], timeout: float = NETSH_TIMEOUT_SECONDS) -> str:
    completed = subprocess.run(
        ["netsh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=timeout,
    )
    return completed.stdout


def _parse_profiles(output: str) -> list[str]:
    profiles = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        profile = right.strip()
        label = left.lower()
        if profile and ("profile" in label or "perfil" in label):
            profiles.append(profile)
    return profiles


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _profile_name_from_xml(root: ET.Element) -> str | None:
    for child in root:
        if _local_name(child.tag) == "name":
            return child.text.strip() if child.text else None
    return None


def _key_material_from_xml(root: ET.Element) -> str | None:
    for node in root.iter():
        if _local_name(node.tag) == "keyMaterial":
            return node.text if node.text else None
    return None


def _read_exported_password(profile: str, export_root: Path) -> str:
    """Export one profile into an isolated directory and read only its matching XML."""
    with tempfile.TemporaryDirectory(prefix="wifi_profile_", dir=export_root) as temp_dir:
        export_dir = Path(temp_dir)
        _run_netsh(
            [
                "wlan",
                "export",
                "profile",
                f"name={profile}",
                "key=clear",
                f"folder={export_dir}",
            ]
        )

        matching_roots: list[ET.Element] = []
        for exported_file in sorted(export_dir.glob("*.xml")):
            root = ET.parse(exported_file).getroot()
            if _profile_name_from_xml(root) == profile:
                matching_roots.append(root)

        if not matching_roots:
            raise ValueError(f"No se encontró un XML exportado que corresponda al perfil '{profile}'.")

        password = _key_material_from_xml(matching_roots[0])
        return password or "No Password"


def get_wifi_profiles(cancel_event: threading.Event | None = None):
    """Obtiene las redes WiFi guardadas en Windows junto con sus contrasenas."""
    _check_cancel(cancel_event)
    try:
        output = _run_netsh(["wlan", "show", "profiles"])
        profiles = _parse_profiles(output)
        wifi_data = []

        with tempfile.TemporaryDirectory(prefix="pythonkni_wifi_") as temp_dir:
            export_root = Path(temp_dir)
            for profile in profiles:
                _check_cancel(cancel_event)
                try:
                    password = _read_exported_password(profile, export_root)
                except subprocess.TimeoutExpired:
                    password = "Timeout retrieving"
                except (subprocess.CalledProcessError, ET.ParseError, OSError, ValueError):
                    password = "Error retrieving"
                wifi_data.append((profile, password))

        _check_cancel(cancel_event)
        return wifi_data
    except WorkerCancelled:
        raise
    except subprocess.TimeoutExpired:
        return [("Error", "Tiempo de espera agotado ejecutando netsh.")]
    except Exception as error:
        return [("Error", str(error))]


def _load_wifi_task(worker: Worker):
    return get_wifi_profiles(cancel_event=worker.cancel_event)


class Tool(BaseTool):
    name = "Listado WiFi + Claves"
    description = "Consulta perfiles y datos de redes Wi-Fi guardadas."
    category = "Red"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(100, 100, 800, 600)
        self.worker: Worker | None = None

        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QTableWidget {
                background-color: #2b2b2b;
                color: white;
                font-size: 14px;
                gridline-color: #444;
                border: 1px solid #444;
            }
            QTableWidget QHeaderView::section {
                background-color: #3d3d3d;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: 1px solid #444;
            }
        """)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["WiFi Name", "Password"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.clicked.connect(self.refresh_wifi_data)

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_loading)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addWidget(self.btn_refresh)
        layout.addWidget(self.btn_cancel)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Starting a QThread is non-blocking; all netsh work runs inside Worker.run().
        self.refresh_wifi_data()

    def _loading_active(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _set_loading(self, loading: bool) -> None:
        self.btn_refresh.setEnabled(not loading)
        self.btn_cancel.setEnabled(loading)
        if loading:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("Cargando perfiles Wi-Fi..."))
            self.table.setItem(0, 1, QTableWidgetItem(""))

    def refresh_wifi_data(self) -> bool:
        if self._loading_active():
            return False

        worker = Worker(_load_wifi_task)
        worker.result.connect(self.show_wifi_data)
        worker.error.connect(lambda error: self.show_wifi_data([("Error", str(error))]))
        worker.cancelled.connect(self.on_loading_cancelled)
        worker.finished.connect(lambda worker=worker: self._on_worker_finished(worker))
        self.worker = worker
        self._set_loading(True)
        self.start_managed_worker(worker, cancel=worker.cancel)
        return True

    def cancel_loading(self) -> None:
        if not self._loading_active():
            return
        self.worker.cancel()
        self.btn_cancel.setEnabled(False)

    def on_loading_cancelled(self) -> None:
        self.table.setRowCount(1)
        self.table.setItem(0, 0, QTableWidgetItem("Carga cancelada"))
        self.table.setItem(0, 1, QTableWidgetItem(""))

    def show_wifi_data(self, data):
        self.table.setRowCount(len(data))
        for row, (name, password) in enumerate(data):
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(password))

    def _on_worker_finished(self, worker: Worker) -> None:
        if self.worker is not worker:
            return
        self.worker = None
        self._set_loading(False)
