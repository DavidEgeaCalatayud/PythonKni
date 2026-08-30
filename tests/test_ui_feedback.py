import pytest
from PyQt5.QtWidgets import QMessageBox

from tools.ui_feedback import (
    FeedbackSeverity,
    UserFeedback,
    build_feedback_box,
    format_technical_details,
)


@pytest.mark.parametrize(
    ("severity", "expected_icon"),
    [
        (FeedbackSeverity.INFORMATION, QMessageBox.Information),
        (FeedbackSeverity.WARNING, QMessageBox.Warning),
        (FeedbackSeverity.ERROR, QMessageBox.Critical),
    ],
)
def test_feedback_box_maps_severity_and_keeps_details_expandable(qtbot, severity, expected_icon):
    feedback = UserFeedback(
        severity=severity,
        title="Operación fallida",
        message="No se pudo completar la operación.",
        details="OSError: disco lleno",
    )

    box = build_feedback_box(None, feedback)
    qtbot.addWidget(box)

    assert box.icon() == expected_icon
    assert box.windowTitle() == "Operación fallida"
    assert box.text() == "No se pudo completar la operación."
    assert box.detailedText() == "OSError: disco lleno"
    assert box.standardButtons() == QMessageBox.Ok


def test_feedback_box_omits_details_when_not_provided(qtbot):
    box = build_feedback_box(
        None,
        UserFeedback.warning("Aviso", "Revise la selección."),
    )
    qtbot.addWidget(box)

    assert box.detailedText() == ""


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OSError("disk full"), "OSError: disk full"),
        (ValueError(), "ValueError"),
    ],
)
def test_format_technical_details_is_stable(error, expected):
    assert format_technical_details(error) == expected
