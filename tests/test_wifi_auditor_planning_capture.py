import hashlib
import subprocess
import threading
from types import SimpleNamespace

import pytest

from pythonkni.core.tasks import WorkerCancelled
from pythonkni.wifi_auditor import service
from pythonkni.wifi_auditor.models import AccessPoint


def _point(
    ssid="Office",
    bssid="aa:bb:cc:dd:ee:ff",
    authentication="WPA2-Personal",
    encryption="CCMP",
    channel=36,
    band="5 GHz",
):
    return AccessPoint(
        ssid,
        bssid,
        authentication,
        encryption,
        80,
        channel,
        "802.11ax",
        band,
        "Infrastructure",
    )


def test_empty_inventory_gets_visibility_plan():
    plan = service.recommend_audit_plan([])
    assert [item.code for item in plan] == ["adapter-visibility-review"]
    assert plan[0].priority == 100


def test_plan_ranks_security_consistency_channel_and_evidence():
    points = [
        _point(authentication="Open", encryption="None", channel=6, band="2.4 GHz"),
        _point(bssid="aa:bb:cc:dd:ee:01", channel=6, band="2.4 GHz"),
        _point(ssid="Guest", bssid="aa:bb:cc:dd:ee:02", channel=6, band="2.4 GHz"),
        _point(ssid="Lab", bssid="aa:bb:cc:dd:ee:03", channel=6, band="2.4 GHz"),
    ]
    plan = service.recommend_audit_plan(points)
    codes = [item.code for item in plan]
    assert codes[0] == "security-policy-review"
    assert "ssid-consistency-review" in codes
    assert "channel-planning-review" in codes
    assert "offline-capture-review" in codes
    assert codes[-1] == "evidence-baseline"
    assert [item.priority for item in plan] == sorted(
        (item.priority for item in plan), reverse=True
    )


def test_unknown_security_adds_capability_review():
    plan = service.recommend_audit_plan([_point(authentication="Unknown", encryption="Unknown")])
    assert "capability-review" in {item.code for item in plan}


def test_tkip_is_treated_as_legacy_even_with_wpa2():
    point = _point(encryption="TKIP")
    assert service.security_rating(point) == "Review"
    score, findings = service.analyze_access_points([point])
    assert score == 90
    assert any("heredada" in finding.title.lower() for finding in findings)


def test_parser_accepts_security_values_inside_bssid_block():
    output = """
SSID 1 : Office
    Authentication : WPA2-Personal
    Encryption : CCMP
    BSSID 1 : aa:bb:cc:dd:ee:ff
         Authentication : WPA3-Personal
         Encryption : GCMP
         Signal : 77%
         Channel : 149
"""
    [point] = service.parse_networks(output)
    assert point.authentication == "WPA3-Personal"
    assert point.encryption == "GCMP"
    assert point.signal_percent == 77
    assert point.channel == 149


def test_build_report_includes_ranked_plan_in_signed_payload():
    report = service.build_report([_point()], generated_at="fixed")
    assert report.plan
    data = service.report_to_dict(report)
    assert data["schema_version"] == 2
    assert data["plan"][0]["code"] == report.plan[0].code
    assert service.verify_report_data(data)
    data["plan"][0]["title"] = "tampered"
    assert not service.verify_report_data(data)


def test_inspect_pcap_without_tshark(tmp_path, monkeypatch):
    capture = tmp_path / "sample.pcap"
    capture.write_bytes(b"\xd4\xc3\xb2\xa1payload")
    monkeypatch.setattr(service.shutil, "which", lambda name: None)

    result = service.inspect_capture(capture)

    assert result.format == "pcap"
    assert result.size_bytes == capture.stat().st_size
    assert result.sha256 == hashlib.sha256(capture.read_bytes()).hexdigest()
    assert result.eapol_frames is None
    assert result.rsn_frames is None
    assert result.analyzer == "builtin"
    assert service.capture_inspection_to_dict(result)["format"] == "pcap"


def test_inspect_pcapng_with_tshark_metadata(tmp_path, monkeypatch):
    capture = tmp_path / "sample.pcapng"
    capture.write_bytes(b"\x0a\x0d\x0d\x0adata")
    monkeypatch.setattr(service.shutil, "which", lambda name: "C:/tshark.exe")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        output = "1\n2\n" if command[command.index("-Y") + 1] == "eapol" else "9\n"
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    result = service.inspect_capture(capture)

    assert result.format == "pcapng"
    assert result.eapol_frames == 2
    assert result.rsn_frames == 1
    assert result.analyzer == "tshark"
    assert len(calls) == 2
    assert all("-r" in command for command in calls)


def test_tshark_failure_degrades_to_builtin_metadata(tmp_path, monkeypatch):
    capture = tmp_path / "sample.cap"
    capture.write_bytes(b"\xa1\xb2\xc3\xd4data")
    monkeypatch.setattr(service.shutil, "which", lambda name: "tshark")

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("tshark", 20)

    monkeypatch.setattr(service.subprocess, "run", fail)
    result = service.inspect_capture(capture)
    assert result.eapol_frames is None
    assert result.rsn_frames is None
    assert result.analyzer == "builtin"


def test_capture_validation_and_cancellation(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError):
        service.inspect_capture(tmp_path / "missing.pcap")

    invalid = tmp_path / "not-capture.bin"
    invalid.write_bytes(b"NOPE")
    with pytest.raises(ValueError, match="PCAP"):
        service.inspect_capture(invalid)

    capture = tmp_path / "cancel.pcap"
    capture.write_bytes(b"\xd4\xc3\xb2\xa1payload")
    event = threading.Event()
    event.set()
    with pytest.raises(WorkerCancelled):
        service.inspect_capture(capture, event)

    calls = {"count": 0}
    original = service._check_cancel

    def cancel_during_hash(cancel_event):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise WorkerCancelled()
        original(cancel_event)

    monkeypatch.setattr(service, "_check_cancel", cancel_during_hash)
    with pytest.raises(WorkerCancelled):
        service.inspect_capture(capture)
