from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QLabel, QTextEdit, QVBoxLayout

from .auditors import build_device_audit
from .models import AssetRecord


class DeviceAuditorDialog(QDialog):
    def __init__(self, asset: AssetRecord, parent=None):
        super().__init__(parent)
        self.asset = asset
        report = build_device_audit(asset)
        self.setWindowTitle(report.title)
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{asset.ip} · {asset.vendor} · Risk {report.risk.value}"))

        area = QTextEdit()
        area.setReadOnly(True)
        lines = [
            report.title,
            "",
            f"Asset: {asset.asset_id}",
            f"Hostname: {asset.hostname}",
            f"MAC: {asset.mac}",
            f"Services: {', '.join(asset.services) or 'None detected'}",
            "",
            "Findings",
        ]
        for finding in report.findings:
            lines.extend(
                [
                    f"[{finding.severity.value}] {finding.title}",
                    f"Evidence: {finding.evidence}",
                    f"Recommendation: {finding.recommendation}",
                    "",
                ]
            )
        area.setPlainText("\n".join(lines).rstrip())
        layout.addWidget(area)
