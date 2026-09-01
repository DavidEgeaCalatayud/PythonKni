from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .comparison import SnapshotReportError, load_network_report


@dataclass(frozen=True, slots=True)
class ScoreHistoryPoint:
    generated_at: datetime
    generated_at_text: str
    source: Path
    schema_version: int
    score: int
    score_delta: int | None
    total_devices: int
    high_risk: int
    medium_risk: int
    low_risk: int
    unknown_devices: int
    findings: tuple[str, ...]
    findings_added: tuple[str, ...]
    findings_resolved: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScoreHistory:
    scope: str
    points: tuple[ScoreHistoryPoint, ...]

    @property
    def first_score(self) -> int:
        return self.points[0].score

    @property
    def latest_score(self) -> int:
        return self.points[-1].score

    @property
    def total_delta(self) -> int:
        return self.latest_score - self.first_score

    @property
    def lowest_score(self) -> int:
        return min(point.score for point in self.points)

    @property
    def highest_score(self) -> int:
        return max(point.score for point in self.points)


def _parse_generated_at(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise SnapshotReportError("generated_at must include a timezone.")
    return parsed


def build_score_history(
    snapshots: list[tuple[Path, dict]] | tuple[tuple[Path, dict], ...],
) -> ScoreHistory:
    if len(snapshots) < 2:
        raise SnapshotReportError("Security Score History requires at least two snapshots.")

    normalized: list[tuple[datetime, str, Path, dict]] = []
    scopes: set[str] = set()
    timestamps: set[datetime] = set()
    for source, report in snapshots:
        generated_at_text = str(report["generated_at"])
        generated_at = _parse_generated_at(generated_at_text)
        if generated_at in timestamps:
            raise SnapshotReportError(
                f"Duplicate snapshot generated_at timestamp: {generated_at_text}."
            )
        timestamps.add(generated_at)
        scopes.add(str(report["scope"]))
        normalized.append((generated_at, generated_at_text, Path(source), report))

    if len(scopes) != 1:
        raise SnapshotReportError("All Security Score History snapshots must use the same scope.")

    normalized.sort(key=lambda item: (item[0], str(item[2])))
    points: list[ScoreHistoryPoint] = []
    previous_score: int | None = None
    previous_findings: set[str] = set()
    for generated_at, generated_at_text, source, report in normalized:
        score = report["security_score"]
        findings = tuple(str(item) for item in score.get("findings", []))
        current_findings = set(findings)
        points.append(
            ScoreHistoryPoint(
                generated_at=generated_at,
                generated_at_text=generated_at_text,
                source=source,
                schema_version=int(report["schema_version"]),
                score=int(score["score"]),
                score_delta=None
                if previous_score is None
                else int(score["score"]) - previous_score,
                total_devices=int(score.get("total_devices", 0)),
                high_risk=int(score.get("high_risk", 0)),
                medium_risk=int(score.get("medium_risk", 0)),
                low_risk=int(score.get("low_risk", 0)),
                unknown_devices=int(score.get("unknown_devices", 0)),
                findings=findings,
                findings_added=tuple(sorted(current_findings - previous_findings))
                if points
                else (),
                findings_resolved=tuple(sorted(previous_findings - current_findings))
                if points
                else (),
            )
        )
        previous_score = int(score["score"])
        previous_findings = current_findings

    return ScoreHistory(scope=scopes.pop(), points=tuple(points))


def load_score_history(paths: list[str | Path] | tuple[str | Path, ...]) -> ScoreHistory:
    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        try:
            key = path.resolve()
        except OSError:
            key = path.absolute()
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    if len(unique_paths) < 2:
        raise SnapshotReportError(
            "Select at least two distinct snapshots for Security Score History."
        )

    snapshots = [(path, load_network_report(path)) for path in unique_paths]
    return build_score_history(snapshots)


def format_score_history(history: ScoreHistory) -> str:
    lines = [
        f"Scope: {history.scope}",
        f"Snapshots: {len(history.points)}",
        f"Score: {history.first_score} → {history.latest_score} ({history.total_delta:+d})",
        f"Range: {history.lowest_score}–{history.highest_score}",
        "",
    ]
    for point in history.points:
        delta = "baseline" if point.score_delta is None else f"{point.score_delta:+d}"
        lines.append(
            f"{point.generated_at_text}  ·  {point.score}/100 ({delta})  ·  "
            f"devices {point.total_devices}  ·  H/M/L {point.high_risk}/{point.medium_risk}/{point.low_risk}"
        )
        if point.findings_added:
            lines.append("  New findings: " + " | ".join(point.findings_added))
        if point.findings_resolved:
            lines.append("  Resolved findings: " + " | ".join(point.findings_resolved))
    return "\n".join(lines)
