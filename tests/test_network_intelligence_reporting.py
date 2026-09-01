from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone

import pytest

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network_intelligence.models import (
    AssetRecord,
    DeviceKind,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
    TimelineEvent,
)
from pythonkni.network_intelligence.reporting import build_network_report, export_network_report

NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def asset(
    asset_id: str,
    ip: str,
    *,
    hostname: str = "device.local",
    kind: DeviceKind = DeviceKind.PC,
    risk: RiskLevel = RiskLevel.LOW,
    online: bool = True,
    evidence: tuple[str, ...] = ("classified",),
) -> AssetRecord:
    return AssetRecord(
        asset_id=asset_id,
        scope=SCOPE,
        ip=ip,
        mac="AA:BB:CC:DD:EE:FF",
        hostname=hostname,
        vendor="Vendor",
        kind=kind,
        services=("HTTP",) if risk != RiskLevel.LOW else ("HTTPS",),
        open_ports=(80,) if risk != RiskLevel.LOW else (443,),
        evidence=evidence,
        risk=risk,
        first_seen=NOW,
        last_seen=NOW,
        last_change=NOW,
        is_online=online,
    )


def relationship(*, evidence: tuple[str, ...] = ("same scope",)) -> NetworkRelationship:
    return NetworkRelationship(
        scope=SCOPE,
        source_id="mac:AA:BB:CC:DD:EE:01",
        target_id="mac:AA:BB:CC:DD:EE:02",
        kind=RelationshipKind.PHYSICAL_LINK,
        confidence=RelationshipConfidence.CONFIRMED,
        evidence=evidence,
        observed_at=NOW,
        source_port="Gi1/0/1",
        target_port="eth0",
        protocol="LLDP",
    )


def event(*, details: str = "changed") -> TimelineEvent:
    return TimelineEvent(
        event_id=7,
        asset_id="mac:AA:BB:CC:DD:EE:01",
        scope=SCOPE,
        created_at=NOW,
        event_type="risk_changed",
        summary="Risk changed",
        details=details,
        ip="192.168.1.10",
    )


def test_build_report_is_canonical_ordered_and_reproducible():
    report = build_network_report(
        "192.168.1.25/24",
        [
            asset("ip:192.168.1.20", "192.168.1.20", online=False),
            asset("ip:192.168.1.10", "192.168.1.10", risk=RiskLevel.MEDIUM),
        ],
        [relationship()],
        [event()],
        generated_at=NOW,
    )

    assert report["schema_version"] == 1
    assert report["generated_at"] == "2026-09-01T08:00:00Z"
    assert report["scope"] == SCOPE
    assert report["summary"] == {
        "assets": 2,
        "online_assets": 1,
        "offline_assets": 1,
        "relationships": 1,
        "timeline_events": 1,
    }
    assert [item["ip"] for item in report["assets"]] == ["192.168.1.10", "192.168.1.20"]
    assert report["security_score"]["total_devices"] == 1
    assert report["security_score"]["medium_risk"] == 1


def test_build_report_rejects_ipv6_and_naive_generation_time():
    with pytest.raises(ValueError, match="IPv4"):
        build_network_report("fd00::/64", [], [], [], generated_at=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_network_report(
            SCOPE,
            [],
            [],
            [],
            generated_at=datetime(2026, 9, 1, 8, 0),
        )


def test_json_export_preserves_full_structured_snapshot(tmp_path):
    report = build_network_report(
        SCOPE, [asset("ip:192.168.1.10", "192.168.1.10")], [], [], generated_at=NOW
    )
    path = export_network_report(tmp_path / "report.json", report)

    assert path.name == "report.json"
    assert json.loads(path.read_text(encoding="utf-8")) == report


def test_zip_bundle_contains_json_and_csv_safety(tmp_path):
    report = build_network_report(
        SCOPE,
        [
            asset(
                "ip:192.168.1.10",
                "192.168.1.10",
                hostname='=HYPERLINK("https://example.invalid")',
                evidence=("+formula",),
            )
        ],
        [relationship(evidence=("-danger",))],
        [event(details="@payload")],
        generated_at=NOW,
    )

    path = export_network_report(tmp_path / "evidence.zip", report)

    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            "report.json",
            "assets.csv",
            "relationships.csv",
            "timeline.csv",
        }
        assert json.loads(archive.read("report.json").decode("utf-8")) == report
        assets_csv = archive.read("assets.csv").decode("utf-8")
        relationships_csv = archive.read("relationships.csv").decode("utf-8")
        timeline_csv = archive.read("timeline.csv").decode("utf-8")

    assert "'=HYPERLINK" in assets_csv
    assert "'+formula" in assets_csv
    assert "'-danger" in relationships_csv
    assert "'@payload" in timeline_csv


def test_export_rejects_unknown_extension(tmp_path):
    report = build_network_report(SCOPE, [], [], [], generated_at=NOW)

    with pytest.raises(ValueError, match=".json or .zip"):
        export_network_report(tmp_path / "report.txt", report)
