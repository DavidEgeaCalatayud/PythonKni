from __future__ import annotations

import json
from pathlib import Path

import pytest

from pythonkni.network_intelligence.comparison import SnapshotReportError
from pythonkni.network_intelligence.history import (
    build_score_history,
    format_score_history,
    load_score_history,
)

SCOPE = "192.168.1.0/24"


def snapshot(
    generated_at: str,
    score: int,
    *,
    scope: str = SCOPE,
    findings: tuple[str, ...] = (),
    total_devices: int = 3,
    high: int = 0,
    medium: int = 1,
    low: int = 2,
    unknown: int = 0,
) -> dict:
    return {
        "schema_version": 2,
        "generated_at": generated_at,
        "scope": scope,
        "summary": {},
        "security_score": {
            "score": score,
            "total_devices": total_devices,
            "unknown_devices": unknown,
            "high_risk": high,
            "medium_risk": medium,
            "low_risk": low,
            "findings": list(findings),
        },
        "assets": [],
        "relationships": [],
        "timeline": [],
    }


def test_history_sorts_chronologically_and_tracks_score_and_findings():
    history = build_score_history(
        [
            (Path("new.json"), snapshot("2026-09-01T10:00:00Z", 91, findings=("B", "C"))),
            (Path("old.json"), snapshot("2026-09-01T08:00:00Z", 80, findings=("A", "B"))),
            (Path("mid.json"), snapshot("2026-09-01T09:00:00Z", 75, findings=("B",))),
        ]
    )

    assert history.scope == SCOPE
    assert [point.source.name for point in history.points] == ["old.json", "mid.json", "new.json"]
    assert [point.score for point in history.points] == [80, 75, 91]
    assert [point.score_delta for point in history.points] == [None, -5, 16]
    assert history.total_delta == 11
    assert history.lowest_score == 75
    assert history.highest_score == 91
    assert history.points[1].findings_resolved == ("A",)
    assert history.points[1].findings_added == ()
    assert history.points[2].findings_added == ("C",)
    assert history.points[2].findings_resolved == ()


def test_history_requires_two_snapshots_same_scope_and_unique_timestamps():
    with pytest.raises(SnapshotReportError, match="at least two"):
        build_score_history([(Path("one.json"), snapshot("2026-09-01T08:00:00Z", 90))])

    with pytest.raises(SnapshotReportError, match="same scope"):
        build_score_history(
            [
                (Path("a.json"), snapshot("2026-09-01T08:00:00Z", 90)),
                (
                    Path("b.json"),
                    snapshot("2026-09-01T09:00:00Z", 91, scope="192.168.2.0/24"),
                ),
            ]
        )

    with pytest.raises(SnapshotReportError, match="Duplicate snapshot generated_at"):
        build_score_history(
            [
                (Path("a.json"), snapshot("2026-09-01T08:00:00Z", 90)),
                (Path("b.json"), snapshot("2026-09-01T08:00:00+00:00", 91)),
            ]
        )


def test_load_history_deduplicates_paths_and_uses_validated_reports(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(snapshot("2026-09-01T08:00:00Z", 88)), encoding="utf-8")
    second.write_text(json.dumps(snapshot("2026-09-01T09:00:00Z", 92)), encoding="utf-8")

    history = load_score_history([first, first, second])

    assert len(history.points) == 2
    assert history.first_score == 88
    assert history.latest_score == 92

    with pytest.raises(SnapshotReportError, match="at least two distinct"):
        load_score_history([first, first])


def test_format_history_is_compact_and_explainable():
    history = build_score_history(
        [
            (Path("a.json"), snapshot("2026-09-01T08:00:00Z", 90, findings=("A",))),
            (Path("b.json"), snapshot("2026-09-01T09:00:00Z", 95, findings=("B",))),
        ]
    )

    text = format_score_history(history)

    assert "Score: 90 → 95 (+5)" in text
    assert "New findings: B" in text
    assert "Resolved findings: A" in text
