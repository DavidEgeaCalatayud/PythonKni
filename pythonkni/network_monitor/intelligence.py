from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from .models import (
    AsnInfo,
    ConnectionObservation,
    EndpointScope,
    EventSeverity,
    HostActivity,
    KnownAssetRef,
    MonitorEvent,
    MonitorHistoryPoint,
    MonitorSnapshot,
    MonitorUpdate,
    ProcessActivity,
)

COMMON_EGRESS_PORTS = {53, 80, 123, 443, 853, 993, 995, 5228, 5353}
DEFAULT_TRAFFIC_SPIKE_BPS = 10 * 1024 * 1024
MAX_DNS_LOOKUPS_PER_SAMPLE = 4
MAX_ASN_LOOKUPS_PER_SAMPLE = 2
HISTORY_LIMIT = 300


def _inventory_store(database_path: Path):
    from pythonkni.network_intelligence.inventory import InventoryStore

    return InventoryStore(database_path)


def load_known_assets(database_path: Path) -> dict[str, KnownAssetRef]:
    store = _inventory_store(database_path)
    assets: dict[str, KnownAssetRef] = {}
    for asset in store.list_assets():
        label = (
            getattr(asset, "hostname", "")
            or getattr(getattr(asset, "kind", None), "value", "")
            or asset.ip
        )
        assets[asset.ip] = KnownAssetRef(asset_id=asset.asset_id, ip=asset.ip, label=str(label))
    return assets


def _event_id(kind: str, key: str) -> str:
    return hashlib.sha256(f"network-monitor|{kind}|{key}".encode()).hexdigest()


def _event(
    *,
    kind: str,
    key: str,
    severity: EventSeverity,
    timestamp: float,
    title: str,
    description: str,
    connection: ConnectionObservation | None = None,
    asset_id: str = "",
) -> MonitorEvent:
    return MonitorEvent(
        event_id=_event_id(kind, key),
        kind=kind,
        severity=severity,
        timestamp=timestamp,
        title=title,
        description=description,
        process_name=connection.process_name if connection else "",
        remote_ip=connection.remote_ip or "" if connection else "",
        port=connection.remote_port if connection else None,
        asset_id=asset_id,
    )


def _aggregate_processes(
    connections: tuple[ConnectionObservation, ...],
) -> tuple[ProcessActivity, ...]:
    groups: dict[tuple[int | None, str], list[ConnectionObservation]] = defaultdict(list)
    for connection in connections:
        groups[(connection.pid, connection.process_name)].append(connection)
    result = []
    for (pid, process_name), items in groups.items():
        remotes = sorted({item.remote_ip for item in items if item.remote_ip})
        result.append(
            ProcessActivity(
                pid=pid,
                process_name=process_name,
                connection_count=len(items),
                external_connections=sum(item.scope is EndpointScope.PUBLIC for item in items),
                remote_hosts=tuple(remotes),
                protocols=tuple(sorted({item.protocol for item in items})),
            )
        )
    return tuple(
        sorted(result, key=lambda item: (-item.connection_count, item.process_name.casefold()))
    )


def _aggregate_hosts(
    connections: tuple[ConnectionObservation, ...],
    known_assets: Mapping[str, KnownAssetRef],
    asn_cache: Mapping[str, AsnInfo],
) -> tuple[HostActivity, ...]:
    groups: dict[str, list[ConnectionObservation]] = defaultdict(list)
    for connection in connections:
        if connection.remote_ip:
            groups[connection.remote_ip].append(connection)
    result = []
    for ip, items in groups.items():
        known = known_assets.get(ip)
        hostname = next((item.hostname for item in items if item.hostname), "")
        asn_info = asn_cache.get(ip, AsnInfo())
        result.append(
            HostActivity(
                ip=ip,
                hostname=hostname,
                scope=items[0].scope,
                connection_count=len(items),
                processes=tuple(sorted({item.process_name for item in items}, key=str.casefold)),
                ports=tuple(
                    sorted({item.remote_port for item in items if item.remote_port is not None})
                ),
                known_asset_id=known.asset_id if known else "",
                known_asset_label=known.label if known else "",
                asn=asn_info.label,
                prefix=asn_info.prefix,
            )
        )
    return tuple(sorted(result, key=lambda item: (-item.connection_count, item.ip)))


class MonitorState:
    def __init__(self, *, traffic_spike_bps: float = DEFAULT_TRAFFIC_SPIKE_BPS) -> None:
        self.traffic_spike_bps = max(0.0, traffic_spike_bps)
        self.seen_remote_hosts: set[str] = set()
        self.seen_external_connections: set[str] = set()
        self.seen_listeners: set[str] = set()
        self.seen_processes: set[tuple[int | None, str]] = set()
        self.seen_known_assets: set[str] = set()
        self.seen_unusual_destinations: set[str] = set()
        self.hostname_cache: dict[str, str] = {}
        self.asn_cache: dict[str, AsnInfo] = {}
        self.history: deque[MonitorHistoryPoint] = deque(maxlen=HISTORY_LIMIT)
        self._spike_active = False

    def _enrich_dns(
        self,
        snapshot: MonitorSnapshot,
        resolver: Callable[[str], str] | None,
    ) -> MonitorSnapshot:
        if resolver is None:
            return snapshot
        unresolved = []
        for connection in snapshot.connections:
            ip = connection.remote_ip
            if ip and ip not in self.hostname_cache and ip not in unresolved:
                unresolved.append(ip)
        for ip in unresolved[:MAX_DNS_LOOKUPS_PER_SAMPLE]:
            self.hostname_cache[ip] = resolver(ip)
        connections = tuple(
            replace(connection, hostname=self.hostname_cache.get(connection.remote_ip or "", ""))
            for connection in snapshot.connections
        )
        return replace(snapshot, connections=connections)

    def _enrich_asn(
        self,
        snapshot: MonitorSnapshot,
        resolver: Callable[[str], AsnInfo] | None,
    ) -> None:
        if resolver is None:
            return
        unresolved = []
        for connection in snapshot.connections:
            ip = connection.remote_ip
            if (
                ip
                and connection.scope is EndpointScope.PUBLIC
                and ip not in self.asn_cache
                and ip not in unresolved
            ):
                unresolved.append(ip)
        for ip in unresolved[:MAX_ASN_LOOKUPS_PER_SAMPLE]:
            self.asn_cache[ip] = resolver(ip)

    def observe(
        self,
        snapshot: MonitorSnapshot,
        *,
        known_assets: Mapping[str, KnownAssetRef] | None = None,
        resolver: Callable[[str], str] | None = None,
        asn_resolver: Callable[[str], AsnInfo] | None = None,
    ) -> MonitorUpdate:
        known_assets = {} if known_assets is None else known_assets
        snapshot = self._enrich_dns(snapshot, resolver)
        self._enrich_asn(snapshot, asn_resolver)
        events = []

        for connection in snapshot.connections:
            if connection.is_listener:
                listener_key = (
                    f"{connection.transport}|{connection.local_port}|{connection.pid or 0}"
                )
                if listener_key not in self.seen_listeners:
                    self.seen_listeners.add(listener_key)
                    events.append(
                        _event(
                            kind="new_listening_port",
                            key=listener_key,
                            severity=EventSeverity.INFO,
                            timestamp=snapshot.timestamp,
                            title="New listening port",
                            description=(
                                f"{connection.process_name} is listening on "
                                f"{connection.local_ip or '*'}:{connection.local_port}/"
                                f"{connection.transport}."
                            ),
                            connection=connection,
                        )
                    )

            if not connection.remote_ip:
                continue

            remote_ip = connection.remote_ip
            if remote_ip not in self.seen_remote_hosts:
                self.seen_remote_hosts.add(remote_ip)
                events.append(
                    _event(
                        kind="new_remote_host",
                        key=remote_ip,
                        severity=EventSeverity.INFO,
                        timestamp=snapshot.timestamp,
                        title="New remote host",
                        description=f"First observed connection to {remote_ip} in this monitor session.",
                        connection=connection,
                    )
                )

            process_key = (connection.pid, connection.process_name)
            if process_key not in self.seen_processes:
                self.seen_processes.add(process_key)
                events.append(
                    _event(
                        kind="process_network_activity",
                        key=f"{connection.pid or 0}|{connection.process_name}",
                        severity=EventSeverity.INFO,
                        timestamp=snapshot.timestamp,
                        title="Process network activity",
                        description=f"{connection.process_name} started network activity.",
                        connection=connection,
                    )
                )

            if connection.scope is EndpointScope.PUBLIC:
                if connection.key not in self.seen_external_connections:
                    self.seen_external_connections.add(connection.key)
                    events.append(
                        _event(
                            kind="new_external_connection",
                            key=connection.key,
                            severity=EventSeverity.WARNING,
                            timestamp=snapshot.timestamp,
                            title="New external connection",
                            description=(
                                f"{connection.process_name} connected to {remote_ip}:"
                                f"{connection.remote_port or 0}/{connection.transport}."
                            ),
                            connection=connection,
                        )
                    )
                if connection.remote_port and connection.remote_port not in COMMON_EGRESS_PORTS:
                    unusual_key = f"{connection.process_name}|{remote_ip}|{connection.remote_port}"
                    if unusual_key not in self.seen_unusual_destinations:
                        self.seen_unusual_destinations.add(unusual_key)
                        events.append(
                            _event(
                                kind="unusual_destination",
                                key=unusual_key,
                                severity=EventSeverity.WARNING,
                                timestamp=snapshot.timestamp,
                                title="Unusual external destination",
                                description=(
                                    f"Observed {connection.process_name} using uncommon destination port "
                                    f"{connection.remote_port} on {remote_ip}."
                                ),
                                connection=connection,
                            )
                        )

            known = known_assets.get(remote_ip)
            if known and known.asset_id not in self.seen_known_assets:
                self.seen_known_assets.add(known.asset_id)
                events.append(
                    _event(
                        kind="known_asset_connection",
                        key=f"{known.asset_id}|{connection.key}",
                        severity=EventSeverity.INFO,
                        timestamp=snapshot.timestamp,
                        title="Known asset connection",
                        description=(
                            f"Traffic matched Network Intelligence asset {known.label} ({remote_ip})."
                        ),
                        connection=connection,
                        asset_id=known.asset_id,
                    )
                )

        spike_now = snapshot.traffic.total_bps >= self.traffic_spike_bps > 0
        if spike_now and not self._spike_active:
            events.append(
                _event(
                    kind="traffic_spike",
                    key=f"{int(snapshot.timestamp // 30)}|{int(snapshot.traffic.total_bps)}",
                    severity=EventSeverity.WARNING,
                    timestamp=snapshot.timestamp,
                    title="Traffic spike",
                    description=(
                        f"Combined adapter traffic reached {snapshot.traffic.total_bps:.0f} B/s, "
                        f"above the configured {self.traffic_spike_bps:.0f} B/s threshold."
                    ),
                )
            )
        self._spike_active = spike_now

        external_connections = sum(
            connection.scope is EndpointScope.PUBLIC and connection.remote_ip is not None
            for connection in snapshot.connections
        )
        history_point = MonitorHistoryPoint(
            timestamp=snapshot.timestamp,
            rx_bps=snapshot.traffic.rx_bps,
            tx_bps=snapshot.traffic.tx_bps,
            connections=len(snapshot.connections),
            external_connections=external_connections,
            remote_hosts=len({item.remote_ip for item in snapshot.connections if item.remote_ip}),
        )
        self.history.append(history_point)

        return MonitorUpdate(
            snapshot=snapshot,
            processes=_aggregate_processes(snapshot.connections),
            hosts=_aggregate_hosts(snapshot.connections, known_assets, self.asn_cache),
            events=tuple(events),
            history=tuple(self.history),
        )
