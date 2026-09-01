from __future__ import annotations

from .comparison_window import Tool as ComparisonTool
from .score import calculate_security_score


class Tool(ComparisonTool):
    """Network Intelligence window with topology-aware security scoring."""

    def refresh_inventory(self, *, keep_status: bool = False) -> None:
        super().refresh_inventory(keep_status=keep_status)
        if not hasattr(self, "score_label") or not hasattr(self, "score_findings"):
            return

        score = calculate_security_score(
            self.assets,
            relationships=tuple(self.relationships),
        )
        self.score_label.setText(
            f"Network Security Score: {score.score}/100  ·  Devices {score.total_devices}  ·  "
            f"Unknown {score.unknown_devices}  ·  High {score.high_risk}  ·  "
            f"Medium {score.medium_risk}  ·  Low {score.low_risk}"
        )
        self.score_findings.setPlainText("\n".join(f"• {item}" for item in score.findings))
