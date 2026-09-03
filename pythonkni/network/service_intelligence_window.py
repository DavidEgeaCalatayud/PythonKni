from __future__ import annotations

import threading

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget

from . import fingerprint_inventory_window as _inventory_window
from . import fingerprinting
from . import window as _network_window

DEFAULT_UDP_PORTS = "53,67,68,123,161,5353"
DEFAULT_SCTP_PORTS = "3868"
MAX_EXPLICIT_TRANSPORT_PORTS = 32


def _parse_port_list(text: str) -> tuple[int, ...]:
    values = [item.strip() for item in text.split(",") if item.strip()]
    if not values:
        raise ValueError("Indica al menos un puerto.")
    if len(values) > MAX_EXPLICIT_TRANSPORT_PORTS:
        raise ValueError(
            f"Se permiten como máximo {MAX_EXPLICIT_TRANSPORT_PORTS} puertos por ejecución."
        )
    ports: set[int] = set()
    for value in values:
        try:
            port = int(value)
        except ValueError as error:
            raise ValueError(f"Puerto no válido: {value}") from error
        if port < 1 or port > 65535:
            raise ValueError(f"Puerto fuera de rango: {port}")
        ports.add(port)
    return tuple(sorted(ports))


def _fingerprint_key(item) -> tuple[object, ...]:
    findings = tuple(
        (finding.finding_id, finding.severity.value, finding.description, finding.evidence)
        for finding in item.security_findings
    )
    return (
        item.ip,
        item.port,
        item.transport,
        item.protocol,
        item.product,
        item.version,
        findings,
    )


class TransportFingerprintWorker(QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    failed = pyqtSignal(object)
    results_ready = pyqtSignal(object)

    def __init__(
        self,
        target: str,
        ports: tuple[int, ...],
        *,
        transport: str,
        misconfigs: bool = False,
    ):
        super().__init__()
        self.target = target
        self.ports = ports
        self.transport = transport
        self.misconfigs = misconfigs
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        mode = " + misconfigs" if self.misconfigs else ""
        self.message.emit(
            f"Nerva: {self.transport.upper()} sobre {len(self.ports)} puerto(s){mode}..."
        )
        try:
            results = fingerprinting.fingerprint_open_ports(
                self.target,
                self.ports,
                stop_event=self._stop_event,
                transport=self.transport,
                misconfigs=self.misconfigs,
            )
        except Exception as error:
            self.failed.emit(error)
            self.finished_summary.emit(
                f"Service Intelligence falló para {self.target} ({self.transport})."
            )
            return

        self.results_ready.emit(results)
        finding_count = sum(len(item.security_findings) for item in results)
        summary = (
            f"Service Intelligence {self.transport.upper()} en {self.target}: "
            f"{len(results)} servicio(s), {finding_count} finding(s)."
        )
        if self._stop_event.is_set():
            summary = f"[CANCELADO] {summary} Resultados parciales."
            self.cancelled.emit(summary)
        self.finished_summary.emit(summary)


class UdpFingerprintWorker(QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    failed = pyqtSignal(object)
    results_ready = pyqtSignal(object)

    def __init__(self, target: str, ports: tuple[int, ...]):
        super().__init__()
        self.target = target
        self.ports = ports
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        self.message.emit(
            f"Analizando {len(self.ports)} puerto(s) UDP con Nerva; la ausencia de respuesta "
            "no se interpretará como puerto cerrado."
        )
        try:
            results = fingerprinting.probe_udp_ports(
                self.target,
                self.ports,
                stop_event=self._stop_event,
            )
        except Exception as error:
            self.failed.emit(error)
            self.finished_summary.emit(f"Análisis UDP fallido para {self.target}.")
            return

        self.results_ready.emit(results)
        identified = sum(item.fingerprint is not None for item in results)
        summary = (
            f"UDP en {self.target}: {identified} servicio(s) identificado(s) de "
            f"{len(results)} puerto(s) analizado(s)."
        )
        if self._stop_event.is_set():
            summary = f"[CANCELADO] {summary} Resultados parciales."
            self.cancelled.emit(summary)
        self.finished_summary.emit(summary)


class PortScanner(_inventory_window.PortScanner):
    """Network Explorer with explicit Service Intelligence v2 actions."""

    def __init__(self, history_tab):
        self.udp_probe_results = ()
        super().__init__(history_tab)

        self.layout().addWidget(
            QLabel(
                "Service Intelligence v2: UDP y misconfiguraciones son acciones explícitas. "
                "SCTP sólo se habilita cuando el motor/plataforma lo soportan."
            )
        )

        udp_row = QHBoxLayout()
        udp_row.addWidget(QLabel("UDP:"))
        self.udp_ports_input = QLineEdit(DEFAULT_UDP_PORTS)
        self.udp_ports_input.setPlaceholderText("53,67,68,123,161,5353")
        udp_row.addWidget(self.udp_ports_input, 1)
        self.udp_button = QPushButton("Analizar UDP (Nerva)")
        self.udp_button.clicked.connect(self.scan_udp_services)
        udp_row.addWidget(self.udp_button)
        self.layout().addLayout(udp_row)

        sctp_row = QHBoxLayout()
        sctp_row.addWidget(QLabel("SCTP avanzado:"))
        self.sctp_ports_input = QLineEdit(DEFAULT_SCTP_PORTS)
        sctp_row.addWidget(self.sctp_ports_input, 1)
        self.sctp_button = QPushButton("Analizar SCTP")
        self.sctp_button.clicked.connect(self.scan_sctp_services)
        sctp_supported = fingerprinting.transport_available("sctp")
        self.sctp_button.setEnabled(sctp_supported)
        self.sctp_ports_input.setEnabled(sctp_supported)
        if not sctp_supported:
            explanation = "Nerva v1.69.4 soporta SCTP únicamente en Linux; no disponible en Windows."
            self.sctp_button.setToolTip(explanation)
            self.sctp_ports_input.setToolTip(explanation)
        sctp_row.addWidget(self.sctp_button)
        self.layout().addLayout(sctp_row)

        self.misconfigs_button = QPushButton("Comprobar configuraciones inseguras")
        self.misconfigs_button.setEnabled(False)
        self.misconfigs_button.setToolTip(
            "Ejecuta Nerva --misconfigs sólo sobre los puertos TCP ya confirmados abiertos. "
            "Nunca se ejecuta automáticamente desde Network Intelligence."
        )
        self.misconfigs_button.clicked.connect(self.scan_misconfigs)
        self.layout().addWidget(self.misconfigs_button)

    def _set_running(self, running: bool):
        super()._set_running(running)
        if not hasattr(self, "udp_button"):
            return
        self.udp_button.setEnabled(not running)
        sctp_supported = fingerprinting.transport_available("sctp")
        self.sctp_button.setEnabled(not running and sctp_supported)
        self.sctp_ports_input.setEnabled(not running and sctp_supported)
        self.udp_ports_input.setEnabled(not running)
        self.misconfigs_button.setEnabled(not running and bool(self.open_ports))

    def _remember_open_ports(self, results) -> None:
        self.udp_probe_results = ()
        super()._remember_open_ports(results)
        if hasattr(self, "misconfigs_button"):
            self.misconfigs_button.setEnabled(False)

    def _remember_fingerprints(self, results) -> None:
        merged = list(self.fingerprints)
        positions = {_fingerprint_key(item): index for index, item in enumerate(merged)}
        for item in results:
            key = _fingerprint_key(item)
            if key in positions:
                merged[positions[key]] = item
            else:
                positions[key] = len(merged)
                merged.append(item)
        merged.sort(
            key=lambda item: (
                item.transport,
                item.port,
                item.protocol,
                item.product,
                item.version,
            )
        )
        super()._remember_fingerprints(tuple(merged))

    def _transport_failed(self, error):
        _network_window._show_exception(
            self,
            "Service Intelligence v2",
            "No se pudo completar la comprobación solicitada con Nerva.",
            error,
        )

    def _start_transport_worker(
        self,
        *,
        transport: str,
        ports: tuple[int, ...],
        misconfigs: bool = False,
    ) -> None:
        if self.worker and self.worker.isRunning():
            return
        target = self.ip_input.text().strip()
        if not target:
            self.result_area.append("Error: Debes ingresar una dirección IP o dominio.")
            return
        worker = TransportFingerprintWorker(
            target,
            ports,
            transport=transport,
            misconfigs=misconfigs,
        )
        worker.message.connect(self.result_area.append)
        worker.failed.connect(self._transport_failed)
        worker.results_ready.connect(self._transport_results_ready)
        worker.finished_summary.connect(self.history_tab.append_to_history)
        worker.finished.connect(self._worker_finished)
        self.worker = worker
        self._set_running(True)
        worker.start()

    def _transport_results_ready(self, results) -> None:
        self._remember_fingerprints(results)
        for item in results:
            identity = " ".join(part for part in (item.product, item.version) if part).strip()
            label = f"{item.protocol} {identity}".strip()
            self.result_area.append(f"IDENTIFICADO  {item.port}/{item.transport}  {label}")
            for finding in item.security_findings:
                self.result_area.append(
                    f"FINDING  [{finding.severity.value.upper()}] {finding.finding_id} · "
                    f"{finding.description}"
                )

    def scan_udp_services(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        try:
            ports = _parse_port_list(self.udp_ports_input.text())
        except ValueError as error:
            self.result_area.append(f"Error UDP: {error}")
            return
        target = self.ip_input.text().strip()
        if not target:
            self.result_area.append("Error: Debes ingresar una dirección IP o dominio.")
            return
        self.result_area.append("\n--- Service Intelligence UDP ---")
        worker = UdpFingerprintWorker(target, ports)
        worker.message.connect(self.result_area.append)
        worker.failed.connect(self._transport_failed)
        worker.results_ready.connect(self._udp_results_ready)
        worker.finished_summary.connect(self.history_tab.append_to_history)
        worker.finished.connect(self._worker_finished)
        self.worker = worker
        self._set_running(True)
        worker.start()

    def _udp_results_ready(self, results) -> None:
        self.udp_probe_results = tuple(results)
        identified = [item.fingerprint for item in results if item.fingerprint is not None]
        self._remember_fingerprints(identified)
        for item in results:
            if item.fingerprint is None:
                self.result_area.append(f"UDP  {item.port}/udp  {item.state.value}")
                continue
            fingerprint = item.fingerprint
            identity = " ".join(
                part for part in (fingerprint.product, fingerprint.version) if part
            ).strip()
            label = f"{fingerprint.protocol} {identity}".strip()
            self.result_area.append(f"UDP  {item.port}/udp  {item.state.value} · {label}")

    def scan_sctp_services(self) -> None:
        if not fingerprinting.transport_available("sctp"):
            self.result_area.append(
                "SCTP no está disponible: Nerva v1.69.4 lo limita a plataformas Linux."
            )
            return
        try:
            ports = _parse_port_list(self.sctp_ports_input.text())
        except ValueError as error:
            self.result_area.append(f"Error SCTP: {error}")
            return
        self.result_area.append("\n--- Service Intelligence SCTP ---")
        self._start_transport_worker(transport="sctp", ports=ports)

    def scan_misconfigs(self) -> None:
        if not self.open_ports:
            self.result_area.append(
                "No hay puertos TCP confirmados abiertos. Ejecuta primero el escaneo de puertos."
            )
            return
        self.result_area.append(
            "\n--- Comprobación explícita de configuraciones inseguras (Nerva --misconfigs) ---"
        )
        ports = tuple(sorted({item.port for item in self.open_ports}))
        self._start_transport_worker(transport="tcp", ports=ports, misconfigs=True)


class Tool(_inventory_window.Tool):
    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 820, 720)
        self._close_when_workers_finish = False

        self.history_tab = _inventory_window._base.HistoryTab()
        self.network_scanner = _inventory_window._base.NetworkScanner(self.history_tab)
        self.port_scanner = PortScanner(self.history_tab)

        tabs = QTabWidget()
        tabs.addTab(self.network_scanner, "Escáner de Red")
        tabs.addTab(self.port_scanner, "Service Intelligence")
        tabs.addTab(self.history_tab, "Histórico")
        self.setCentralWidget(tabs)
