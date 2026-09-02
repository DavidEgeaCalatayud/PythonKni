from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_preserves_direct_tag_and_controlled_branch_entry_points():
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert '- "v*.*.*"' in content
    assert '- "release/v*.*.*"' in content
    assert '- "release-retry/v*.*.*"' in content
    assert "id: release_meta" in content
    assert "^release/(v\\d+\\.\\d+\\.\\d+)$" in content
    assert "^release-retry/(v\\d+\\.\\d+\\.\\d+)$" in content
    assert "^v\\d+\\.\\d+\\.\\d+$" in content


def test_release_bootstrap_and_recovery_preserve_immutable_tag_source():
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert 'Get-Content "pyproject.toml" -Raw' in content
    assert "$mainHead -ne $env:GITHUB_SHA" in content
    assert 'git rev-parse -q --verify "refs/tags/$tag^{commit}"' in content
    assert 'git push origin "refs/tags/$tag"' in content
    assert "refusing to move it" in content
    assert "Release recovery requires existing tag $tag" in content
    assert "git merge-base --is-ancestor $releaseCommit origin/main" in content
    assert "recovery=$($recovery.ToString().ToLowerInvariant())" in content
    assert "git checkout --detach $env:RELEASE_COMMIT" in content
    assert "does not match tagged source version" in content


def test_release_outputs_drive_safe_packaging_artifact_and_publication():
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    release_output = "steps.release_meta.outputs.tag"
    assert content.count(release_output) >= 4
    assert "RELEASE_TAG: ${{ steps.release_meta.outputs.tag }}" in content
    assert "PythonKni-${{ steps.release_meta.outputs.tag }}-windows-x64" in content
    assert 'cmd /c "gh release view $tag >nul 2>&1"' in content
    assert "gh release view $tag *> $null" not in content
    assert "gh release create $tag" in content
    assert "gh release upload $tag" in content
    assert "--verify-tag" in content


def test_release_installer_is_required_for_new_sources_and_optional_for_historical_recovery():
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "id: installer_support" in content
    assert "RELEASE_RECOVERY: ${{ steps.release_meta.outputs.recovery }}" in content
    assert "Release source is missing the Windows installer pipeline" in content
    assert "steps.installer_support.outputs.enabled == 'true'" in content
    assert ".\\scripts\\build_windows_installer.ps1" in content
    assert "-ExpectedTag $env:RELEASE_TAG" in content
    assert ".\\scripts\\smoke_test_windows_installer.ps1" in content
    assert "PythonKni-$tag-windows-x64-setup.exe" in content
    assert "PythonKni-$tag-windows-x64-setup.sha256" in content
    assert "$installer $installerChecksum --clobber" in content
    assert "$installer $installerChecksum --title" in content
