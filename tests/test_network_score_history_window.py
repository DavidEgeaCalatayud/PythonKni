from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pythonkni.network_intelligence import history_window, reporting_window
from pythonkni.network_intelligence import window as base_window
from pythonkni.network_intelligence.history import ScoreHistory, ScoreHistoryPoint

SCOPE = "192.168.1.0/24"
NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


def point(
    name: str,
    score: int,
    *,
    delta: int | None,
    added: tuple[str, ...] = (),
    resolved: tuple[str, ...] = (),
) -> ScoreHistoryPoint:
    return ScoreHistoryPoint(
        generated_at=NOW,
        generated_at_text=f"2026-09-01T0{8 if delta is None else 9}:00:00Z",
        source=Path(name),
        schema_version=2,
        score=score,
        score_delta=delta,
        total_devices=3,
        high_risk=0,
        medium_risk=1,
        low_risk=2,
        unknown_devices=0,
        findings=("finding",),
        findings_added=added,
        findings_resolved=resolved,
    )


def history() -> ScoreHistory:
    return ScoreHistory(
        scope=SCOPE,
        points=(
            point("first.json", 88, delta=None),
            point("second.json", 94, delta=6, added=("new",), resolved=("old",)),
        ),
    )


def make_tool(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(base_window, "_default_scope", lambda: SCOPE)
    monkeypatch.setattr(base_window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    monkeypatch.setattr(reporting_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(
        reporting_window,
        "NETWORK_INTELLIGENCE_REPORTS_DIR",
        tmp_path / "reports",
    )
    tool = history_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_history_composition_adds_action_and_tracks_running_state(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)

    assert tool.score_history_button.text() == "Security Score History"
    assert tool.score_history_button.isEnabled()
    tool._set_running(True)
    assert not tool.score_history_button.isEnabled()
    tool._set_running(False)
    assert tool.score_history_button.isEnabled()


def test_history_dialog_renders_points_and_selected_details(qtbot):
    dialog = history_window.ScoreHistoryDialog(history())
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 2
    assert "88 → 94 (+6)" in dialog.summary_label.text()
    assert "second.json" in dialog.detail_area.toPlainText()
    assert "New since previous snapshot" in dialog.detail_area.toPlainText()
    assert "Resolved since previous snapshot" in dialog.detail_area.toPlainText()

    dialog.table.selectRow(0)
    assert "first.json" in dialog.detail_area.toPlainText()
    assert "Baseline" in dialog.detail_area.toPlainText()


def test_history_action_cancel_and_single_selection_are_non_destructive(
    qtbot, monkeypatch, tmp_path
):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    warnings = []
    monkeypatch.setattr(history_window, "show_warning", lambda *args, **kwargs: warnings.append(args))

    monkeypatch.setattr(
        history_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([], ""),
    )
    tool.open_score_history()
    assert not warnings

    monkeypatch.setattr(
        history_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(tmp_path / "one.json")], ""),
    )
    tool.open_score_history()
    assert warnings
    assert "al menos dos" in warnings[0][2]


def test_history_action_uses_saved_snapshots_only_and_updates_status(
    qtbot, monkeypatch, tmp_path
):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    selected = [str(tmp_path / "one.json"), str(tmp_path / "two.json")]
    monkeypatch.setattr(
        history_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (selected, "Network Intelligence snapshots (*.json *.zip)"),
    )
    loaded = []
    monkeypatch.setattr(
        history_window,
        "load_score_history",
        lambda paths: loaded.append(tuple(paths)) or history(),
    )

    class FakeDialog:
        def __init__(self, score_history, parent=None):
            assert score_history.latest_score == 94

        def exec_(self):
            return 0

    monkeypatch.setattr(history_window, "ScoreHistoryDialog", FakeDialog)
    monkeypatch.setattr(
        tool.inventory,
        "list_assets",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("live inventory must not be read")),
    )

    tool.open_score_history()

    assert loaded == [tuple(selected)]
    assert "88 → 94 (+6)" in tool.status_label.text()


def test_history_action_reports_loading_failure(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(
        history_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (["one.json", "two.json"], ""),
    )
    monkeypatch.setattr(
        history_window,
        "load_score_history",
        lambda paths: (_ for _ in ()).throw(ValueError("bad snapshot")),
    )
    errors = []
    monkeypatch.setattr(
        history_window,
        "show_error",
        lambda *args, **kwargs: errors.append((args, kwargs)),
    )

    tool.open_score_history()

    assert errors
    assert "No se pudo construir" in errors[0][0][2]
