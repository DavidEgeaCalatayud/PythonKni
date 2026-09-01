from __future__ import annotations

import json
import zipfile

import pytest

from pythonkni.network_intelligence import comparison
from pythonkni.network_intelligence.comparison import (
    SnapshotReportError,
    compare_network_reports,
    format_snapshot_comparison,
    load_network_report,
    validate_network_report,
)

SCOPE = "192.168.1.0/24"


def asset(
    asset_id: str = "mac:AA:BB:CC:DD:EE:01",
    ip: str = "192.168.1.10",
    **overrides,
):
    value = {
        "asset_id": asset_id,
        "scope": SCOPE,
        "ip": ip,
        "mac": "AA:BB:CC:DD:EE:01",
        "hostname": "nas.local",
        "vendor": "Synology",
        "kind": "NAS",
        "classification_confidence": 80,
        "services": ["HTTPS", "SMB"],
        "open_ports": [443, 445],
        "risk": "LOW",
        "is_online": True,
        "first_seen": "2026-09-01T08:00:00Z",
        "last_seen": "2026-09-01T08:00:00Z",
        "last_change": "2026-09-01T08:00:00Z",
    }
    value.update(overrides)
    return value


def relationship(
    *,
    source_id: str = "mac:AA:BB:CC:DD:EE:01",
    target_id: str = "mac:AA:BB:CC:DD:EE:02",
    **overrides,
):
    value = {
        "scope": SCOPE,
        "source_id": source_id,
        "target_id": target_id,
        "kind": "Physical link",
        "confidence": "CONFIRMED",
        "evidence": ["LLDP snapshot"],
        "observed_at": "2026-09-01T08:00:00Z",
        "source_port": "Gi1/0/1",
        "target_port": "eth0",
        "protocol": "LLDP",
    }
    value.update(overrides)
    return value


def report(
    *,
    generated_at: str = "2026-09-01T08:00:00Z",
    scope: str = SCOPE,
    schema_version: int = 2,
    score: int = 90,
    assets=None,
    relationships=None,
    findings=None,
):
    assets = [] if assets is None else assets
    relationships = [] if relationships is None else relationships
    findings = [] if findings is None else findings
    return {
        "schema_version": schema_version,
        "generated_at": generated_at,
        "scope": scope,
        "summary": {
            "assets": len(assets),
            "online_assets": sum(bool(item.get("is_online")) for item in assets),
            "offline_assets": sum(not bool(item.get("is_online")) for item in assets),
            "relationships": len(relationships),
            "timeline_events": 0,
        },
        "security_score": {
            "score": score,
            "findings": findings,
        },
        "assets": assets,
        "relationships": relationships,
        "timeline": [],
    }


def test_validation_accepts_supported_schema_versions_and_canonicalizes_scope():
    assert validate_network_report(report(schema_version=1, scope="192.168.1.25/24"))["scope"] == SCOPE
    assert validate_network_report(report(schema_version=2))["schema_version"] == 2


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(schema_version=3), "schema_version"),
        (lambda value: value.update(generated_at="2026-09-01T08:00:00"), "timezone"),
        (lambda value: value.update(scope="fd00::/64"), "IPv4"),
        (lambda value: value.update(assets={}), "assets"),
        (lambda value: value.update(relationships={}), "relationships"),
        (lambda value: value.update(security_score={"score": 101, "findings": []}), "0 to 100"),
        (lambda value: value.update(timeline={}), "timeline"),
    ],
)
def test_validation_rejects_invalid_report_shape(mutator, message):
    value = report()
    mutator(value)
    with pytest.raises(SnapshotReportError, match=message):
        validate_network_report(value)


def test_validation_rejects_duplicate_assets_invalid_ip_ports_and_relationships():
    duplicated = asset()
    with pytest.raises(SnapshotReportError, match="Duplicate asset_id"):
        validate_network_report(report(assets=[duplicated, dict(duplicated)]))

    with pytest.raises(SnapshotReportError, match="ip is invalid"):
        validate_network_report(report(assets=[asset(ip=None)]))
    with pytest.raises(SnapshotReportError, match="outside"):
        validate_network_report(report(assets=[asset(ip="10.0.0.8")]))
    with pytest.raises(SnapshotReportError, match="invalid port"):
        validate_network_report(report(assets=[asset(open_ports=[0, 443])]))
    with pytest.raises(SnapshotReportError, match="strings only"):
        validate_network_report(report(assets=[asset(services=["SMB", 22])]))

    link = relationship()
    with pytest.raises(SnapshotReportError, match="Duplicate relationship"):
        validate_network_report(report(relationships=[link, dict(link)]))
    with pytest.raises(SnapshotReportError, match="source_id"):
        validate_network_report(report(relationships=[relationship(source_id="")]))


def test_json_and_zip_snapshots_load_without_extracting_other_members(tmp_path):
    value = report(assets=[asset()])
    json_path = tmp_path / "baseline.json"
    json_path.write_text(json.dumps(value), encoding="utf-8")
    assert load_network_report(json_path)["assets"][0]["asset_id"] == value["assets"][0]["asset_id"]

    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps(value))
        archive.writestr("ignored.txt", "not extracted")
    assert load_network_report(zip_path)["scope"] == SCOPE
    assert not (tmp_path / "ignored.txt").exists()


def test_loader_rejects_unknown_invalid_missing_and_oversized_snapshots(tmp_path, monkeypatch):
    with pytest.raises(SnapshotReportError, match=".json or .zip"):
        load_network_report(tmp_path / "snapshot.txt")

    broken = tmp_path / "broken.json"
    broken.write_text("{broken", encoding="utf-8")
    with pytest.raises(SnapshotReportError, match="invalid JSON"):
        load_network_report(broken)

    missing = tmp_path / "missing.zip"
    with zipfile.ZipFile(missing, "w") as archive:
        archive.writestr("other.json", "{}")
    with pytest.raises(SnapshotReportError, match="report.json"):
        load_network_report(missing)

    monkeypatch.setattr(comparison, "MAX_REPORT_BYTES", 4)
    oversized = tmp_path / "large.json"
    oversized.write_text("{}   ", encoding="utf-8")
    with pytest.raises(SnapshotReportError, match="limit"):
        load_network_report(oversized)


def test_compare_reports_tracks_assets_score_and_meaningful_changes():
    baseline = report(
        score=91,
        findings=["legacy finding"],
        assets=[
            asset(),
            asset(
                "mac:AA:BB:CC:DD:EE:02",
                "192.168.1.20",
                mac="AA:BB:CC:DD:EE:02",
                hostname="old-pc.local",
                vendor="Dell",
                kind="PC",
                services=["HTTPS"],
                open_ports=[443],
            ),
        ],
    )
    current = report(
        generated_at="2026-09-01T09:00:00Z",
        score=78,
        findings=["new cleartext exposure"],
        assets=[
            asset(
                ip="192.168.1.11",
                vendor="QNAP",
                risk="MEDIUM",
                is_online=False,
                classification_confidence=65,
                services=["HTTP", "SMB"],
                open_ports=[80, 445],
                last_seen="2026-09-01T09:00:00Z",
            ),
            asset(
                "mac:AA:BB:CC:DD:EE:03",
                "192.168.1.30",
                mac="AA:BB:CC:DD:EE:03",
                hostname="camera.local",
                vendor="Reolink",
                kind="Camera",
                services=["RTSP"],
                open_ports=[554],
            ),
        ],
    )

    result = compare_network_reports(baseline, current)

    assert [item.asset_id for item in result.added_assets] == ["mac:AA:BB:CC:DD:EE:03"]
    assert [item.asset_id for item in result.removed_assets] == ["mac:AA:BB:CC:DD:EE:02"]
    assert [item.asset_id for item in result.changed_assets] == ["mac:AA:BB:CC:DD:EE:01"]
    details = result.changed_assets[0].details
    assert "IP: 192.168.1.10 → 192.168.1.11" in details
    assert "Vendor: Synology → QNAP" in details
    assert "Risk: LOW → MEDIUM" in details
    assert "Status: Online → Offline" in details
    assert "Classification confidence: 80 → 65" in details
    assert "Ports opened: 80" in details
    assert "Ports closed: 443" in details
    assert "Services added: HTTP" in details
    assert "Services removed: HTTPS" in details
    assert result.security_score_delta == -13
    assert result.findings_added == ("new cleartext exposure",)
    assert result.findings_removed == ("legacy finding",)


def test_compare_reports_ignores_timestamp_only_churn_and_supports_schema1_without_confidence():
    before_asset = asset(last_seen="2026-09-01T08:00:00Z", last_change="2026-09-01T08:00:00Z")
    after_asset = asset(last_seen="2026-09-01T09:00:00Z", last_change="2026-09-01T09:00:00Z")
    before_asset.pop("classification_confidence")
    after_asset.pop("classification_confidence")

    result = compare_network_reports(
        report(schema_version=1, assets=[before_asset]),
        report(schema_version=2, generated_at="2026-09-01T09:00:00Z", assets=[after_asset]),
    )

    assert result.unchanged_assets == 1
    assert not result.changed_assets


def test_compare_reports_tracks_relationship_add_remove_change_and_ignores_observed_time():
    changed_before = relationship(target_id="mac:AA:BB:CC:DD:EE:03")
    changed_after = relationship(
        target_id="mac:AA:BB:CC:DD:EE:03",
        confidence="INFERRED",
        evidence=["MAC table"],
        observed_at="2026-09-01T09:00:00Z",
    )
    unchanged_before = relationship(target_id="mac:AA:BB:CC:DD:EE:04")
    unchanged_after = dict(unchanged_before, observed_at="2026-09-01T09:00:00Z")

    result = compare_network_reports(
        report(
            relationships=[
                relationship(target_id="mac:AA:BB:CC:DD:EE:02"),
                changed_before,
                unchanged_before,
            ]
        ),
        report(
            generated_at="2026-09-01T09:00:00Z",
            relationships=[
                changed_after,
                unchanged_after,
                relationship(target_id="mac:AA:BB:CC:DD:EE:05"),
            ],
        ),
    )

    assert len(result.added_relationships) == 1
    assert len(result.removed_relationships) == 1
    assert len(result.changed_relationships) == 1
    assert result.unchanged_relationships == 1
    assert "Confidence: CONFIRMED → INFERRED" in result.changed_relationships[0].details
    assert "Evidence added: MAC table" in result.changed_relationships[0].details
    assert "Evidence removed: LLDP snapshot" in result.changed_relationships[0].details


def test_compare_rejects_different_scopes():
    with pytest.raises(SnapshotReportError, match="scopes differ"):
        compare_network_reports(report(), report(scope="10.0.0.0/24"))


def test_formatter_summarizes_changes_and_identical_snapshots():
    changed = compare_network_reports(
        report(score=90, findings=["old"], assets=[asset()]),
        report(
            generated_at="2026-09-01T09:00:00Z",
            score=94,
            findings=["new"],
            assets=[asset(risk="MEDIUM")],
        ),
    )
    text = format_snapshot_comparison(changed)
    assert "Security score: 90 → 94 (+4)" in text
    assert "Changed assets" in text
    assert "New security findings" in text
    assert "Resolved security findings" in text

    identical = compare_network_reports(report(), report(generated_at="2026-09-01T09:00:00Z"))
    assert "No meaningful state changes were detected." in format_snapshot_comparison(identical)
