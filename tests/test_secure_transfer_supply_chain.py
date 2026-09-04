from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tailcat_lock_is_pinned_to_verified_windows_release():
    lock = json.loads((ROOT / "third_party" / "tailcat.lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == "0.5.0"
    assert lock["tag"] == "v0.5.0"
    assert lock["platform"] == "windows_amd64"
    assert lock["license"] == "BSD-3-Clause"
    assert lock["url"].startswith("https://github.com/tailscale/tailcat/releases/download/v0.5.0/")
    assert lock["sha256"] == ("47c2a22eff596dc184642779b8ba9988ca554b0f177ee1188bc4913253b18430")


def test_tailcat_fetch_script_enforces_official_source_hash_and_runtime_contract():
    script = (ROOT / "scripts" / "fetch_tailcat.ps1").read_text(encoding="utf-8")
    assert "Get-FileHash" in script
    assert "tailscale/tailcat/releases/download" in script
    assert "tailcat.exe" in script
    assert "0.5.0" in script
    assert "binary_sha256" in script
    assert "check_tailcat_contract.ps1" in script


def test_tailcat_contract_smoke_covers_used_cli_surface():
    script = (ROOT / "scripts" / "check_tailcat_contract.ps1").read_text(encoding="utf-8")
    assert "tailcat recv" in script
    assert "tailcat cp" in script
    assert "tailcat serve" in script
    assert "tailcat forward" in script
    assert "--key=new" in script
    assert "127.0.0.1" in script
    assert "ExpectedVersion" in script


def test_secure_transfer_docs_record_instability_and_safety_boundaries():
    docs = (ROOT / "docs" / "secure-transfer.md").read_text(encoding="utf-8")
    assert "does **not** guarantee API, CLI or wire-format stability" in docs
    assert "--key=new" in docs
    assert "127.0.0.1" in docs
    assert "OpenSSH Client" in docs


def test_pyinstaller_and_ci_package_and_verify_tailcat():
    spec = (ROOT / "PythonKni.spec").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "third_party/tailcat.lock.json" in spec
    assert "third_party/tailcat/tailcat.exe" in spec
    assert "fetch_tailcat.ps1" in workflow
    assert "Verify packaged Tailcat transport" in workflow
    assert "third_party/tailcat.lock.json" in workflow


def test_release_staging_cannot_silently_omit_tailcat():
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    nerva_stage = (ROOT / "scripts" / "fetch_nerva.ps1").read_text(encoding="utf-8")
    assert "fetch_nerva.ps1" in release
    assert "fetch_tailcat.ps1" in nerva_stage
    assert "Invoke-OptionalTailcatStage" in nerva_stage
