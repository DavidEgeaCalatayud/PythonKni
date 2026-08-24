from pathlib import Path

import pytest

from pythonkni.archive import service


class FakeWorker:
    def check_cancelled(self):
        return None

    def report_progress(self, _payload):
        return None


def test_legacy_py7zr_fails_closed_only_for_streaming_extraction(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "HAS_STREAMING_7Z_FACTORY", False)
    destination = tmp_path / "out"

    with pytest.raises(RuntimeError, match=r"py7zr >= 1\.0\.0"):
        service.extract_7z_task(FakeWorker(), Path("missing.7z"), destination)

    assert not destination.exists()


def test_streaming_requirement_is_noop_when_supported(monkeypatch):
    monkeypatch.setattr(service, "HAS_STREAMING_7Z_FACTORY", True)

    service._require_streaming_7z_factory()
