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
                    source_port TEXT NOT NULL DEFAULT '',
                    target_port TEXT NOT NULL DEFAULT '',
                    protocol TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(scope, source_id, target_id, kind)
                );

                CREATE INDEX IF NOT EXISTS idx_network_relationships_scope_confidence
                    ON network_relationships(scope, confidence);
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(network_relationships)")
            }
            migrations = {
                "source_port": "ALTER TABLE network_relationships ADD COLUMN source_port TEXT NOT NULL DEFAULT ''",
                "target_port": "ALTER TABLE network_relationships ADD COLUMN target_port TEXT NOT NULL DEFAULT ''",
                "protocol": "ALTER TABLE network_relationships ADD COLUMN protocol TEXT NOT NULL DEFAULT ''",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            connection.commit()

    @staticmethod
    def _validate_scope(scope: str, relationship: NetworkRelationship) -> None:
        if relationship.scope != scope:
            raise ValueError("Relationship scope does not match the requested snapshot scope.")

    def _insert_many(self, connection, scope: str, relationships) -> None:
        for relationship in relationships:
            self._validate_scope(scope, relationship)
            connection.execute(
                """
                INSERT OR REPLACE INTO network_relationships(
                    scope,
                    source_id,
                    target_id,
                    kind,
                    confidence,
                    evidence_json,
                    observed_at,
                    source_port,
                    target_port,
                    protocol
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    relationship.source_port,
                    relationship.target_port,
                    relationship.protocol,
                ),
            )

    def replace(
        self,
        scope: str,
        relationships: tuple[NetworkRelationship, ...] | list[NetworkRelationship],
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM network_relationships WHERE scope = ?", (scope,))
            self._insert_many(connection, scope, relationships)
            connection.commit()

    def replace_logical(
        self,
        scope: str,
        relationships: tuple[NetworkRelationship, ...] | list[NetworkRelationship],
    ) -> None:
        if any(item.kind == RelationshipKind.PHYSICAL_LINK for item in relationships):
            raise ValueError("replace_logical accepts logical relationships only.")
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM network_relationships WHERE scope = ? AND kind <> ?",
                (scope, RelationshipKind.PHYSICAL_LINK.value),
            )
            self._insert_many(connection, scope, relationships)
            connection.commit()

    def replace_physical(
        self,
        scope: str,
        relationships: tuple[NetworkRelationship, ...] | list[NetworkRelationship],
    ) -> None:
        if any(item.kind != RelationshipKind.PHYSICAL_LINK for item in relationships):
            raise ValueError("replace_physical accepts PHYSICAL_LINK relationships only.")
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM network_relationships WHERE scope = ? AND kind = ?",
                (scope, RelationshipKind.PHYSICAL_LINK.value),
            )
            self._insert_many(connection, scope, relationships)
            connection.commit()

    def list(self, *, scope: str) -> list[NetworkRelationship]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    scope,
                    source_id,
                    target_id,
                    kind,
                    confidence,
                    evidence_json,
                    observed_at,
                    source_port,
                    target_port,
                    protocol
                FROM network_relationships
                WHERE scope = ?
                ORDER BY
                    CASE confidence
                        WHEN 'CONFIRMED' THEN 0
                        WHEN 'INFERRED' THEN 1
                        ELSE 2
                    END,
                    CASE kind
                        WHEN 'Physical link' THEN 0
                        ELSE 1
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
                    source_port=row["source_port"] or "",
                    target_port=row["target_port"] or "",
                    protocol=row["protocol"] or "",
                )
            )
        return relationships
