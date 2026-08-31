import json
import subprocess
import threading

import pytest

import pythonkni.wifi_auditor.service as service
from pythonkni.core.tasks import WorkerCancelled
from pythonkni.wifi_auditor.models import AccessPoint


ENGLISH_SCAN = """
SSID 1 : Office
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : AA:BB:CC:DD:EE:01
         Signal             : 84%
         Radio type         : 802.11ax
         Channel            : 36
    BSSID 2                 : AA:BB:CC:DD:EE:02
         Signal             : 62%
         Radio type         : 802.11ax
         Channel            : 36
SSID 2 : Guest
    Authentication          : Open
    Encryption              : None
    BSSID 1                 : 11:22:33:44:55:66
         Signal             : 40%
         Channel            : 6
"""


SPANISH_SCAN = """
SSID 1 : Casa
    Tipo de red             : Infraestructura
    Autenticación           : WPA3-Personal
    Cifrado                 : CCMP
    BSSID 1                 : 00:11:22:33:44:55
         Señal              : 91%
         Tipo de radio      : 802.11ax
         Banda              : 6 GHz
         Canal              : 197
"""


def _ap(ssid="Office", auth="WPA2-Personal", encryption="CCMP", channel=36, bssid="aa"):
    return AccessPoint(ssid, bssid, auth, encryption, 80, channel, "802.11ax", "5 GHz", "Infrastructure")


def test_parse_networks_reads_multiple_bssid_and_security():
    points = service.parse_networks(ENGLISH_SCAN)
    assert len(points) == 3
    assert points[0].ssid == "Office"
    assert points[0].bssid == "aa:bb:cc:dd:ee:01"
    assert points[0].signal_percent == 84
    assert points[0].channel == 36
    assert points[0].band == "5 GHz"
    assert points[1].authentication == "WPA2-Personal"
    assert points[2].ssid == "Guest"
    assert points[2].band == "2.4 GHz"


def test_parse_networks_supports_spanish_labels_and_explicit_band():
    point = service.parse_networks(SPANISH_SCAN)[0]
    assert point.ssid == "Casa"
    assert point.authentication == "WPA3-Personal"
    assert point.signal_percent == 91
    assert point.radio_type == "802.11ax"
    assert point.band == "6 GHz"


def test_parse_networks_handles_hidden_and_missing_optional_values():
    points = service.parse_networks("SSID 1 :\n Authentication : WPA2\n BSSID 1 : AA\n")
    assert points[0].ssid == "<hidden>"
    assert points[0].channel is None
    assert points[0].signal_percent is None
    assert points[0].band == "Unknown"


def test_parse_networks_ignores_unrelated_lines_and_flushes_between_ssids():
    output = "header\nSSID 1 : A\nBSSID 1 : 01\nSSID 2 : B\nBSSID 1 : 02\n"
    points = service.parse_networks(output)
    assert [point.ssid for point in points] == ["A", "B"]


def test_band_inference_boundaries():
    assert service._band(None) == "Unknown"
    assert service._band(1) == "2.4 GHz"
    assert service._band(14) == "2.4 GHz"
    assert service._band(36) == "5 GHz"
    assert service._band(177) == "5 GHz"
    assert service._band(197) == "6 GHz / other"
    assert service._band(36, "5 GHz explicit") == "5 GHz explicit"


def test_number_and_normalization_helpers():
    assert service._number("84%") == 84
    assert service._number("none") is None
    assert service._normalize(" Autenticación ") == "autenticacion"


def test_scan_access_points_calls_netsh(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_run_netsh", lambda args: calls.append(args) or ENGLISH_SCAN)
    points = service.scan_access_points()
    assert calls == [["wlan", "show", "networks", "mode=bssid"]]
    assert len(points) == 3


def test_scan_access_points_honors_pre_cancel(monkeypatch):
    event = threading.Event()
    event.set()
    called = []
    monkeypatch.setattr(service, "_run_netsh", lambda args: called.append(args) or "")
    with pytest.raises(WorkerCancelled):
        service.scan_access_points(event)
    assert called == []


def test_scan_access_points_honors_post_cancel(monkeypatch):
    event = threading.Event()

    def fake_run(_args):
        event.set()
        return ENGLISH_SCAN

    monkeypatch.setattr(service, "_run_netsh", fake_run)
    with pytest.raises(WorkerCancelled):
        service.scan_access_points(event)


def test_run_netsh_uses_timeout_and_returns_stdout(monkeypatch):
    captured = {}

    class Result:
        stdout = "ok"

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert service._run_netsh(["wlan", "show"]) == "ok"
    assert captured["args"] == ["netsh", "wlan", "show"]
    assert captured["timeout"] == service.NETSH_TIMEOUT_SECONDS
    assert captured["check"] is True


@pytest.mark.parametrize(
    ("auth", "encryption", "rating"),
    [
        ("WPA3-Personal", "CCMP", "Good"),
        ("WPA2-Personal", "CCMP", "Good"),
        ("WPA-Personal", "TKIP", "Review"),
        ("Open", "None", "Review"),
        ("Unknown", "Unknown", "Unknown"),
        ("WEP", "WEP", "Review"),
    ],
)
def test_security_rating(auth, encryption, rating):
    assert service.security_rating(_ap(auth=auth, encryption=encryption)) == rating


def test_analysis_flags_open_and_legacy_configuration():
    points = [
        _ap(ssid="Guest", auth="Open", encryption="None", bssid="01"),
        _ap(ssid="Legacy", auth="WPA-Personal", encryption="TKIP", bssid="02"),
    ]
    score, findings = service.analyze_access_points(points)
    assert score == 75
    assert {finding.severity for finding in findings} == {"high"}
    assert any("abierta" in finding.title.lower() for finding in findings)
    assert any("heredada" in finding.title.lower() for finding in findings)


def test_analysis_flags_mixed_policy_for_same_ssid():
    points = [
        _ap(ssid="Corp", auth="WPA2-Personal", bssid="01"),
        _ap(ssid="Corp", auth="Open", encryption="None", bssid="02"),
    ]
    score, findings = service.analyze_access_points(points)
    assert score == 77
    assert any("inconsistente" in finding.title.lower() for finding in findings)


def test_analysis_ignores_unknown_when_comparing_policy():
    points = [
        _ap(ssid="Corp", auth="WPA2-Personal", bssid="01"),
        _ap(ssid="Corp", auth="Unknown", encryption="Unknown", bssid="02"),
    ]
    score, findings = service.analyze_access_points(points)
    assert score == 100
    assert findings == []


def test_analysis_flags_channel_congestion():
    points = [_ap(ssid=f"N{i}", channel=36, bssid=str(i)) for i in range(4)]
    score, findings = service.analyze_access_points(points)
    assert score == 96
    finding = findings[0]
    assert finding.severity == "medium"
    assert "canal 36" in finding.title.lower()


def test_analysis_empty_snapshot_is_informational():
    score, findings = service.analyze_access_points([])
    assert score == 100
    assert findings[0].severity == "info"


def test_score_never_goes_below_zero():
    points = [_ap(ssid=f"Open{i}", auth="Open", encryption="None", bssid=str(i)) for i in range(10)]
    score, _ = service.analyze_access_points(points)
    assert score == 0


def test_build_report_is_deterministic_with_fixed_timestamp():
    points = [_ap()]
    first = service.build_report(points, generated_at="2026-08-31T12:00:00+00:00")
    second = service.build_report(points, generated_at="2026-08-31T12:00:00+00:00")
    assert first == second
    assert len(first.evidence_sha256) == 64
    assert first.limitations == service.LIMITATIONS


def test_run_audit_builds_report_from_scan(monkeypatch):
    monkeypatch.setattr(service, "scan_access_points", lambda cancel_event=None: [_ap()])
    report = service.run_audit()
    assert report.score == 100
    assert len(report.access_points) == 1


def test_report_round_trip_and_tamper_detection(tmp_path):
    report = service.build_report([_ap()], generated_at="fixed")
    path = service.export_report(tmp_path / "audit.json", report)
    assert service.verify_report_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert service.verify_report_data(data)
    data["score"] = 1
    assert not service.verify_report_data(data)


def test_verify_report_rejects_missing_digest_and_non_mapping_file(tmp_path):
    assert not service.verify_report_data({"score": 100})
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    assert not service.verify_report_file(path)
