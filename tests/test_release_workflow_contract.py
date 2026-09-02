from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_preserves_direct_tag_and_controlled_branch_entry_points():
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert '- "v*.*.*"' in content
    assert '- "release/v*.*.*"' in content
    assert "id: release_meta" in content
    assert "^release/(v\\d+\\.\\d+\\.\\d+)$" in content
    assert "^v\\d+\\.\\d+\\.\\d+$" in content


def test_release_bootstrap_is_bound_to_main_version_and_immutable_tag():
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert 'Get-Content "pyproject.toml" -Raw' in content
    assert "git merge-base --is-ancestor $env:GITHUB_SHA origin/main" in content
    assert "$mainHead -ne $env:GITHUB_SHA" in content
    assert 'git rev-parse -q --verify "refs/tags/$tag^{commit}"' in content
    assert 'git push origin "refs/tags/$tag"' in content
    assert "refusing to move it" in content


def test_release_outputs_drive_packaging_artifact_and_publication():
    content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    release_output = "steps.release_meta.outputs.tag"
    assert content.count(release_output) >= 4
    assert 'RELEASE_TAG: ${{ steps.release_meta.outputs.tag }}' in content
    assert 'PythonKni-${{ steps.release_meta.outputs.tag }}-windows-x64' in content
    assert 'gh release create $tag' in content
    assert "--verify-tag" in content
