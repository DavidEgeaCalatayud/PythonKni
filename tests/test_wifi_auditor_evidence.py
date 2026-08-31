import os
from pathlib import Path

import pytest

from pythonkni.wifi_auditor import service
from pythonkni.wifi_auditor.models import AccessPoint


def _report():
    point = AccessPoint(
        "Office",
        "aa:bb:cc:dd:ee:ff",
        "WPA2-Personal",
        "CCMP",
        80,
        36,
        "802.11ax",
        "5 GHz",
        "Infrastructure",
    )
    return service.build_report([point], generated_at="fixed")


def test_export_report_replaces_destination_atomically(tmp_path):
    destination = tmp_path / "audit.json"
    destination.write_text("old", encoding="utf-8")
    service.export_report(destination, _report())
    assert destination.read_text(encoding="utf-8") != "old"
    assert service.verify_report_file(destination)
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_export_report_cleans_temp_file_when_replace_fails(tmp_path, monkeypatch):
    destination = tmp_path / "audit.json"
    destination.write_text("previous", encoding="utf-8")
    failure = OSError("replace failed")
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(failure))

    with pytest.raises(OSError, match="replace failed"):
        service.export_report(destination, _report())

    assert destination.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.glob(".audit.json.*.tmp")) == []


def test_export_report_tolerates_cleanup_failure_and_preserves_original_exception(
    tmp_path, monkeypatch
):
    destination = tmp_path / "audit.json"
    replace_failure = OSError("replace failed")
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(replace_failure))
    monkeypatch.setattr(os, "unlink", lambda *_args: (_ for _ in ()).throw(OSError("cleanup failed")))

    with pytest.raises(OSError, match="replace failed"):
        service.export_report(destination, _report())
