from __future__ import annotations

import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pythonkni.infrastructure.paths import (
    NETWORK_INTELLIGENCE_DB,
    NETWORK_MONITOR_CAPTURES_DIR,
    NETWORK_MONITOR_EVENTS_FILE,
    NETWORK_MONITOR_HISTORY_FILE,
    ensure_app_dirs,
)
from tools.base_tool import BaseTool
from tools.ui_feedback import show_error
from tools.worker import Worker

from .capture import PacketCaptureError, PktmonCapture
from .intelligence import MonitorState, load_known_assets
from .models import MonitorUpdate, PcapCaptureResult
from .service import (
    ALL_ADAPTERS,
    append_events_jsonl,
    append_history_jsonl,
    collect_snapshot,
    list_adapters,
    lookup_asn,
    reverse_dns,
)

POLL_SECONDS = 1.0
PERSIST_HISTORY_EVERY_SAMPLES = 5


def _format_rate(bytes_per_second: float) -> str:
    value = max(0.0, bytes_per_second)
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GB/s"
    if value >= 1024**2:
        return f"{value / 1024**2:.2f} MB/s"
    if value >= 1024:
        return f"{value / 1024:.1f} KB/s"
    return f"{value:.0f} B/s"


def _format_time(timestamp: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(timestamp))


def _run_monitor(worker: Worker, adapter_name: str, enable_asn: bool):
    state = MonitorState()
    try:
        known_assets = load_known_assets(NETWORK_INTELLIGENCE_DB)
    except Exception:
        known_assets = {}
    process_cache: dict[int, str] = {}
    previous_counters = None
    sample_count = 0
    while True:
        worker.check_cancelled()
        snapshot, previous_counters = collect_snapshot(
            adapter_name,
            previous_counters,
            process_cache=process_cache,
        )
        update = state.observe(
            snapshot,
            known_assets=known_assets,
            resolver=reverse_dns,
            asn_resolver=lookup_asn if enable_asn else None,
        )
        append_events_jsonl(NETWORK_MONITOR_EVENTS_FILE, update.events)
        sample_count += 1
        if sample_count % PERSIST_HISTORY_EVERY_SAMPLES == 0 and update.history:
            append_history_jsonl(NETWORK_MONITOR_HISTORY_FILE, update.history[-1])
        worker.report_progress(update)
        if worker.cancel_event.wait(POLL_SECONDS):
            worker.check_cancelled()


def _start_pcap(worker: Worker, capture: PktmonCapture):
    worker.check_cancelled()
    return capture.start()


def _stop_pcap(worker: Worker, capture: PktmonCapture):
    worker.check_cancelled()
    return capture.stop()


class Tool(BaseTool):
    name = "Network Traffic Monitor"
    description = "Observa conexiones y tráfico local en tiempo real con alertas pasivas y PCAP opcional."
    category = "Red"

    def setup_ui(self) -> None:
        ensure_app_dirs()
        NETWORK_MONITOR_CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle(self.name)
        self.setGeometry(150, 90, 1180, 760)
        self.worker: Worker | None = None
        self.pcap_worker: Worker | None = None
        self.capture = PktmonCapture(NETWORK_MONITOR_CAPTURES_DIR)
        self.alert_rows = []

        root = QWidget()
        layout = QVBoxLayout(root)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Adapter:"))
        self.adapter_combo = QComboBox()
        controls.addWidget(self.adapter_combo, 2)
        self.refresh_adapters_button = QPushButton("Refresh")
        self.refresh_adapters_button.clicked.connect(self.refresh_adapters)
        controls.addWidget(self.refresh_adapters_button)
        self.start_button = QPushButton("▶ Start")
        self.start_button.clicked.connect(self.start_monitoring)
        controls.addWidget(self.start_button)
        self.stop_button = QPushButton("■ Stop")
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.stop_button.setEnabled(False)
        controls.addWidget(self.stop_button)
        self.asn_check = QCheckBox("ASN (RIPEstat)")
        self.asn_check.setToolTip("Optional: contacts the RIPEstat Data API for public remote IPs.")
        controls.addWidget(self.asn_check)
        controls.addStretch(1)
        self.pcap_start_button = QPushButton("Start PCAP")
        self.pcap_start_button.clicked.connect(self.start_pcap)
        controls.addWidget(self.pcap_start_button)
        self.pcap_stop_button = QPushButton("Stop PCAP")
        self.pcap_stop_button.clicked.connect(self.stop_pcap)
        self.pcap_stop_button.setEnabled(False)
        controls.addWidget(self.pcap_stop_button)
        layout.addLayout(controls)

        traffic_row = QHBoxLayout()
        self.rx_label = QLabel("↓ 0 B/s")
        self.tx_label = QLabel("↑ 0 B/s")
        traffic_row.addWidget(self.rx_label)
        traffic_row.addSpacing(40)
        traffic_row.addWidget(self.tx_label)
        traffic_row.addStretch(1)
        layout.addLayout(traffic_row)

        self.status_label = QLabel(
            "Passive monitoring only. Adapter throughput is exact; process rows represent socket activity, "
            "not claimed per-process byte counters. ASN enrichment is opt-in and contacts RIPEstat."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.connection_table = self._table(
            ["Process", "PID", "Remote host", "Port", "Protocol", "State", "Scope", "Adapter"]
        )
        self.process_table = self._table(
            ["Process", "PID", "Connections", "External", "Remote hosts", "Protocols"]
        )
        self.host_table = self._table(
            [
                "Remote host",
                "DNS",
                "ASN",
                "Prefix",
                "Scope",
                "Connections",
                "Ports",
                "Processes",
                "Known asset",
            ]
        )
        self.history_table = self._table(
            ["Time", "RX", "TX", "Connections", "External", "Remote hosts"]
        )
        self.alert_table = self._table(["Time", "Severity", "Event", "Description"])
        self.tabs.addTab(self.connection_table, "Connections")
        self.tabs.addTab(self.process_table, "Processes")
        self.tabs.addTab(self.host_table, "Hosts")
        self.tabs.addTab(self.history_table, "History")
        self.tabs.addTab(self.alert_table, "Alerts")
        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(root)
        self.refresh_adapters()
        self._sync_pcap_buttons()

    def _table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return table

    def refresh_adapters(self) -> None:
        selected = self._adapter_value() if self.adapter_combo.count() else ALL_ADAPTERS
        self.adapter_combo.clear()
        self.adapter_combo.addItem(ALL_ADAPTERS)
        try:
            adapters = list_adapters()
        except Exception as error:
            self.status_label.setText(f"Could not enumerate adapters: {error}")
            return
        for adapter in adapters:
            state = "up" if adapter.is_up else "down"
            addresses = ", ".join(adapter.addresses) or "no IP"
            self.adapter_combo.addItem(f"{adapter.name} · {addresses} · {state}", adapter.name)
        for index in range(self.adapter_combo.count()):
            if self._adapter_value(index) == selected:
                self.adapter_combo.setCurrentIndex(index)
                break

    def _adapter_value(self, index: int | None = None) -> str:
        index = self.adapter_combo.currentIndex() if index is None else index
        data = self.adapter_combo.itemData(index)
        return str(data) if data else self.adapter_combo.itemText(index)

    def _set_monitor_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.adapter_combo.setEnabled(not running)
        self.refresh_adapters_button.setEnabled(not running)
        self.asn_check.setEnabled(not running)

    def start_monitoring(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        adapter_name = self._adapter_value()
        self._clear_tables()
        self._set_monitor_running(True)
        self.status_label.setText(f"Monitoring {adapter_name} passively...")
        worker = Worker(_run_monitor, adapter_name, self.asn_check.isChecked(), parent=self)
        worker.progress.connect(self._update_monitor)
        worker.error.connect(self._monitor_failed)
        worker.cancelled.connect(self._monitor_cancelled)
        worker.finished.connect(self._monitor_finished)
        self.worker = worker
        self.start_managed_worker(worker, cancel=worker.cancel)

    def stop_monitoring(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            return
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping passive monitor...")
        self.worker.cancel()

    def _monitor_failed(self, error: Exception) -> None:
        show_error(self, self.name, str(error))
        self.status_label.setText(f"Monitoring failed: {error}")

    def _monitor_cancelled(self) -> None:
        self.status_label.setText("Monitoring stopped.")

    def _monitor_finished(self) -> None:
        self._set_monitor_running(False)
        self.worker = None

    def _clear_tables(self) -> None:
        for table in (
            self.connection_table,
            self.process_table,
            self.host_table,
            self.history_table,
            self.alert_table,
        ):
            table.setRowCount(0)
        self.alert_rows = []

    def _set_rows(self, table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(row_index, column_index, item)

    def _update_monitor(self, update: MonitorUpdate) -> None:
        traffic = update.snapshot.traffic
        self.rx_label.setText(f"↓ {_format_rate(traffic.rx_bps)}")
        self.tx_label.setText(f"↑ {_format_rate(traffic.tx_bps)}")
        self.status_label.setText(
            f"{len(update.snapshot.connections)} socket(s) · {len(update.hosts)} remote host(s) · "
            f"{len(update.events)} new event(s)"
        )

        connection_rows = []
        for connection in update.snapshot.connections:
            remote = connection.hostname or connection.remote_ip or "—"
            connection_rows.append(
                [
                    connection.process_name,
                    str(connection.pid or "—"),
                    remote,
                    str(connection.remote_port or connection.local_port or "—"),
                    connection.protocol,
                    connection.status,
                    connection.scope.value,
                    connection.adapter,
                ]
            )
        self._set_rows(self.connection_table, connection_rows)

        self._set_rows(
            self.process_table,
            [
                [
                    item.process_name,
                    str(item.pid or "—"),
                    str(item.connection_count),
                    str(item.external_connections),
                    str(len(item.remote_hosts)),
                    ", ".join(item.protocols),
                ]
                for item in update.processes
            ],
        )
        self._set_rows(
            self.host_table,
            [
                [
                    item.ip,
                    item.hostname or "—",
                    item.asn or "—",
                    item.prefix or "—",
                    item.scope.value,
                    str(item.connection_count),
                    ", ".join(str(port) for port in item.ports) or "—",
                    ", ".join(item.processes),
                    item.known_asset_label or "—",
                ]
                for item in update.hosts
            ],
        )
        self._set_rows(
            self.history_table,
            [
                [
                    _format_time(item.timestamp),
                    _format_rate(item.rx_bps),
                    _format_rate(item.tx_bps),
                    str(item.connections),
                    str(item.external_connections),
                    str(item.remote_hosts),
                ]
                for item in update.history[-120:]
            ],
        )

        for event in update.events:
            self.alert_rows.insert(
                0,
                [
                    _format_time(event.timestamp),
                    event.severity.value,
                    event.kind,
                    event.description,
                ],
            )
        del self.alert_rows[500:]
        self._set_rows(self.alert_table, self.alert_rows)

    def _sync_pcap_buttons(self) -> None:
        busy = self.pcap_worker is not None
        available = self.capture.available
        self.pcap_start_button.setEnabled(available and not self.capture.active and not busy)
        self.pcap_stop_button.setEnabled(available and self.capture.active and not busy)
        if not available:
            self.pcap_start_button.setToolTip("pktmon is unavailable on this system.")

    def start_pcap(self) -> None:
        if self.pcap_worker is not None:
            return
        worker = Worker(_start_pcap, self.capture, parent=self)
        worker.result.connect(self._pcap_started)
        worker.error.connect(self._pcap_failed)
        worker.finished.connect(self._pcap_worker_finished)
        self.pcap_worker = worker
        self._sync_pcap_buttons()
        self.start_managed_worker(worker, cancel=worker.cancel)

    def stop_pcap(self) -> None:
        if self.pcap_worker is not None:
            return
        worker = Worker(_stop_pcap, self.capture, parent=self)
        worker.result.connect(self._pcap_stopped)
        worker.error.connect(self._pcap_failed)
        worker.finished.connect(self._pcap_worker_finished)
        self.pcap_worker = worker
        self._sync_pcap_buttons()
        self.start_managed_worker(worker, cancel=worker.cancel)

    def _pcap_started(self, path: object) -> None:
        self.status_label.setText(
            f"PCAP capture started through pktmon: {path}. Capture covers NIC traffic system-wide."
        )
        self._sync_pcap_buttons()

    def _pcap_stopped(self, result: PcapCaptureResult) -> None:
        self.status_label.setText(f"PCAPNG saved to {result.pcapng_path}")
        self._sync_pcap_buttons()

    def _pcap_failed(self, error: Exception) -> None:
        message = str(error)
        if isinstance(error, PacketCaptureError):
            message += " Run PythonKni elevated only if packet capture permissions are required."
        show_error(self, "Packet capture", message)
        self.status_label.setText(f"PCAP error: {error}")
        self._sync_pcap_buttons()

    def _pcap_worker_finished(self) -> None:
        self.pcap_worker = None
        self._sync_pcap_buttons()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self.capture.active and (self.pcap_worker is None or not self.pcap_worker.isRunning()):
            try:
                self.capture.stop()
            except PacketCaptureError:
                pass
        super().closeEvent(event)
