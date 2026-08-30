from pathlib import Path

import pytest

from scripts import check_dependency_locks


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_hashed_lock_accepts_exact_sha256_pins(tmp_path):
    lock = write(
        tmp_path / "requirements.txt",
        "example==1.2.3 \\\n"
        "    --hash=sha256:" + "a" * 64 + " \\\n"
        "    --hash=sha256:" + "b" * 64 + "\n"
        "    # via example-parent\n",
    )

    versions, hash_count = check_dependency_locks._locked_versions(lock)

    assert str(versions["example"]) == "1.2.3"
    assert hash_count == 2


def test_hashed_lock_rejects_missing_hash(tmp_path):
    lock = write(tmp_path / "requirements.txt", "example==1.2.3\n")

    with pytest.raises(ValueError, match="ningún hash SHA-256"):
        check_dependency_locks._locked_versions(lock)


def test_hashed_lock_rejects_malformed_hash(tmp_path):
    lock = write(
        tmp_path / "requirements.txt",
        "example==1.2.3 \\\n    --hash=sha256:not-a-real-hash\n",
    )

    with pytest.raises(ValueError, match="malformado"):
        check_dependency_locks._locked_versions(lock)


def test_direct_requirement_must_be_present_and_in_range(tmp_path):
    direct = write(tmp_path / "requirements.in", "example>=2,<3\n")
    lock = write(
        tmp_path / "requirements.txt",
        "example==1.2.3 \\\n    --hash=sha256:" + "c" * 64 + "\n",
    )

    with pytest.raises(ValueError, match="no satisface"):
        check_dependency_locks._validate_direct_requirements(direct, lock)
