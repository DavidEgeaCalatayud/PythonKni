from __future__ import annotations

import threading
from datetime import datetime, timezone
from types import SimpleNamespace

from pythonkni.network import fingerprinting
from pythonkni.network.models import ServiceFingerprint
from pythonkni.network_intelligence import fingerprint_policy
from pythonkni.network_intelligence.fingerprint_policy import FingerprintPolicy

SCOPE = "192.168.1.0/24"
NOW = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)


class _Store:
    def __init__(self, assets):
        self.assets = assets

    def list_assets(self, *, scope=None, online_only=False):
        assert scope == SCOPE
        return list(self.assets)


def _asset(asset_id, ip, *, online=True, ports=(22,), last_change=NOW):
    return SimpleNamespace(
        asset_id=asset_id,
        ip=ip,
        is_online=online,
        open_ports=ports,
        last_change=last_change,
    )


def test_policy_filters_offline_and_portless_assets_and_reports_progress(monkeypatch):
    assets = [
        _asset("offline", "192.168.1.10", online=False),
        _asset("empty", "192.168.1.11", ports=()),
        _asset("online", "192.168.1.12", ports=(443, 22)),
    ]
    calls = []
    progress = []
    monkeypatch.setattr(
        fingerprint_policy,
        "fingerprint_open_ports",
        lambda target, ports, **kwargs: calls.append((target, tuple(ports), kwargs)) or [],
    )

    result = fingerprint_policy.run_scheduled_fingerprinting(
        _Store(assets),
        SCOPE,
        FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
        on_progress=progress.append,
    )

    assert result.selected_assets == 1
    assert result.attempted_assets == 1
    assert result.fingerprinted_assets == 0
    assert calls[0][0] == "192.168.1.12"
    assert calls[0][1] == (22, 443)
    assert progress and "1/1" in progress[0]


def test_missing_nerva_stops_remaining_assets_without_losing_error(monkeypatch):
    assets = [
        _asset("a", "192.168.1.10"),
        _asset("b", "192.168.1.11"),
    ]
    calls = []

    def unavailable(target, ports, **kwargs):
        calls.append(target)
        raise fingerprinting.FingerprintEngineUnavailable("nerva missing")

    monkeypatch.setattr(fingerprint_policy, "fingerprint_open_ports", unavailable)

    result = fingerprint_policy.run_scheduled_fingerprinting(
        _Store(assets), SCOPE, FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY
    )

    assert calls == ["192.168.1.10"]
    assert result.attempted_assets == 1
    assert result.errors == ("nerva missing",)


def test_one_asset_failure_does_not_abort_next_asset(monkeypatch):
    assets = [
        _asset("a", "192.168.1.10"),
        _asset("b", "192.168.1.11"),
    ]
    persisted = []

    def fingerprint(target, ports, **kwargs):
        if target.endswith(".10"):
            raise RuntimeError("timeout")
        return [
            ServiceFingerprint(
                host=target,
                ip=target,
                port=22,
                protocol="ssh",
            )
        ]

    monkeypatch.setattr(fingerprint_policy, "fingerprint_open_ports", fingerprint)
    monkeypatch.setattr(
        fingerprint_policy,
        "persist_asset_fingerprints",
        lambda store, asset, results: persisted.append((asset.asset_id, tuple(results))),
    )

    result = fingerprint_policy.run_scheduled_fingerprinting(
        _Store(assets), SCOPE, FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY
    )

    assert result.attempted_assets == 2
    assert result.fingerprinted_assets == 1
    assert result.fingerprints == 1
    assert result.errors == ("192.168.1.10: timeout",)
    assert persisted[0][0] == "b"


def test_cancel_between_assets_stops_without_persisting_later_results(monkeypatch):
    stop_event = threading.Event()
    assets = [
        _asset("a", "192.168.1.10"),
        _asset("b", "192.168.1.11"),
    ]
    persisted = []

    def fingerprint(target, ports, **kwargs):
        stop_event.set()
        return [
            ServiceFingerprint(
                host=target,
                ip=target,
                port=22,
                protocol="ssh",
            )
        ]

    monkeypatch.setattr(fingerprint_policy, "fingerprint_open_ports", fingerprint)
    monkeypatch.setattr(
        fingerprint_policy,
        "persist_asset_fingerprints",
        lambda *args: persisted.append(args),
    )

    result = fingerprint_policy.run_scheduled_fingerprinting(
        _Store(assets),
        SCOPE,
        FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
        stop_event=stop_event,
    )

    assert result.cancelled
    assert result.attempted_assets == 1
    assert persisted == []
