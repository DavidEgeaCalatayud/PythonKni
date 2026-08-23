from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CleanResult:
    deleted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def add(self, other: "CleanResult") -> None:
        self.deleted += other.deleted
        self.failed += other.failed
        self.errors.extend(other.errors)


@dataclass(frozen=True)
class CleanTarget:
    label: str
    path: Path


@dataclass
class CleanPreview:
    targets: list[CleanTarget] = field(default_factory=list)
    items: int = 0
    bytes: int = 0
