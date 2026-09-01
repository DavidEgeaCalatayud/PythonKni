from __future__ import annotations

from pathlib import Path

from pythonkni.network_intelligence import comparison_window
from pythonkni.network_intelligence import reporting_window
from pythonkni.network_intelligence import window as base_window
from pythonkni.network_intelligence.comparison import (
    SnapshotAssetDelta,
    SnapshotComparison,
)

SCOPE = "192.168.1.0/24"


def comparison_result() -> SnapshotComparison:
    return SnapshotComparison(
        scope=SCOPE,
        baseline_generated_at="2026-09-01T08:00:00Z",
        current_generated_at="2026-09-01T09:00:00Z",
        baseline_schema_version=2,
        current_schema_version=2,
        added_assets=(
            SnapshotAssetDelta(
                asset_id="mac:AA:BB:CC:DD:EE:02",
                change="added",
                before_label="",
                after_label="camera.local · Camera · 192.168.1.20",
            ),
        ),
        removed_assets=(),
        changed_assets=(
            SnapshotAssetDelta(
                asset_id="mac:AA:BB:CC:DD:EE:01",
                change="changed",
                before_label="nas.local · NAS · 192.168.1.10",
                after_label="nas.local · NAS · 192.168.1.10",
                details=("Risk: LOW → MEDIUM",),
            ),
        ),
        unchanged_assets=0,
        added_relationships=(),
        removed_relationships=(),
        changed_relationships=(),
        unchanged_relationships=0,
        security_score_before=92,
        security_score_after=84,
        findings_added=("New exposure",),
        findings_removed=(),
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
    instance = comparison_window.Tool()
    qtbot.addWidget(instance)
    return instance


def test_comparison_composition_adds_action_and_tracks_running_state(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)

    assert tool.compare_snapshots_button.text() == "Compare saved snapshots"
    assert tool.compare_snapshots_button.isEnabled()

    tool._set_running(True)
    assert not tool.compare_snapshots_button.isEnabled()
    tool._set_running(False)
    assert tool.compare_snapshots_button.isEnabled()


def test_comparison_dialog_renders_human_readable_diff(qtbot):
    dialog = comparison_window.SnapshotComparisonDialog(comparison_result())
    qtbot.addWidget(dialog)

    text = dialog.text_area.toPlainText()
    assert "Network Intelligence Snapshot Comparison" in text
    assert "Security score: 92 → 84 (-8)" in text
    assert "camera.local" in text
    assert "Risk: LOW → MEDIUM" in text


def test_canceling_first_or_second_picker_does_not_load_reports(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    loaded = []
    monkeypatch.setattr(
        comparison_window,
        "load_network_report",
        lambda path: loaded.append(path) or {},
    )

    monkeypatch.setattr(tool, "_pick_snapshot", lambda _title: None)
    tool.compare_saved_snapshots()
    assert loaded == []

    paths = iter([tmp_path / "baseline.json", None])
    monkeypatch.setattr(tool, "_pick_snapshot", lambda _title: next(paths))
    tool.compare_saved_snapshots()
    assert loaded == []


def test_same_snapshot_warns_without_loading(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    selected = tmp_path / "snapshot.json"
    paths = iter([selected, selected])
    monkeypatch.setattr(tool, "_pick_snapshot", lambda _title: next(paths))
    warnings = []
    monkeypatch.setattr(
        comparison_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    monkeypatch.setattr(
        comparison_window,
        "load_network_report",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not load")),
    )

    tool.compare_saved_snapshots()

    assert warnings
    assert "dos snapshots distintos" in warnings[0][0][2]


def test_successful_comparison_uses_saved_reports_only_and_updates_status(
    qtbot, monkeypatch, tmp_path
):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.zip"
    paths = iter([baseline_path, current_path])
    monkeypatch.setattr(tool, "_pick_snapshot", lambda _title: next(paths))

    loaded = []
    reports = {
        baseline_path: {"source": "baseline"},
        current_path: {"source": "current"},
    }

    def fake_load(path):
        loaded.append(path)
        return reports[path]

    monkeypatch.setattr(comparison_window, "load_network_report", fake_load)
    compared = []

    def fake_compare(baseline, current):
        compared.append((baseline, current))
        return comparison_result()

    monkeypatch.setattr(comparison_window, "compare_network_reports", fake_compare)
    dialogs = []

    class FakeDialog:
        def __init__(self, result, parent):
            dialogs.append((result, parent))

        def exec_(self):
            dialogs.append("executed")

    monkeypatch.setattr(comparison_window, "SnapshotComparisonDialog", FakeDialog)
    monkeypatch.setattr(
        tool.inventory,
        "list_assets",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("live inventory must not be read")),
    )

    tool.compare_saved_snapshots()

    assert loaded == [baseline_path, current_path]
    assert compared == [(reports[baseline_path], reports[current_path])]
    assert dialogs[-1] == "executed"
    assert "+1 / -0 / 1 activo(s) cambiado(s)" in tool.status_label.text()
    assert "92 → 84 (-8)" in tool.status_label.text()


def test_comparison_failure_is_reported(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    paths = iter([tmp_path / "baseline.json", tmp_path / "current.json"])
    monkeypatch.setattr(tool, "_pick_snapshot", lambda _title: next(paths))
    monkeypatch.setattr(
        comparison_window,
        "load_network_report",
        lambda *_args: (_ for _ in ()).throw(ValueError("broken snapshot")),
    )
    errors = []
    monkeypatch.setattr(
        comparison_window,
        "show_error",
        lambda *args, **kwargs: errors.append((args, kwargs)),
    )

    tool.compare_saved_snapshots()

    assert errors
    assert "No se pudieron comparar" in errors[0][0][2]
    assert isinstance(errors[0][1]["error"], ValueError)


def test_picker_accepts_json_and_zip(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    selected = tmp_path / "snapshot.zip"
    calls = []

    def fake_picker(*args):
        calls.append(args)
        return str(selected), "Network Intelligence snapshots (*.json *.zip)"

    monkeypatch.setattr(comparison_window.QFileDialog, "getOpenFileName", fake_picker)

    assert tool._pick_snapshot("Select baseline snapshot") == Path(selected)
    assert "*.json *.zip" in calls[0][3]
