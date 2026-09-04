from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_trippy_lock_is_pinned_to_verified_windows_release():
    lock = json.loads((ROOT / "third_party" / "trippy.lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == "0.13.0"
    assert lock["tag"] == "0.13.0"
    assert lock["platform"] == "x86_64-pc-windows-msvc"
    assert lock["license"] == "Apache-2.0"
    assert lock["url"].startswith(
        "https://github.com/fujiapple852/trippy/releases/download/0.13.0/"
    )
    assert lock["archive"] == "trippy-0.13.0-x86_64-pc-windows-msvc.zip"
    assert lock["sha256"] == (
        "74a184434d96eec6c7f8e4b467147c40fa8841fa3722a3ddf51267208fcbbbe6"
    )


def test_trippy_fetch_script_enforces_official_source_hash_and_contract():
    script = (ROOT / "scripts" / "fetch_trippy.ps1").read_text(encoding="utf-8")
    assert "Get-FileHash" in script
    assert "fujiapple852/trippy/releases/download" in script
    assert "trip.exe" in script
    assert "0.13.0" in script
    assert "binary_sha256" in script
    assert "check_trippy_contract.ps1" in script
    assert "archive SHA-256 mismatch" in script


def test_trippy_contract_smoke_covers_used_cli_surface():
    script = (ROOT / "scripts" / "check_trippy_contract.ps1").read_text(encoding="utf-8")
    for value in ("--version", "--mode", "--protocol", "--report-cycles", "--max-ttl"):
        assert value in script
    for protocol in ("icmp", "udp", "tcp"):
        assert protocol in script
    assert "ExpectedVersion" in script


def test_third_party_notice_records_trippy_license_and_isolation():
    notice = (ROOT / "third_party" / "NOTICE.md").read_text(encoding="utf-8")
    assert "## Trippy" in notice
    assert "Apache License 2.0" in notice
    assert "not committed" in notice
    assert "command-line JSON reporting contract" in notice


def test_pyinstaller_and_ci_package_and_verify_trippy():
    spec = (ROOT / "PythonKni.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "third_party/trippy.lock.json" in spec
    assert "third_party/trippy/trip.exe" in spec
    assert "fetch_trippy.ps1" in workflow
    assert "Verify packaged Trippy path backend" in workflow
    assert "check_trippy_contract.ps1" in workflow
    assert "third_party/trippy.lock.json" in workflow


def test_release_native_staging_cannot_silently_omit_trippy():
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    nerva_stage = (ROOT / "scripts" / "fetch_nerva.ps1").read_text(encoding="utf-8")
    package = (ROOT / "scripts" / "package_windows_bundle.ps1").read_text(encoding="utf-8")
    assert "fetch_nerva.ps1" in release
    assert "package_windows_bundle.ps1" in release
    assert "fetch_trippy.ps1" in nerva_stage
    assert "Invoke-OptionalTrippyStage" in nerva_stage
    assert "third_party\\trippy.lock.json" in package
    assert "_internal\\third_party\\trippy\\trip.exe" in package
    assert "check_trippy_contract.ps1" in package
