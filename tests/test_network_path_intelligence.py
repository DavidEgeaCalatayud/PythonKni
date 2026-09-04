from __future__ import annotations

from pythonkni.network_path.intelligence import PathState
from pythonkni.network_path.models import HopHost, HopProbe, TraceProtocol, TraceSnapshot


def hop(ttl: int, ip: str | None, rtt: float | None, *, sent=1, received=None):
    if received is None:
        received = 1 if ip is not None else 0
    return HopProbe(
        ttl=ttl,
        hosts=(HopHost(ip, f"hop-{ttl}.example"),) if ip is not None else (),
        sent=sent,
        received=received,
        loss_pct=((sent - received) / sent * 100.0) if sent else 0.0,
        last_ms=rtt,
    )


def snapshot(
    timestamp: float,
    *,
    route=("192.168.1.1", "10.0.0.1", "8.8.8.8"),
    rtts=(1.0, 10.0, 30.0),
    target="8.8.8.8",
):
    hops = tuple(
        hop(index + 1, ip, rtts[index] if ip is not None else None)
        for index, ip in enumerate(route)
    )
    return TraceSnapshot(
        timestamp,
        target,
        target,
        "dns.google",
        TraceProtocol.ICMP,
        None,
        hops,
        any(item is not None and item == target for item in route),
    )


def kinds(update):
    return {event.kind for event in update.events}


def test_first_reached_route_is_baseline_without_change_event():
    update = PathState().observe(snapshot(1.0))
    assert "route_changed" not in kinds(update)
    assert update.snapshot.reached_destination is True
    assert update.history[-1].hop_count == 3
    assert update.hops[-1].status == "Destination"


def test_route_change_requires_confirmation():
    state = PathState()
    state.observe(snapshot(1.0))
    first = state.observe(
        snapshot(2.0, route=("192.168.1.1", "10.0.0.99", "8.8.8.8"))
    )
    second = state.observe(
        snapshot(3.0, route=("192.168.1.1", "10.0.0.99", "8.8.8.8"))
    )
    assert "route_changed" not in kinds(first)
    assert "route_changed" in kinds(second)
    event = next(item for item in second.events if item.kind == "route_changed")
    assert "TTL" not in event.title
    assert "2" in event.description


def test_one_missing_intermediate_reply_does_not_remove_hop():
    state = PathState()
    state.observe(snapshot(1.0))
    update = state.observe(
        snapshot(2.0, route=("192.168.1.1", None, "8.8.8.8"), rtts=(1.0, 0.0, 31.0))
    )
    assert "route_changed" not in kinds(update)
    assert "hop_removed" not in kinds(update)
    assert update.hops[1].status == "No reply (not proof of forwarding loss)"


def test_stable_route_length_changes_emit_added_and_removed_events():
    state = PathState()
    state.observe(snapshot(1.0))
    longer = ("192.168.1.1", "10.0.0.1", "10.0.0.2", "8.8.8.8")
    rtts = (1.0, 10.0, 18.0, 32.0)
    state.observe(snapshot(2.0, route=longer, rtts=rtts))
    added = state.observe(snapshot(3.0, route=longer, rtts=rtts))
    assert "hop_added" in kinds(added)
    assert "route_changed" in kinds(added)

    state.observe(snapshot(4.0))
    removed = state.observe(snapshot(5.0))
    assert "hop_removed" in kinds(removed)
    assert "route_changed" in kinds(removed)


def test_destination_unreachable_requires_three_consecutive_rounds():
    state = PathState()
    state.observe(snapshot(1.0))
    unreachable = ("192.168.1.1", "10.0.0.1", None)
    first = state.observe(snapshot(2.0, route=unreachable, rtts=(1.0, 10.0, 0.0)))
    second = state.observe(snapshot(3.0, route=unreachable, rtts=(1.0, 10.0, 0.0)))
    third = state.observe(snapshot(4.0, route=unreachable, rtts=(1.0, 10.0, 0.0)))
    assert "destination_unreachable" not in kinds(first)
    assert "destination_unreachable" not in kinds(second)
    assert "destination_unreachable" in kinds(third)

    recovered = state.observe(snapshot(5.0))
    assert recovered.snapshot.reached_destination is True
    again = state.observe(snapshot(6.0, route=unreachable, rtts=(1.0, 10.0, 0.0)))
    assert "destination_unreachable" not in kinds(again)


def test_packet_loss_is_based_on_destination_not_intermediate_silence():
    state = PathState()
    for index in range(6):
        update = state.observe(
            snapshot(
                float(index),
                route=("192.168.1.1", None, "8.8.8.8"),
                rtts=(1.0, 0.0, 30.0),
            )
        )
        assert "packet_loss" not in kinds(update)
    assert update.history[-1].destination_loss_pct == 0.0


def test_end_to_end_packet_loss_event_uses_accumulated_destination_rounds():
    state = PathState()
    state.observe(snapshot(1.0))
    unreachable = ("192.168.1.1", "10.0.0.1", None)
    updates = [
        state.observe(snapshot(float(index), route=unreachable, rtts=(1.0, 10.0, 0.0)))
        for index in range(2, 6)
    ]
    assert "packet_loss" in kinds(updates[-1])
    event = next(item for item in updates[-1].events if item.kind == "packet_loss")
    assert "destino" in event.description.lower()
    assert event.severity.value == "CRITICAL"


def test_latency_spike_uses_recent_destination_baseline_and_marks_issue_hop():
    state = PathState()
    for index in range(5):
        update = state.observe(snapshot(float(index), rtts=(1.0, 10.0, 30.0)))
        assert "latency_spike" not in kinds(update)

    spike = state.observe(snapshot(10.0, rtts=(1.0, 10.0, 100.0)))
    assert "latency_spike" in kinds(spike)
    event = next(item for item in spike.events if item.kind == "latency_spike")
    assert event.hop_ttl == 3
    assert spike.issue_hop_ttl == 3
    assert spike.hops[-1].status == "Latency jump"


def test_hop_stats_accumulate_min_max_average_and_jitter():
    state = PathState()
    state.observe(snapshot(1.0, rtts=(1.0, 10.0, 20.0)))
    update = state.observe(snapshot(2.0, rtts=(3.0, 14.0, 30.0)))
    first = update.hops[0]
    assert first.sent == 2
    assert first.received == 2
    assert first.avg_ms == 2.0
    assert first.min_ms == 1.0
    assert first.max_ms == 3.0
    assert first.jitter_ms == 2.0


def test_reset_clears_history_and_route_baseline():
    state = PathState()
    state.observe(snapshot(1.0))
    assert state.history
    state.reset()
    assert not state.history
    update = state.observe(snapshot(2.0))
    assert "route_changed" not in kinds(update)
