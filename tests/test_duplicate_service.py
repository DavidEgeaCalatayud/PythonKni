from tools.duplicate_tool import find_duplicates, hash_file


def test_hash_file_returns_none_for_missing_file(tmp_path):
    assert hash_file(tmp_path / "missing.txt") is None


def test_hash_file_is_stable_for_same_content(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("same content", encoding="utf-8")
    second.write_text("same content", encoding="utf-8")

    assert hash_file(first) == hash_file(second)


def test_find_duplicates_groups_files_with_same_hash(tmp_path):
    original = tmp_path / "a.txt"
    duplicate = tmp_path / "b.txt"
    unique = tmp_path / "c.txt"

    original.write_text("repeat", encoding="utf-8")
    duplicate.write_text("repeat", encoding="utf-8")
    unique.write_text("different", encoding="utf-8")

    duplicates = find_duplicates(tmp_path)

    assert len(duplicates) == 1
    duplicate_paths = next(iter(duplicates.values()))
    assert {original.as_posix(), duplicate.as_posix()} == {
        path.replace("\\", "/") for path in duplicate_paths
    }
