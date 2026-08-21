from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReportData:
    generated_at: str
    system_rows: list[tuple[str, str]]
    disk_rows: list[tuple[str, str, str, str]]
    network_rows: list[tuple[str, str]]
    top_cpu: list[tuple[int, str, float, float]]
    top_memory: list[tuple[int, str, float, float]]
    temp_summary: list[tuple[str, str]]
    event_summary: list[tuple[str, str, str, str, str, str]] = field(default_factory=list)
