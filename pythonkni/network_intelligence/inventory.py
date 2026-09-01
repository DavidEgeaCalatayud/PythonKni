from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pythonkni.camera_auditor.models import RiskLevel

from .models import AssetRecord, DeviceKind, NetworkIntelligenceDevice, TimelineEvent

_MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
_UNKNOWN_MACS = {"", "N/A", "UNKNOWN", "NO DISPONIBLE", "00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_mac(value: str) -> str:
    candidate = (value or "").strip().upper()
    if candidate in _UNKNOWN_MACS or not _MAC_PATTERN.fullmatch(candidate):
        return ""
    return candidate


def asset_identity(device: NetworkIntelligenceDevice) -> str:
    mac = _normalize_mac(device.host.mac)
    return f"mac:{mac}" if mac else f"ip:{device.host.ip}"


def _json_tuple(value) -> str:
    return json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))


def _load_tuple(value: str, converter=str):
    try:
        decoded = json.loads(value or "[]")
    except json.JSONDecodeError:
        decoded = []
    return tuple(converter(item) for item in decoded)


class InventoryStore:
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
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    mac TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    vendor TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    services_json TEXT NOT NULL,
                    ports_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    last_change TEXT NOT NULL,
                    is_online INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_assets_scope_online
                    ON assets(scope, is_online);

                CREATE TABLE IF NOT EXISTS network_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT NOT NULL,
                    ip TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_network_events_scope_created
                    ON network_events(scope, created_at DESC);
                """
            )
            connection.commit()

    def _event(
        self,
        connection,
        *,
        asset_id: str,
        scope: str,
        created_at: datetime,
        event_type: str,
        summary: str,
        details: str,
        ip: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO network_events(asset_id, scope, created_at, event_type, summary, details, ip)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (asset_id, scope, _iso(created_at), event_type, summary, details, ip),
        )

    def _upsert_device(
        self,
        connection,
        scope: str,
        device: NetworkIntelligenceDevice,
        observed_at: datetime,
    ) -> str:
        asset_id = asset_identity(device)
        mac = _normalize_mac(device.host.mac) or (device.host.mac or "Unknown")
        row = connection.execute(
            "SELECT * FROM assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()

        services_json = _json_tuple(device.services)
        ports_json = _json_tuple(device.open_ports)
        evidence_json = _json_tuple(device.evidence)
        timestamp = _iso(observed_at)

        if row is None:
            connection.execute(
                """
                INSERT INTO assets(
                    asset_id, scope, ip, mac, hostname, vendor, kind,
                    services_json, ports_json, evidence_json, risk,
                    first_seen, last_seen, last_change, is_online
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    asset_id,
                    scope,
                    device.host.ip,
                    mac,
                    device.host.hostname,
                    device.vendor,
                    device.kind.value,
                    services_json,
                    ports_json,
                    evidence_json,
                    device.risk.value,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            self._event(
                connection,
                asset_id=asset_id,
                scope=scope,
                created_at=observed_at,
                event_type="new_device",
                summary="New device detected",
                details=f"{device.kind.value} · {device.vendor}",
                ip=device.host.ip,
            )
            return asset_id

        changed = False
        old_ports = set(_load_tuple(row["ports_json"], int))
        new_ports = set(device.open_ports)

        if not bool(row["is_online"]):
            changed = True
            self._event(
                connection,
                asset_id=asset_id,
                scope=scope,
                created_at=observed_at,
                event_type="device_returned",
                summary="Device returned",
                details=f"Seen again as {device.kind.value}",
                ip=device.host.ip,
            )
        if row["ip"] != device.host.ip:
            changed = True
            self._event(
                connection,
                asset_id=asset_id,
                scope=scope,
                created_at=observed_at,
                event_type="ip_changed",
                summary="Device IP changed",
                details=f"{row['ip']} → {device.host.ip}",
                ip=device.host.ip,
            )
        if row["kind"] != device.kind.value:
            changed = True
            self._event(
                connection,
                asset_id=asset_id,
                scope=scope,
                created_at=observed_at,
                event_type="type_changed",
                summary="Device classification changed",
                details=f"{row['kind']} → {device.kind.value}",
                ip=device.host.ip,
            )
        if row["risk"] != device.risk.value:
            changed = True
            self._event(
                connection,
                asset_id=asset_id,
                scope=scope,
                created_at=observed_at,
                event_type="risk_changed",
                summary="Risk level changed",
                details=f"{row['risk']} → {device.risk.value}",
                ip=device.host.ip,
            )

        for port in sorted(new_ports - old_ports):
            changed = True
            service = next(
                (name for index, name in zip(device.open_ports, device.services) if index == port),
                "TCP",
            )
            self._event(
                connection,
                asset_id=asset_id,
                scope=scope,
                created_at=observed_at,
                event_type="port_opened",
                summary="Port appeared",
                details=f"{port}/tcp {service}",
                ip=device.host.ip,
            )
        for port in sorted(old_ports - new_ports):
            changed = True
            self._event(
                connection,
                asset_id=asset_id,
                scope=scope,
                created_at=observed_at,
                event_type="port_closed",
                summary="Port disappeared",
                details=f"{port}/tcp",
                ip=device.host.ip,
            )

        last_change = timestamp if changed else row["last_change"]
        connection.execute(
            """
            UPDATE assets
            SET scope = ?, ip = ?, mac = ?, hostname = ?, vendor = ?, kind = ?,
                services_json = ?, ports_json = ?, evidence_json = ?, risk = ?,
                last_seen = ?, last_change = ?, is_online = 1
            WHERE asset_id = ?
            """,
            (
                scope,
                device.host.ip,
                mac,
                device.host.hostname,
                device.vendor,
                device.kind.value,
                services_json,
                ports_json,
                evidence_json,
                device.risk.value,
                timestamp,
                last_change,
                asset_id,
            ),
        )
        return asset_id

    def record_device(
        self,
        scope: str,
        device: NetworkIntelligenceDevice,
        *,
        observed_at: datetime | None = None,
    ) -> AssetRecord:
        observed_at = observed_at or utc_now()
        with closing(self._connect()) as connection:
            asset_id = self._upsert_device(connection, scope, device, observed_at)
            connection.commit()
        asset = self.get_asset(asset_id)
        if asset is None:
            raise RuntimeError("The persisted asset could not be reloaded.")
        return asset

    def record_scan(
        self,
        scope: str,
        devices: list[NetworkIntelligenceDevice],
        *,
        observed_at: datetime | None = None,
        complete: bool = True,
    ) -> list[AssetRecord]:
        observed_at = observed_at or utc_now()
        seen: set[str] = set()
        with closing(self._connect()) as connection:
            for device in devices:
                seen.add(self._upsert_device(connection, scope, device, observed_at))

            if complete:
                online_rows = connection.execute(
                    "SELECT asset_id, ip FROM assets WHERE scope = ? AND is_online = 1",
                    (scope,),
                ).fetchall()
                for row in online_rows:
                    if row["asset_id"] in seen:
                        continue
                    connection.execute(
                        "UPDATE assets SET is_online = 0, last_change = ? WHERE asset_id = ?",
                        (_iso(observed_at), row["asset_id"]),
                    )
                    self._event(
                        connection,
                        asset_id=row["asset_id"],
                        scope=scope,
                        created_at=observed_at,
                        event_type="device_disappeared",
                        summary="Device disappeared",
                        details="Not observed in the latest completed scan",
                        ip=row["ip"],
                    )
            connection.commit()
        return self.list_assets(scope=scope)

    def _asset_from_row(self, row) -> AssetRecord:
        return AssetRecord(
            asset_id=row["asset_id"],
            scope=row["scope"],
            ip=row["ip"],
            mac=row["mac"],
            hostname=row["hostname"],
            vendor=row["vendor"],
            kind=DeviceKind(row["kind"]),
            services=_load_tuple(row["services_json"], str),
            open_ports=_load_tuple(row["ports_json"], int),
            evidence=_load_tuple(row["evidence_json"], str),
            risk=RiskLevel(row["risk"]),
            first_seen=_parse_datetime(row["first_seen"]),
            last_seen=_parse_datetime(row["last_seen"]),
            last_change=_parse_datetime(row["last_change"]),
            is_online=bool(row["is_online"]),
        )

    def get_asset(self, asset_id: str) -> AssetRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        return self._asset_from_row(row) if row is not None else None

    def list_assets(
        self, *, scope: str | None = None, online_only: bool = False
    ) -> list[AssetRecord]:
        clauses = []
        params = []
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if online_only:
            clauses.append("is_online = 1")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM assets{where} ORDER BY is_online DESC, last_seen DESC, ip"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def list_events(self, *, scope: str | None = None, limit: int = 200) -> list[TimelineEvent]:
        limit = max(1, min(int(limit), 1000))
        params = []
        where = ""
        if scope:
            where = " WHERE scope = ?"
            params.append(scope)
        params.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT id, asset_id, scope, created_at, event_type, summary, details, ip
                FROM network_events{where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            TimelineEvent(
                event_id=row["id"],
                asset_id=row["asset_id"],
                scope=row["scope"],
                created_at=_parse_datetime(row["created_at"]),
                event_type=row["event_type"],
                summary=row["summary"],
                details=row["details"],
                ip=row["ip"],
            )
            for row in rows
        ]
