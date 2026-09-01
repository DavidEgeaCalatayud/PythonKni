from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .models import NetworkRelationship, RelationshipConfidence, RelationshipKind


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class RelationshipStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS network_relationships (
                    scope TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY(scope, source_id, target_id, kind)
                );

                CREATE INDEX IF NOT EXISTS idx_network_relationships_scope_confidence
                    ON network_relationships(scope, confidence);
                """
            )
            connection.commit()

    def replace(
        self,
        scope: str,
        relationships: tuple[NetworkRelationship, ...] | list[NetworkRelationship],
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM network_relationships WHERE scope = ?", (scope,))
            for relationship in relationships:
                if relationship.scope != scope:
                    raise ValueError(
                        "Relationship scope does not match the requested snapshot scope."
                    )
                connection.execute(
                    """
                    INSERT INTO network_relationships(
                        scope, source_id, target_id, kind, confidence, evidence_json, observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relationship.scope,
                        relationship.source_id,
                        relationship.target_id,
                        relationship.kind.value,
                        relationship.confidence.value,
                        json.dumps(
                            list(relationship.evidence),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        _iso(relationship.observed_at),
                    ),
                )
            connection.commit()

    def list(self, *, scope: str) -> list[NetworkRelationship]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT scope, source_id, target_id, kind, confidence, evidence_json, observed_at
                FROM network_relationships
                WHERE scope = ?
                ORDER BY
                    CASE confidence
                        WHEN 'CONFIRMED' THEN 0
                        WHEN 'INFERRED' THEN 1
                        ELSE 2
                    END,
                    source_id,
                    target_id,
                    kind
                """,
                (scope,),
            ).fetchall()
        relationships = []
        for row in rows:
            try:
                evidence = tuple(str(item) for item in json.loads(row["evidence_json"] or "[]"))
            except (json.JSONDecodeError, TypeError):
                evidence = ()
            relationships.append(
                NetworkRelationship(
                    scope=row["scope"],
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    kind=RelationshipKind(row["kind"]),
                    confidence=RelationshipConfidence(row["confidence"]),
                    evidence=evidence,
                    observed_at=_parse_datetime(row["observed_at"]),
                )
            )
        return relationships
