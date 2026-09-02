from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_DEFINITION = ROOT / "installer" / "PythonKni.iss"
BUILD_SCRIPT = ROOT / "scripts" / "build_windows_installer.ps1"
SMOKE_SCRIPT = ROOT / "scripts" / "smoke_test_windows_installer.ps1"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_inno_setup_definition_is_per_user_and_creates_standard_shell_entries():
    content = INSTALLER_DEFINITION.read_text(encoding="utf-8")

    assert "PrivilegesRequired=lowest" in content
    assert "DefaultDirName={localappdata}\\Programs\\{#MyAppName}" in content
    assert "DefaultGroupName={#MyAppName}" in content
    assert 'Source: "{#SourceDir}\\*"' in content
    assert 'Name: "{group}\\PythonKni"' in content
    assert 'Name: "{group}\\Uninstall PythonKni"' in content
    assert "UninstallDisplayIcon={app}\\PythonKni.exe" in content


def test_installer_build_is_version_bound_and_uses_preinstalled_inno_setup_only():
    content = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'Get-Content -LiteralPath $projectPath -Raw' in content
    assert 'if ($ExpectedTag -and $ExpectedTag -ne "v$version")' in content
    assert 'Get-Command "ISCC.exe"' in content
    assert 'Inno Setup 6\\ISCC.exe' in content
    assert '"/DAppVersion=$version"' in content
    assert '"/DSourceDir=$bundleDir"' in content
    assert "Get-FileHash -LiteralPath $installer -Algorithm SHA256" in content
    assert "choco" not in content.lower()
    assert "winget" not in content.lower()
    assert "invoke-webrequest" not in content.lower()


def test_installer_smoke_exercises_install_run_uninstall_and_cleanup():
    content = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert '"/VERYSILENT"' in content
    assert '"/SUPPRESSMSGBOXES"' in content
    assert '"--smoke-test"' in content
    assert '"unins000.exe"' in content
    assert "Start Menu shortcut was not created" in content
    assert "Per-user uninstall registration was not created" in content
    assert "install directory still exists" in content
    assert "Start Menu shortcut still exists" in content
    assert "uninstall registration still exists" in content
    assert "already registered for the current user" in content


def test_ci_builds_smokes_and_retains_installer_outputs():
    content = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "Build Windows installer" in content
    assert ".\\scripts\\build_windows_installer.ps1" in content
    assert "Smoke test installed application" in content
    assert ".\\scripts\\smoke_test_windows_installer.ps1" in content
    assert "dist/PythonKni-windows-x64-setup.exe" in content
    assert "dist/PythonKni-windows-x64-setup.sha256" in content
