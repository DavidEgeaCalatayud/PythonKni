import subprocess
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pythonkni.core.tasks import WorkerCancelled
from pythonkni.wifi import service as wifi_service


def test_profile_helpers_cover_empty_and_missing_values():
    assert wifi_service._parse_profiles("line without separator") == []
    root = ET.fromstring("<WLANProfile><name /></WLANProfile>")
    assert wifi_service._profile_name_from_xml(root) is None
    assert wifi_service._key_material_from_xml(root) is None

    namespaced = ET.fromstring(
        '<WLANProfile xmlns="urn:test"><name>Office</name><keyMaterial /></WLANProfile>'
    )
    assert wifi_service._profile_name_from_xml(namespaced) == "Office"
    assert wifi_service._key_material_from_xml(namespaced) is None


def test_export_requires_matching_xml(monkeypatch, tmp_path):
    def fake_run(args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS):
        del timeout
        export_dir = Path(
            next(value.removeprefix("folder=") for value in args if value.startswith("folder="))
        )
        (export_dir / "wrong.xml").write_text(
            "<WLANProfile><name>Other</name></WLANProfile>", encoding="utf-8"
        )
        return ""

    monkeypatch.setattr(wifi_service, "_run_netsh", fake_run)

    with pytest.raises(ValueError, match="Office"):
        wifi_service._read_exported_password("Office", tmp_path)


def test_profile_without_key_reports_no_password(monkeypatch, tmp_path):
    def fake_run(args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS):
        del timeout
        export_dir = Path(
            next(value.removeprefix("folder=") for value in args if value.startswith("folder="))
        )
        (export_dir / "profile.xml").write_text(
            "<WLANProfile><name>Office</name></WLANProfile>", encoding="utf-8"
        )
        return ""

    monkeypatch.setattr(wifi_service, "_run_netsh", fake_run)

    assert wifi_service._read_exported_password("Office", tmp_path) == "No Password"


def test_per_profile_timeout_and_parse_error_are_isolated(monkeypatch):
    monkeypatch.setattr(
        wifi_service,
        "_run_netsh",
        lambda _args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS: (
            "All User Profile : Office\nAll User Profile : Home\n"
        ),
    )
    responses = iter(
        [
            subprocess.TimeoutExpired("netsh", 10),
            ET.ParseError("invalid xml"),
        ]
    )

    def fake_read(_profile, _root):
        raise next(responses)

    monkeypatch.setattr(wifi_service, "_read_exported_password", fake_read)

    assert wifi_service.get_wifi_profiles() == [
        ("Office", "Timeout retrieving"),
        ("Home", "Error retrieving"),
    ]


def test_generic_list_error_is_reported(monkeypatch):
    monkeypatch.setattr(
        wifi_service,
        "_run_netsh",
        lambda _args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS: (_ for _ in ()).throw(
            RuntimeError("netsh exploded")
        ),
    )

    assert wifi_service.get_wifi_profiles() == [("Error", "netsh exploded")]


def test_pre_cancelled_and_post_cancelled_events_raise(monkeypatch):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(WorkerCancelled):
        wifi_service.get_wifi_profiles(cancel_event=cancelled)

    event = threading.Event()

    def fake_run(_args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS):
        del timeout
        event.set()
        return ""

    monkeypatch.setattr(wifi_service, "_run_netsh", fake_run)
    with pytest.raises(WorkerCancelled):
        wifi_service.get_wifi_profiles(cancel_event=event)
