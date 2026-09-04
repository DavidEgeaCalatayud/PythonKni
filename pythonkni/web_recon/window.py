from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.ui_feedback import show_error, show_warning
from tools.worker import Worker

from .models import ReconProgress, ReconReport
from .service import normalize_target, run_recon


def _run(
    worker: Worker,
    target: str,
    external: bool,
    active: bool,
    nerva: bool,
) -> ReconReport:
    return run_recon(
        target,
        include_external_sources=external,
        include_active_discovery=active,
        include_nerva=nerva,
        stop_event=worker.cancel_event,
        on_progress=worker.report_progress,
    )


class Tool(BaseTool):
    name = "Web Recon Auditor"
    description = (
        "Audita DNS, TLS, seguridad HTTP y superficie web de un objetivo explícito."
    )
    category = "Red"

    def setup_ui(self) -> None:
        self.setWindowTitle(self.name)
        self.setGeometry(120, 70, 1180, 780)
        self.worker: Worker | None = None
        self.report: ReconReport | None = None

        root = QWidget()
        layout = QVBoxLayout(root)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Target:"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("https://example.com")
        controls.addWidget(self.target_input, 3)
        self.run_button = QPushButton("Run reconnaissance")
        self.run_button.clicked.connect(self.start_recon)
        controls.addWidget(self.run_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_recon)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)

        options = QHBoxLayout()
        self.external_check = QCheckBox("External passive sources (CT / Wayback)")
        self.external_check.setChecked(False)
        options.addWidget(self.external_check)
        self.active_check = QCheckBox(
            "Active bounded discovery (crawl / paths / ports)"
        )
        self.active_check.setChecked(False)
        self.active_check.toggled.connect(self._sync_options)
        options.addWidget(self.active_check)
        self.nerva_check = QCheckBox("Nerva fingerprinting")
        self.nerva_check.setChecked(True)
        options.addWidget(self.nerva_check)
        options.addStretch(1)
        layout.addLayout(options)

        self.status_label = QLabel(
            "Un objetivo por ejecución. Sin explotación, credenciales, fuzzing masivo "
            "ni ampliación silenciosa del scope."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.overview = QTextEdit()
        self.overview.setReadOnly(True)
        self.dns_table = self._table(["Type", "Name", "Value", "Preference"])
        self.whois_table = self._table(["Property", "Value"])
        self.tls_table = self._table(["Property", "Value"])
        self.http_table = self._table(["Check", "Result", "Observed"])
        self.subdomain_table = self._table(["Hostname", "Addresses", "Source"])
        self.tech_table = self._table(["Technology", "Confidence", "Evidence"])
        self.urls_table = self._table(["URL", "Source", "Status"])
        self.ports_table = self._table(["Port", "Service", "Nerva fingerprint"])
        self.findings_table = self._table(
            ["Severity", "Category", "Finding", "Evidence"]
        )
        for widget, label in (
            (self.overview, "Overview"),
            (self.dns_table, "DNS"),
            (self.whois_table, "WHOIS"),
            (self.tls_table, "TLS"),
            (self.http_table, "HTTP Security"),
            (self.subdomain_table, "Subdomains"),
            (self.tech_table, "Technology"),
            (self.urls_table, "Crawl / Archive"),
            (self.ports_table, "Ports"),
            (self.findings_table, "Findings"),
        ):
            self.tabs.addTab(widget, label)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self._sync_options()

    def _table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return table

    def _sync_options(self) -> None:
        self.nerva_check.setEnabled(
            self.active_check.isChecked() and self.run_button.isEnabled()
        )

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.target_input.setEnabled(not running)
        self.external_check.setEnabled(not running)
        self.active_check.setEnabled(not running)
        self.nerva_check.setEnabled(not running and self.active_check.isChecked())

    def start_recon(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        target = self.target_input.text().strip()
        try:
            normalize_target(target)
        except ValueError as error:
            show_warning(self, self.name, str(error))
            return
        self._clear()
        self._set_running(True)
        worker = Worker(
            _run,
            target,
            self.external_check.isChecked(),
            self.active_check.isChecked(),
            self.nerva_check.isChecked(),
            parent=self,
        )
        worker.progress.connect(self._progress)
        worker.result.connect(self._finished)
        worker.error.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(self._worker_finished)
        self.worker = worker
        self.start_managed_worker(worker, cancel=worker.cancel)

    def stop_recon(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.stop_button.setEnabled(False)
            self.status_label.setText("Cancelando reconocimiento de forma cooperativa...")
            self.worker.cancel()

    def _progress(self, progress: ReconProgress) -> None:
        self.status_label.setText(progress.message)

    def _failed(self, error: Exception) -> None:
        show_error(self, self.name, str(error))
        self.status_label.setText(f"Reconnaissance failed: {error}")

    def _cancelled(self) -> None:
        self.status_label.setText("Reconnaissance cancelled.")

    def _worker_finished(self) -> None:
        self.worker = None
        self._set_running(False)

    def _clear(self) -> None:
        self.overview.clear()
        for table in (
            self.dns_table,
            self.whois_table,
            self.tls_table,
            self.http_table,
            self.subdomain_table,
            self.tech_table,
            self.urls_table,
            self.ports_table,
            self.findings_table,
        ):
            table.setRowCount(0)

    def _rows(self, table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))

    def _finished(self, report: ReconReport) -> None:
        self.report = report
        self.status_label.setText(
            f"Recon complete · {len(report.addresses)} IP(s) · "
            f"{len(report.ports)} open port(s) · {len(report.findings)} finding(s)."
        )
        self.overview.setPlainText(
            "\n".join(
                [
                    f"Target: {report.target.url}",
                    f"Host: {report.target.hostname}",
                    f"Addresses: {', '.join(report.addresses) or 'none'}",
                    f"HTTP: {report.http.status_code or 'unavailable'} "
                    f"{report.http.final_url}",
                    f"TLS: {report.tls.version or report.tls.error or 'not checked'}",
                    f"WHOIS registrar: {report.whois.registrar or 'not available'}",
                    f"SPF: {'yes' if report.dns.spf else 'not observed'}",
                    f"DMARC: {report.dns.dmarc_policy or 'not observed'}",
                    f"DNSSEC publication: {report.dns.dnssec_published}",
                    f"Subdomains: {len(report.subdomains)}",
                    f"Discovered URLs: {len(report.discovered_urls)}",
                ]
            )
        )
        self._rows(
            self.dns_table,
            [
                [
                    item.record_type,
                    item.name,
                    item.value,
                    str(item.preference or ""),
                ]
                for item in report.dns.records
            ],
        )
        self._rows(
            self.whois_table,
            [
                ["Registrar", report.whois.registrar],
                ["Created", report.whois.created],
                ["Expires", report.whois.expires],
                ["Nameservers", ", ".join(report.whois.nameservers)],
                ["Statuses", ", ".join(report.whois.statuses)],
                ["WHOIS server", report.whois.referral_server],
                ["Error", report.whois.error],
            ],
        )
        self._rows(
            self.tls_table,
            [
                ["Version", report.tls.version],
                ["Cipher", report.tls.cipher],
                ["Subject", report.tls.subject],
                ["Issuer", report.tls.issuer],
                ["Expires", report.tls.not_after],
                [
                    "Days remaining",
                    str(
                        report.tls.expires_in_days
                        if report.tls.expires_in_days is not None
                        else ""
                    ),
                ],
                ["SANs", ", ".join(report.tls.sans)],
                ["Error", report.tls.error],
            ],
        )
        self._rows(
            self.http_table,
            [
                [item.name, "PASS" if item.passed else "WARN", item.observed]
                for item in report.http.checks
            ],
        )
        self._rows(
            self.subdomain_table,
            [
                [item.hostname, ", ".join(item.addresses), item.source]
                for item in report.subdomains
            ],
        )
        self._rows(
            self.tech_table,
            [
                [item.name, item.confidence, item.evidence]
                for item in report.technologies
            ],
        )
        self._rows(
            self.urls_table,
            [
                [item.url, item.source, str(item.status_code or "")]
                for item in report.discovered_urls
            ],
        )
        self._rows(
            self.ports_table,
            [
                [str(item.port), item.service, item.fingerprint or "—"]
                for item in report.ports
            ],
        )
        self._rows(
            self.findings_table,
            [
                [item.severity.value, item.category, item.title, item.evidence]
                for item in report.findings
            ],
        )
