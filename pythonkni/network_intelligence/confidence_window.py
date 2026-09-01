from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidgetItem

from .classification import classification_confidence_level
from .models import AssetRecord
from .reporting_window import Tool as ReportingTool
from .window import _asset_profile_text, _format_time


def _confidence_text(asset: AssetRecord) -> str:
    level = classification_confidence_level(asset.classification_confidence).value
    return f"{asset.classification_confidence}/100 · {level}"


def _confidence_profile_text(asset: AssetRecord) -> str:
    lines = [
        _asset_profile_text(asset),
        "",
        "Classification confidence",
        _confidence_text(asset),
        "",
        "Weighted classification signals",
    ]
    if not asset.classification_signals:
        lines.append("No structured classification signals are persisted yet.")
    else:
        for signal in asset.classification_signals:
            marker = "✓" if signal.matched else "✗"
            lines.append(f"{marker} {signal.label}  +{signal.contribution}  —  {signal.evidence}")
    lines.extend(
        [
            "",
            "Classification confidence is independent from security risk.",
        ]
    )
    return "\n".join(lines)


class Tool(ReportingTool):
    """Network Intelligence window with explainable classification confidence."""

    def setup_ui(self) -> None:
        super().setup_ui()
        self.table.insertColumn(4)
        self.table.setHorizontalHeaderItem(4, QTableWidgetItem("Confidence"))
        self.refresh_inventory()

    def _write_asset_row(self, row: int, asset: AssetRecord) -> None:
        if self.table.columnCount() < 10:
            super()._write_asset_row(row, asset)
            return
        values = (
            asset.ip,
            asset.hostname,
            asset.vendor,
            asset.kind.value,
            _confidence_text(asset),
            " ".join(asset.services),
            asset.risk.value,
            "Online" if asset.is_online else "Offline",
            _format_time(asset.first_seen),
            _format_time(asset.last_seen),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setData(Qt.UserRole, asset.asset_id)
            self.table.setItem(row, column, item)

    def _selection_changed(self, *_args) -> None:
        super()._selection_changed(*_args)
        asset = self._selected_asset()
        if asset is not None:
            self.detail_area.setPlainText(_confidence_profile_text(asset))

    def _topology_asset_selected(self, asset_id: str) -> None:
        super()._topology_asset_selected(asset_id)
        asset = next((item for item in self.assets if item.asset_id == asset_id), None)
        if asset is not None:
            self.topology_detail.setPlainText(_confidence_profile_text(asset))
