from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QPushButton, QTabWidget

from pythonkni.infrastructure.paths import NETWORK_INTELLIGENCE_DB
from pythonkni.network_intelligence.fingerprints import persist_asset_fingerprints
from pythonkni.network_intelligence.inventory import InventoryStore

from . import camera_handoff_window as _base


class PortScanner(_base.PortScanner):
    """Network Explorer port scanner with explicit inventory enrichment."""

    def __init__(self, history_tab):
        self._fingerprints_applied = False
        super().__init__(history_tab)
        self.layout().addWidget(
            QLabel(
                "Persistencia opcional: aplica los fingerprints sólo a un activo online ya existente "
                "en Network Intelligence."
            )
        )
        self.apply_fingerprints_button = QPushButton("Aplicar a Network Intelligence")
        self.apply_fingerprints_button.setEnabled(False)
        self.apply_fingerprints_button.clicked.connect(self.apply_fingerprints_to_inventory)
        self.layout().addWidget(self.apply_fingerprints_button)

    def _set_running(self, running: bool):
        super()._set_running(running)
        button = getattr(self, "apply_fingerprints_button", None)
        if button is not None:
            button.setEnabled(
                not running and bool(self.fingerprints) and not self._fingerprints_applied
            )

    def _remember_open_ports(self, results) -> None:
        super()._remember_open_ports(results)
        self._fingerprints_applied = False
        if hasattr(self, "apply_fingerprints_button"):
            self.apply_fingerprints_button.setEnabled(False)

    def _remember_fingerprints(self, results) -> None:
        self._fingerprints_applied = False
        super()._remember_fingerprints(results)

    def apply_fingerprints_to_inventory(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        if not self.fingerprints:
            return

        raw_ips = tuple(str(item.ip or "").strip() for item in self.fingerprints)
        if any(not value for value in raw_ips) or len(set(raw_ips)) != 1:
            self.result_area.append(
                "Network Intelligence: no se pueden aplicar fingerprints sin una única IP resuelta."
            )
            return
        target_ip = raw_ips[0]

        try:
            store = InventoryStore(NETWORK_INTELLIGENCE_DB)
            matches = [
                asset
                for asset in store.list_assets(online_only=True)
                if asset.ip == target_ip
            ]
            if not matches:
                self.result_area.append(
                    "Network Intelligence: no existe un activo online persistido con IP "
                    f"{target_ip}. Ejecuta primero Network Intelligence para actualizar el inventario."
                )
                return
            if len(matches) != 1:
                self.result_area.append(
                    "Network Intelligence: la IP coincide con más de un activo persistido; "
                    "se rechaza la asociación ambigua."
                )
                return

            asset = matches[0]
            persisted = persist_asset_fingerprints(store, asset, self.fingerprints)
        except Exception as error:
            _base._base._show_exception(
                self,
                "Aplicar fingerprints",
                "No se pudieron aplicar los fingerprints al inventario de Network Intelligence.",
                error,
            )
            return

        self._fingerprints_applied = True
        self.apply_fingerprints_button.setEnabled(False)
        self.result_area.append(
            "Network Intelligence actualizado: "
            f"{persisted.ip} · {persisted.scope} · riesgo {persisted.risk.value} sin modificar."
        )


class Tool(_base.Tool):
    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 800, 600)
        self._close_when_workers_finish = False

        self.history_tab = _base.HistoryTab()
        self.network_scanner = _base.NetworkScanner(self.history_tab)
        self.port_scanner = PortScanner(self.history_tab)

        tabs = QTabWidget()
        tabs.addTab(self.network_scanner, "Escáner de Red")
        tabs.addTab(self.port_scanner, "Escáner de Puertos")
        tabs.addTab(self.history_tab, "Histórico")
        self.setCentralWidget(tabs)
