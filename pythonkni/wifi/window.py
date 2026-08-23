from __future__ import annotations

import sys as _sys
import types as _types

from PyQt5.QtWidgets import (
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.worker import Worker

from . import service as _service
from .service import (
    NETSH_TIMEOUT_SECONDS as NETSH_TIMEOUT_SECONDS,
)
from .service import (
    _check_cancel as _check_cancel,
)
from .service import (
    _key_material_from_xml as _key_material_from_xml,
)
from .service import (
    _local_name as _local_name,
)
from .service import (
    _parse_profiles as _parse_profiles,
)
from .service import (
    _profile_name_from_xml as _profile_name_from_xml,
)
from .service import (
    _read_exported_password as _read_exported_password,
)
from .service import (
    _run_netsh as _run_netsh,
)
from .service import (
    get_wifi_profiles as get_wifi_profiles,
)


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


class _CompatibilityModule(_types.ModuleType):
    """Forward legacy monkeypatches to the separated service module."""

    def __setattr__(self, name, value):
        if hasattr(_service, name):
            setattr(_service, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_service, name):
            delattr(_service, name)
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _CompatibilityModule
