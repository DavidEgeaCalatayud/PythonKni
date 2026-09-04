from __future__ import annotations

import hashlib
import statistics
from collections import deque
from dataclasses import replace

from .models import (
    HopProbe,
    HopStats,
    PathEvent,
    PathEventSeverity,
    PathHistoryPoint,
    PathUpdate,
    TraceSnapshot,
)

HISTORY_LIMIT = 300
HOP_SAMPLE_LIMIT = 120
ROUTE_CONFIRMATIONS = 2
UNREACHABLE_CONFIRMATIONS = 3
MIN_LOSS_SAMPLES = 5
LOSS_WARNING_PCT = 20.0
LOSS_CRITICAL_PCT = 50.0
LOSS_RECOVERY_PCT = 10.0
MIN_LATENCY_BASELINE_SAMPLES = 5
LATENCY_SPIKE_RATIO = 1.75
LATENCY_SPIKE_DELTA_MS = 30.0
LATENCY_RECOVERY_RATIO = 1.40
LATENCY_RECOVERY_DELTA_MS = 15.0
LATENCY_STEP_MS = 20.0
LATENCY_STEP_RATIO = 1.50


def _event_id(kind: str, target: str, key: str) -> str:
    payload = f"network-path|{kind}|{target}|{key}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event(
    snapshot: TraceSnapshot,
    *,
    kind: str,
    key: str,
    severity: PathEventSeverity,
    title: str,
    description: str,
    hop_ttl: int | None = None,
    hop_ip: str = "",
) -> PathEvent:
    return PathEvent(
        event_id=_event_id(kind, snapshot.target, key),
        kind=kind,
        severity=severity,
        timestamp=snapshot.timestamp,
        title=title,
        description=description,
        target=snapshot.target,
        hop_ttl=hop_ttl,
        hop_ip=hop_ip,
    )


class _HopAccumulator:
    def __init__(self) -> None:
        self.sent = 0
        self.received = 0
        self.rtts: deque[float] = deque(maxlen=HOP_SAMPLE_LIMIT)

    def add(self, probe: HopProbe) -> None:
        self.sent += max(0, probe.sent)
        self.received += max(0, probe.received)
        if probe.last_ms is not None and probe.received > 0:
            self.rtts.append(max(0.0, probe.last_ms))

    def stats(self, probe: HopProbe) -> HopStats:
        values = tuple(self.rtts)
        average = statistics.fmean(values) if values else None
        jitter = None
        if len(values) >= 2:
            jitter = statistics.fmean(
                abs(current - previous) for previous, current in zip(values, values[1:])
            )
        loss = ((self.sent - self.received) / self.sent * 100.0) if self.sent else 0.0
        return HopStats(
            ttl=probe.ttl,
            hosts=probe.hosts,
            sent=self.sent,
            received=self.received,
            loss_pct=min(100.0, max(0.0, loss)),
            last_ms=probe.last_ms,
            avg_ms=average,
            min_ms=min(values) if values else None,
            max_ms=max(values) if values else None,
            jitter_ms=jitter,
            status="OK" if probe.responded else "No reply (not proof of forwarding loss)",
        )


def _host_signature(probe: HopProbe) -> tuple[str, ...]:
    return tuple(sorted(set(probe.host_ips)))


def _route_text(route: tuple[tuple[int, tuple[str, ...]], ...]) -> str:
    return " → ".join(
        f"{ttl}:{'/'.join(hosts)}" for ttl, hosts in route if hosts
    ) or "sin saltos respondientes"


class PathState:
    """Aggregate path samples and emit conservative, explainable temporal events."""

    def __init__(self) -> None:
        self._hop_accumulators: dict[tuple[int, tuple[str, ...]], _HopAccumulator] = {}
        self._confirmed_route: tuple[tuple[int, tuple[str, ...]], ...] | None = None
        self._candidate_route: tuple[tuple[int, tuple[str, ...]], ...] | None = None
        self._candidate_count = 0
        self._unreachable_streak = 0
        self._unreachable_active = False
        self._loss_active = False
        self._latency_active = False
        self._destination_sent = 0
        self._destination_received = 0
        self._destination_rtts: deque[float] = deque(maxlen=HOP_SAMPLE_LIMIT)
        self.history: deque[PathHistoryPoint] = deque(maxlen=HISTORY_LIMIT)

    def reset(self) -> None:
        self.__init__()

    def _current_stats(self, snapshot: TraceSnapshot) -> tuple[HopStats, ...]:
        result: list[HopStats] = []
        for probe in snapshot.hops:
            key = (probe.ttl, _host_signature(probe))
            accumulator = self._hop_accumulators.setdefault(key, _HopAccumulator())
            accumulator.add(probe)
            result.append(accumulator.stats(probe))
        return tuple(result)

    def _normalized_route(
        self, snapshot: TraceSnapshot
    ) -> tuple[tuple[int, tuple[str, ...]], ...] | None:
        destination = snapshot.destination_hop
        if not snapshot.reached_destination or destination is None:
            return None

        observed = {
            hop.ttl: _host_signature(hop)
            for hop in snapshot.hops
            if hop.responded and hop.ttl <= destination.ttl
        }
        previous = dict(self._confirmed_route or ())
        route: list[tuple[int, tuple[str, ...]]] = []
        for ttl in range(1, destination.ttl + 1):
            hosts = observed.get(ttl)
            if hosts is None:
                hosts = previous.get(ttl, ())
            if hosts:
                route.append((ttl, hosts))
        return tuple(route)

    def _route_events(self, snapshot: TraceSnapshot) -> list[PathEvent]:
        route = self._normalized_route(snapshot)
        if route is None:
            return []
        if self._confirmed_route is None:
            self._confirmed_route = route
            self._candidate_route = None
            self._candidate_count = 0
            return []
        if route == self._confirmed_route:
            self._candidate_route = None
            self._candidate_count = 0
            return []

        if route == self._candidate_route:
            self._candidate_count += 1
        else:
            self._candidate_route = route
            self._candidate_count = 1
        if self._candidate_count < ROUTE_CONFIRMATIONS:
            return []

        old_route = self._confirmed_route
        self._confirmed_route = route
        self._candidate_route = None
        self._candidate_count = 0
        old = dict(old_route)
        new = dict(route)
        events: list[PathEvent] = []

        for ttl in sorted(set(new) - set(old)):
            hosts = new[ttl]
            events.append(
                _event(
                    snapshot,
                    kind="hop_added",
                    key=f"ttl={ttl}|{'/'.join(hosts)}",
                    severity=PathEventSeverity.INFO,
                    title="Hop added",
                    description=f"La ruta estable añadió el salto {ttl}: {' / '.join(hosts)}.",
                    hop_ttl=ttl,
                    hop_ip=hosts[0] if hosts else "",
                )
            )
        for ttl in sorted(set(old) - set(new)):
            hosts = old[ttl]
            events.append(
                _event(
                    snapshot,
                    kind="hop_removed",
                    key=f"ttl={ttl}|{'/'.join(hosts)}",
                    severity=PathEventSeverity.INFO,
                    title="Hop removed",
                    description=f"La ruta estable dejó de incluir el salto {ttl}: {' / '.join(hosts)}.",
                    hop_ttl=ttl,
                    hop_ip=hosts[0] if hosts else "",
                )
            )

        changed_ttls = [ttl for ttl in sorted(set(old) & set(new)) if old[ttl] != new[ttl]]
        changed_label = ", ".join(str(ttl) for ttl in changed_ttls) or "longitud de ruta"
        events.append(
            _event(
                snapshot,
                kind="route_changed",
                key=f"{old_route!r}|{route!r}",
                severity=PathEventSeverity.WARNING,
                title="Route changed",
                description=(
                    f"La ruta confirmada hacia {snapshot.target} cambió ({changed_label}). "
                    f"Anterior: {_route_text(old_route)}. Actual: {_route_text(route)}."
                ),
            )
        )
        return events

    def _issue_hop(self, stats: tuple[HopStats, ...]) -> int | None:
        responding = [item for item in stats if item.avg_ms is not None]
        if not responding:
            return None
        first = responding[0]
        if first.avg_ms is not None and first.avg_ms >= 50.0:
            return first.ttl
        previous = first
        for current in responding[1:]:
            assert previous.avg_ms is not None
            assert current.avg_ms is not None
            delta = current.avg_ms - previous.avg_ms
            if delta >= LATENCY_STEP_MS and current.avg_ms >= previous.avg_ms * LATENCY_STEP_RATIO:
                return current.ttl
            previous = current
        return None

    def _destination_events(
        self,
        snapshot: TraceSnapshot,
        *,
        issue_hop_ttl: int | None,
    ) -> list[PathEvent]:
        events: list[PathEvent] = []
        destination = snapshot.destination_hop
        current_rtt = destination.last_ms if destination is not None else None

        self._destination_sent += 1
        if snapshot.reached_destination:
            self._destination_received += 1
            self._unreachable_streak = 0
            self._unreachable_active = False
        else:
            self._unreachable_streak += 1
            if (
                self._unreachable_streak >= UNREACHABLE_CONFIRMATIONS
                and not self._unreachable_active
            ):
                self._unreachable_active = True
                events.append(
                    _event(
                        snapshot,
                        kind="destination_unreachable",
                        key=f"protocol={snapshot.protocol.value}",
                        severity=PathEventSeverity.CRITICAL,
                        title="Destination unreachable",
                        description=(
                            f"{snapshot.target} no respondió como destino durante "
                            f"{self._unreachable_streak} rondas consecutivas. Esto puede indicar "
                            "filtrado, falta de privilegios/respuestas o un problema real de ruta."
                        ),
                    )
                )

        loss = (
            (self._destination_sent - self._destination_received)
            / self._destination_sent
            * 100.0
        )
        if self._destination_sent >= MIN_LOSS_SAMPLES:
            if loss >= LOSS_WARNING_PCT and not self._loss_active:
                self._loss_active = True
                severity = (
                    PathEventSeverity.CRITICAL
                    if loss >= LOSS_CRITICAL_PCT
                    else PathEventSeverity.WARNING
                )
                events.append(
                    _event(
                        snapshot,
                        kind="packet_loss",
                        key=f"destination|{snapshot.protocol.value}",
                        severity=severity,
                        title="End-to-end packet loss",
                        description=(
                            f"La pérdida acumulada hacia el destino {snapshot.target} alcanzó "
                            f"{loss:.1f}% tras {self._destination_sent} rondas. La falta de respuesta "
                            "de saltos intermedios no se contabiliza como pérdida end-to-end."
                        ),
                    )
                )
            elif self._loss_active and loss < LOSS_RECOVERY_PCT:
                self._loss_active = False

        baseline_values = tuple(self._destination_rtts)
        if current_rtt is not None and len(baseline_values) >= MIN_LATENCY_BASELINE_SAMPLES:
            baseline = statistics.median(baseline_values)
            spike = (
                current_rtt >= baseline * LATENCY_SPIKE_RATIO
                and current_rtt - baseline >= LATENCY_SPIKE_DELTA_MS
            )
            recovered = (
                current_rtt < baseline * LATENCY_RECOVERY_RATIO
                or current_rtt - baseline < LATENCY_RECOVERY_DELTA_MS
            )
            if spike and not self._latency_active:
                self._latency_active = True
                hop_ip = ""
                if issue_hop_ttl is not None:
                    issue_probe = next(
                        (hop for hop in snapshot.hops if hop.ttl == issue_hop_ttl), None
                    )
                    hop_ip = issue_probe.primary_ip if issue_probe else ""
                events.append(
                    _event(
                        snapshot,
                        kind="latency_spike",
                        key=f"destination|{snapshot.protocol.value}",
                        severity=PathEventSeverity.WARNING,
                        title="Latency spike",
                        description=(
                            f"RTT hacia {snapshot.target}: {current_rtt:.1f} ms frente a una mediana "
                            f"reciente de {baseline:.1f} ms. "
                            + (
                                f"El primer salto con incremento sostenido está en TTL {issue_hop_ttl}."
                                if issue_hop_ttl is not None
                                else "No hay suficiente evidencia para atribuirlo a un salto concreto."
                            )
                        ),
                        hop_ttl=issue_hop_ttl,
                        hop_ip=hop_ip,
                    )
                )
            elif self._latency_active and recovered:
                self._latency_active = False

        if current_rtt is not None:
            self._destination_rtts.append(max(0.0, current_rtt))
        return events

    def observe(self, snapshot: TraceSnapshot) -> PathUpdate:
        stats = self._current_stats(snapshot)
        issue_hop_ttl = self._issue_hop(stats)
        destination = snapshot.destination_hop
        destination_ttl = destination.ttl if destination is not None else None
        decorated: list[HopStats] = []
        for item in stats:
            status = item.status
            if item.ttl == destination_ttl:
                status = "Destination"
            if item.ttl == issue_hop_ttl:
                status = "Latency jump"
            decorated.append(replace(item, status=status))
        stats = tuple(decorated)

        events = self._route_events(snapshot)
        events.extend(self._destination_events(snapshot, issue_hop_ttl=issue_hop_ttl))

        destination_loss = (
            (self._destination_sent - self._destination_received)
            / self._destination_sent
            * 100.0
            if self._destination_sent
            else 0.0
        )
        history_point = PathHistoryPoint(
            timestamp=snapshot.timestamp,
            target=snapshot.target,
            destination_rtt_ms=destination.last_ms if destination is not None else None,
            destination_loss_pct=destination_loss,
            hop_count=destination.ttl if destination is not None else len(snapshot.hops),
            reached_destination=snapshot.reached_destination,
            issue_hop_ttl=issue_hop_ttl,
        )
        self.history.append(history_point)
        return PathUpdate(
            snapshot=snapshot,
            hops=stats,
            events=tuple(events),
            history=tuple(self.history),
            issue_hop_ttl=issue_hop_ttl,
        )
