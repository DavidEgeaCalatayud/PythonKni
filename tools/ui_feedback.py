from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PyQt5.QtWidgets import QMessageBox, QWidget


class FeedbackSeverity(Enum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class UserFeedback:
    """Structured user-facing feedback rendered through a QMessageBox."""

    severity: FeedbackSeverity
    title: str
    message: str
    details: str | None = None

    @classmethod
    def information(cls, title: str, message: str, *, details: str | None = None):
        return cls(FeedbackSeverity.INFORMATION, title, message, details)

    @classmethod
    def warning(cls, title: str, message: str, *, details: str | None = None):
        return cls(FeedbackSeverity.WARNING, title, message, details)

    @classmethod
    def error(cls, title: str, message: str, *, details: str | None = None):
        return cls(FeedbackSeverity.ERROR, title, message, details)


def format_technical_details(error: BaseException) -> str:
    """Return a stable technical representation without leaking it into the summary."""
    error_type = type(error).__name__
    text = str(error).strip()
    return f"{error_type}: {text}" if text else error_type


def build_feedback_box(parent: QWidget | None, feedback: UserFeedback) -> QMessageBox:
    """Build a message box so presentation can be tested without opening a modal dialog."""
    box = QMessageBox(parent)
    icon_by_severity = {
        FeedbackSeverity.INFORMATION: QMessageBox.Information,
        FeedbackSeverity.WARNING: QMessageBox.Warning,
        FeedbackSeverity.ERROR: QMessageBox.Critical,
    }
    box.setIcon(icon_by_severity[feedback.severity])
    box.setWindowTitle(feedback.title)
    box.setText(feedback.message)
    if feedback.details:
        box.setDetailedText(feedback.details)
    box.setStandardButtons(QMessageBox.Ok)
    return box


def show_feedback(parent: QWidget | None, feedback: UserFeedback) -> int:
    """Render structured feedback modally."""
    return build_feedback_box(parent, feedback).exec_()


def show_error(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    error: BaseException | None = None,
    details: str | None = None,
) -> int:
    """Show an actionable error summary with optional expandable technical details."""
    technical_details = details
    if technical_details is None and error is not None:
        technical_details = format_technical_details(error)
    return show_feedback(
        parent,
        UserFeedback.error(title, message, details=technical_details),
    )


def show_warning(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    details: str | None = None,
) -> int:
    """Show a warning with optional expandable diagnostics."""
    return show_feedback(
        parent,
        UserFeedback.warning(title, message, details=details),
    )
