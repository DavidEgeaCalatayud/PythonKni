from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nerva_lock_is_exact_official_windows_release_pin():
    lock = json.loads((ROOT / "third_party" / "nerva.lock.json").read_text(encoding="utf-8"))

    assert lock["name"] == "Nerva"
    assert lock["version"] == "1.69.4"
    assert lock["tag"] == "v1.69.4"
    assert lock["platform"] == "windows_amd64"
    assert lock["license"] == "Apache-2.0"
    assert lock["archive"] == "nerva_1.69.4_windows_amd64.zip"
    assert lock["url"] == (
        "https://github.com/praetorian-inc/nerva/releases/download/"
        "v1.69.4/nerva_1.69.4_windows_amd64.zip"
    )
    assert lock["sha256"] == "59e59eb54c8c5c581031387a0aa23c98983db94301e811f3c9b1802a05fc97f7"


def test_fetch_script_verifies_hash_before_extracting_and_never_uses_latest():
    script = (ROOT / "scripts" / "fetch_nerva.ps1").read_text(encoding="utf-8")

    assert "Get-FileHash" in script
    assert "-Algorithm SHA256" in script
    assert "Expand-Archive" in script
    assert script.index("Get-FileHash") < script.index("Expand-Archive")
    assert "praetorian-inc/nerva/releases/download" in script
    assert "@latest" not in script
    assert "/latest" not in script


def test_fetch_script_requires_license_before_publishing_staged_engine():
    script = (ROOT / "scripts" / "fetch_nerva.ps1").read_text(encoding="utf-8")

    assert '$targetLicense = Join-Path $targetDir "LICENSE"' in script
    assert "does not contain a distributable LICENSE file" in script
    assert "Copy-Item -LiteralPath $licenseFile.FullName -Destination $targetLicense" in script
    assert script.index("$null -eq $licenseFile") < script.index(
        "Copy-Item -LiteralPath $engine.FullName"
    )


def test_generated_nerva_runtime_directory_is_gitignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "third_party/nerva/" in ignore.splitlines()
