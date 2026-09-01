from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _repoint_relationships(
    connection: sqlite3.Connection,
    *,
    old_id: str,
    new_id: str,
) -> None:
    if not _table_exists(connection, "network_relationships"):
        return

    # UPDATE OR IGNORE deliberately lets an already-existing canonical edge win.
    # Any row that could not be moved because of the relationship primary key is
    # removed below together with the obsolete identity.
    connection.execute(
        "UPDATE OR IGNORE network_relationships SET source_id = ? WHERE source_id = ?",
        (new_id, old_id),
    )
    connection.execute(
        "UPDATE OR IGNORE network_relationships SET target_id = ? WHERE target_id = ?",
        (new_id, old_id),
    )
    connection.execute(
        "DELETE FROM network_relationships WHERE source_id = ? OR target_id = ?",
        (old_id, old_id),
    )
    connection.execute(
        "DELETE FROM network_relationships WHERE source_id = target_id",
    )


def _deduplicate_new_device_event(
    connection: sqlite3.Connection,
    *,
    fallback_row: sqlite3.Row,
    canonical_row: sqlite3.Row,
) -> None:
    fallback_first = _instant(fallback_row["first_seen"])
    canonical_first = _instant(canonical_row["first_seen"])
    if fallback_first <= canonical_first:
        asset_id = canonical_row["asset_id"]
        created_at = canonical_row["first_seen"]
    else:
        asset_id = fallback_row["asset_id"]
        created_at = fallback_row["first_seen"]
    connection.execute(
        """
        DELETE FROM network_events
        WHERE asset_id = ? AND event_type = 'new_device' AND created_at = ?
        """,
        (asset_id, created_at),
    )


def _merge_identity(
    connection: sqlite3.Connection,
    *,
    fallback_row: sqlite3.Row,
    canonical_id: str,
    reconciled_at: str,
    reason: str,
) -> None:
    old_id = fallback_row["asset_id"]
    canonical_row = connection.execute(
        "SELECT * FROM assets WHERE asset_id = ?",
        (canonical_id,),
    ).fetchone()

    if canonical_row is None:
        mac = canonical_id.removeprefix("mac:")
        connection.execute(
            """
            UPDATE assets
            SET asset_id = ?, mac = ?, last_change = ?
            WHERE asset_id = ?
            """,
            (canonical_id, mac, reconciled_at, old_id),
        )
    else:
        _deduplicate_new_device_event(
            connection,
            fallback_row=fallback_row,
            canonical_row=canonical_row,
        )
        first_seen = min(
            (fallback_row["first_seen"], canonical_row["first_seen"]),
            key=_instant,
        )
        last_seen = max(
            (fallback_row["last_seen"], canonical_row["last_seen"]),
            key=_instant,
        )
        is_online = int(bool(fallback_row["is_online"]) or bool(canonical_row["is_online"]))
        connection.execute(
            """
            UPDATE assets
            SET first_seen = ?, last_seen = ?, last_change = ?, is_online = ?
            WHERE asset_id = ?
            """,
            (first_seen, last_seen, reconciled_at, is_online, canonical_id),
        )
        connection.execute("DELETE FROM assets WHERE asset_id = ?", (old_id,))

    connection.execute(
        "UPDATE network_events SET asset_id = ? WHERE asset_id = ?",
        (canonical_id, old_id),
    )
    _repoint_relationships(connection, old_id=old_id, new_id=canonical_id)
    connection.execute(
        """
        INSERT INTO network_events(
            asset_id, scope, created_at, event_type, summary, details, ip
        ) VALUES (?, ?, ?, 'asset_identity_reconciled', ?, ?, ?)
        """,
        (
            canonical_id,
            fallback_row["scope"],
            reconciled_at,
            "Asset identity reconciled",
            f"{old_id} → {canonical_id}. {reason}",
            fallback_row["ip"],
        ),
    )


def _legacy_fingerprint_matches(
    fallback_row: sqlite3.Row,
    canonical_row: sqlite3.Row,
) -> bool:
    return (
        not bool(fallback_row["is_online"])
        and fallback_row["scope"] == canonical_row["scope"]
        and fallback_row["ip"] == canonical_row["ip"]
        and _instant(fallback_row["last_change"]) == _instant(canonical_row["first_seen"])
    )


def reconcile_observation_identity(
    connection: sqlite3.Connection,
    *,
    scope: str,
    ip: str,
    canonical_id: str,
    reconciled_at: str,
) -> bool:
    """Promote an IP fallback when a trustworthy MAC identity becomes available."""
    if not canonical_id.startswith("mac:"):
        return False

    fallback_id = f"ip:{ip}"
    fallback_row = connection.execute(
        "SELECT * FROM assets WHERE asset_id = ? AND scope = ?",
        (fallback_id, scope),
    ).fetchone()
    if fallback_row is None:
        return False

    canonical_row = connection.execute(
        "SELECT * FROM assets WHERE asset_id = ?",
        (canonical_id,),
    ).fetchone()
    active_promotion = bool(fallback_row["is_online"])
    legacy_repair = canonical_row is not None and _legacy_fingerprint_matches(
        fallback_row,
        canonical_row,
    )
    if not active_promotion and not legacy_repair:
        return False

    reason = (
        "A valid MAC was observed while the IP fallback was still active."
        if active_promotion
        else "A legacy IP/MAC duplicate matched the conservative historical fingerprint."
    )
    _merge_identity(
        connection,
        fallback_row=fallback_row,
        canonical_id=canonical_id,
        reconciled_at=reconciled_at,
        reason=reason,
    )
    return True


def repair_legacy_identity_duplicates(
    connection: sqlite3.Connection,
    *,
    reconciled_at: str,
) -> int:
    """Repair duplicates produced by the old IP-fallback-to-MAC transition."""
    fallback_rows = connection.execute(
        """
        SELECT * FROM assets
        WHERE asset_id LIKE 'ip:%' AND is_online = 0
        ORDER BY first_seen, asset_id
        """
    ).fetchall()
    repaired = 0
    for fallback_row in fallback_rows:
        canonical_rows = connection.execute(
            """
            SELECT * FROM assets
            WHERE asset_id LIKE 'mac:%' AND scope = ? AND ip = ?
            ORDER BY first_seen, asset_id
            """,
            (fallback_row["scope"], fallback_row["ip"]),
        ).fetchall()
        matches = [
            row
            for row in canonical_rows
            if _legacy_fingerprint_matches(fallback_row, row)
        ]
        if len(matches) != 1:
            continue
        _merge_identity(
            connection,
            fallback_row=fallback_row,
            canonical_id=matches[0]["asset_id"],
            reconciled_at=reconciled_at,
            reason="A legacy IP/MAC duplicate matched the conservative historical fingerprint.",
        )
        repaired += 1
    return repaired
