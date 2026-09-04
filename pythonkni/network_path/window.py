from __future__ import annotations

import threading
import time

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pythonkni.infrastructure.paths import (
    NETWORK_PATH_EVENTS_FILE,
    NETWORK_PATH_HISTORY_FILE,
    ensure_app_dirs,
)
from tools.base_tool import BaseTool
from tools.ui_feedback import show_error
from tools.worker import Worker

from .backend import TraceCancelled, TrippyBackend, TrippyPrivilegesRequired
from .intelligence import PathState
from .models import AddressFamily, PathUpdate, TraceProtocol, TraceRequest
from .service import append_events_jsonl, append_history_jsonl, build_request

HISTORY_RENDER_LIMIT = 180
ALERT_RENDER_LIMIT = 500


def _format_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} ms"


def _format_time(timestamp: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(timestamp))


def _run_path_analyzer(worker: Worker, request: TraceRequest, reset_event: threading.Event):
    backend = TrippyBackend()
    backend.info()
    state = PathState()
    while True:
        worker.check_cancelled()
        if reset_event.is_set():
            state = PathState()
            reset_event.clear()

        started = time.monotonic()
        try:
            snapshot = backend.trace_once(request, stop_event=worker.cancel_event)
        except TraceCancelled:
            worker.check_cancelled()
            raise
        update = state.observe(snapshot)
        append_events_jsonl(NETWORK_PATH_EVENTS_FILE, update.events)
        if update.history:
            append_history_jsonl(NETWORK_PATH_HISTORY_FILE, update.history[-1])
        worker.report_progress(update)

        remaining = request.interval_seconds - (time.monotonic() - started)
        if remaining > 0 and worker.cancel_event.wait(remaining):
            worker.check_cancelled()


class RttChart(QWidget):
    """Small dependency-free destination RTT timeline."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: tuple[float | None, ...] = ()
        self.setMinimumHeight(180)

    def set_points(self, points: tuple[float | None, ...]) -> None:
        self._points = points[-HISTORY_RENDER_LIMIT:]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        plot = self.rect().adjusted(48, 10, -12, -26)
        if plot.width() <= 1 or plot.height() <= 1:
            return

        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawRect(plot)
        values = [value for value in self._points if value is not None]
        if not values:
            painter.setPen(self.palette().text().color())
            painter.drawText(plot, Qt.AlignCenter, "Sin muestras RTT todavía")
            return

        maximum = max(10.0, max(values) * 1.10)
        for index in range(5):
            y = plot.bottom() - (plot.height() * index / 4)
            painter.setPen(QPen(self.palette().mid().color(), 1))
            painter.drawLine(plot.left(), int(y), plot.right(), int(y))
            painter.setPen(self.palette().text().color())
            painter.drawText(2, int(y + 5), f"{maximum * index / 4:.0f}")

        denominator = max(1, len(self._points) - 1)
        previous: QPointF | None = None
        painter.setPen(QPen(self.palette().highlight().color(), 2))
        for index, value in enumerate(self._points):
            if value is None:
                previous = None
                continue
            x = plot.left() + plot.width() * index / denominator
            y = plot.bottom() - plot.height() * min(max(value, 0.0), maximum) / maximum
            point = QPointF(x, y)
            if previous is not None:
                painter.drawLine(previous, point)
            previous = point


class Tool(BaseTool):
    name = "Network Path Analyzer"
    description = "Analiza latencia, pérdida y cambios de ruta salto a salto con Trippy."
    category = "Red"

    def setup_ui(self) -> None:
        ensure_app_dirs()
        self.setWindowTitle(self.name)
        self.setGeometry(120, 70, 1240, 800)
        self.worker: Worker | None = None
        self.reset_event = threading.Event()
        self.alert_rows: list[list[str]] = []

        root = QWidget()
        layout = QVBoxLayout(root)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target:"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("8.8.8.8 or example.com")
        target_row.addWidget(self.target_input, 3)
        target_row.addWidget(QLabel("Protocol:"))
        self.protocol_combo = QComboBox()
        for protocol in TraceProtocol:
            self.protocol_combo.addItem(protocol.value.upper(), protocol.value)
        self.protocol_combo.currentIndexChanged.connect(self._sync_protocol_controls)
        target_row.addWidget(self.protocol_combo)
        target_row.addWidget(QLabel("Family:"))
        self.family_combo = QComboBox()
        self.family_combo.addItem("Auto", AddressFamily.AUTO.value)
        self.family_combo.addItem("IPv4", AddressFamily.IPV4.value)
        self.family_combo.addItem("IPv6", AddressFamily.IPV6.value)
        target_row.addWidget(self.family_combo)
        layout.addLayout(target_row)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Interval:"))
        self.interval_combo = QComboBox()
        for label, seconds in (("0.5 s", 0.5), ("1 s", 1.0), ("2.5 s", 2.5), ("5 s", 5.0), ("10 s", 10.0)):
            self.interval_combo.addItem(label, seconds)
        self.interval_combo.setCurrentIndex(1)
        options_row.addWidget(self.interval_combo)
        options_row.addWidget(QLabel("Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(0, 65535)
        self.port_spin.setSpecialValueText("Auto")
        self.port_spin.setValue(0)
        self.port_spin.setToolTip("Auto: UDP 33434, TCP 443. ICMP does not use a port.")
        options_row.addWidget(self.port_spin)
        options_row.addWidget(QLabel("Max TTL:"))
        self.ttl_spin = QSpinBox()
        self.ttl_spin.setRange(1, 64)
        self.ttl_spin.setValue(30)
        options_row.addWidget(self.ttl_spin)
        self.start_button = QPushButton("▶ Start")
        self.start_button.clicked.connect(self.start_analysis)
        options_row.addWidget(self.start_button)
        self.stop_button = QPushButton("■ Stop")
        self.stop_button.clicked.connect(self.stop_analysis)
        self.stop_button.setEnabled(False)
        options_row.addWidget(self.stop_button)
        self.reset_button = QPushButton("Reset stats")
        self.reset_button.clicked.connect(self.reset_stats)
        options_row.addWidget(self.reset_button)
        options_row.addStretch(1)
        layout.addLayout(options_row)

        self.status_label = QLabel(
            "Trippy v0.13.0 backend · explicit single target only. On Windows the trace requires "
            "Administrator privileges. Missing replies from intermediate routers are not treated as "
            "proof of end-to-end packet loss."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        path_tab = QWidget()
        path_layout = QVBoxLayout(path_tab)
        self.path_table = self._table(
            ["Hop", "Host", "IP", "Loss", "Last", "Avg", "Min", "Max", "Jitter", "Status"]
        )
        path_layout.addWidget(self.path_table, 3)
        self.rtt_chart = RttChart()
        path_layout.addWidget(self.rtt_chart, 2)
        self.history_table = self._table(
            ["Time", "Destination RTT", "Destination loss", "Hops", "Reached", "Issue hop"]
        )
        self.alert_table = self._table(["Time", "Severity", "Event", "Hop", "Description"])
        self.tabs.addTab(path_tab, "Path")
        self.tabs.addTab(self.history_table, "History")
        self.tabs.addTab(self.alert_table, "Alerts")
        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(root)
        self._sync_protocol_controls()

    def _table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return table

    def _protocol_value(self) -> str:
        return str(self.protocol_combo.currentData())

    def _sync_protocol_controls(self) -> None:
        self.port_spin.setEnabled(self._protocol_value() != TraceProtocol.ICMP.value)

    def _request_from_controls(self) -> TraceRequest:
        return build_request(
            self.target_input.text(),
            protocol=self._protocol_value(),
            interval_seconds=self.interval_combo.currentData(),
            max_ttl=self.ttl_spin.value(),
            port=self.port_spin.value(),
            address_family=self.family_combo.currentData(),
        )

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        for control in (
            self.target_input,
            self.protocol_combo,
            self.family_combo,
            self.interval_combo,
            self.ttl_spin,
        ):
            control.setEnabled(not running)
        if running:
            self.port_spin.setEnabled(False)
        else:
            self._sync_protocol_controls()

    def start_analysis(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        try:
            request = self._request_from_controls()
        except ValueError as error:
            show_error(self, self.name, str(error))
            self.status_label.setText(str(error))
            return

        self._clear_views()
        self.reset_event.clear()
        self._set_running(True)
        self.status_label.setText(
            f"Analizando la ruta hacia {request.target} mediante {request.protocol.value.upper()}..."
        )
        worker = Worker(_run_path_analyzer, request, self.reset_event, parent=self)
        worker.progress.connect(self._update_path)
        worker.error.connect(self._analysis_failed)
        worker.cancelled.connect(self._analysis_cancelled)
        worker.finished.connect(self._analysis_finished)
        self.worker = worker
        self.start_managed_worker(worker, cancel=worker.cancel)

    def stop_analysis(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            return
        self.stop_button.setEnabled(False)
        self.status_label.setText("Deteniendo Network Path Analyzer...")
        self.worker.cancel()

    def reset_stats(self) -> None:
        self._clear_views()
        if self.worker is not None and self.worker.isRunning():
            self.reset_event.set()
            self.status_label.setText("Estadísticas reiniciadas; la ruta seguirá analizándose.")
        else:
            self.status_label.setText("Estadísticas reiniciadas.")

    def _analysis_failed(self, error: Exception) -> None:
        message = str(error)
        if isinstance(error, TrippyPrivilegesRequired):
            message += " Cierra PythonKni y vuelve a abrirlo con 'Ejecutar como administrador'."
        show_error(self, self.name, message)
        self.status_label.setText(f"Análisis fallido: {error}")

    def _analysis_cancelled(self) -> None:
        self.status_label.setText("Network Path Analyzer detenido.")

    def _analysis_finished(self) -> None:
        self._set_running(False)
        self.worker = None

    def _clear_views(self) -> None:
        self.path_table.setRowCount(0)
        self.history_table.setRowCount(0)
        self.alert_table.setRowCount(0)
        self.alert_rows = []
        self.rtt_chart.set_points(())

    def _set_rows(self, table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(row_index, column_index, item)

    def _update_path(self, update: PathUpdate) -> None:
        rows: list[list[str]] = []
        for hop in update.hops:
            hosts = ", ".join(host.hostname for host in hop.hosts if host.hostname) or "—"
            ips = ", ".join(host.ip for host in hop.hosts) or "*"
            rows.append(
                [
                    str(hop.ttl),
                    hosts,
                    ips,
                    f"{hop.loss_pct:.1f}%",
                    _format_ms(hop.last_ms),
                    _format_ms(hop.avg_ms),
                    _format_ms(hop.min_ms),
                    _format_ms(hop.max_ms),
                    _format_ms(hop.jitter_ms),
                    hop.status,
                ]
            )
        self._set_rows(self.path_table, rows)

        history = update.history[-HISTORY_RENDER_LIMIT:]
        self._set_rows(
            self.history_table,
            [
                [
                    _format_time(item.timestamp),
                    _format_ms(item.destination_rtt_ms),
                    f"{item.destination_loss_pct:.1f}%",
                    str(item.hop_count),
                    "Yes" if item.reached_destination else "No",
                    str(item.issue_hop_ttl) if item.issue_hop_ttl is not None else "—",
                ]
                for item in history
            ],
        )
        self.rtt_chart.set_points(tuple(item.destination_rtt_ms for item in history))

        for event in update.events:
            self.alert_rows.insert(
                0,
                [
                    _format_time(event.timestamp),
                    event.severity.value,
                    event.kind,
                    str(event.hop_ttl) if event.hop_ttl is not None else "—",
                    event.description,
                ],
            )
        del self.alert_rows[ALERT_RENDER_LIMIT:]
        self._set_rows(self.alert_table, self.alert_rows)

        destination = update.snapshot.destination_hop
        rtt = _format_ms(destination.last_ms if destination else None)
        status = (
            f"{len(update.hops)} salto(s) · destino {'alcanzado' if update.snapshot.reached_destination else 'sin respuesta'}"
            f" · RTT {rtt}"
        )
        if update.issue_hop_ttl is not None:
            status += (
                f" · primer incremento acumulado de latencia relevante alrededor de TTL "
                f"{update.issue_hop_ttl}"
            )
        self.status_label.setText(status)
