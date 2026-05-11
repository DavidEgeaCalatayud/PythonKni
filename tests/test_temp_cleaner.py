from tools.temp_cleaner_tool import delete_folder_contents


def test_delete_folder_contents_returns_structured_result_for_missing_folder(tmp_path):
    result = delete_folder_contents(tmp_path / "missing")

    assert result.deleted == 0
    assert result.failed == 0
    assert result.errors == []


def test_delete_folder_contents_counts_deleted_files(tmp_path):
    folder = tmp_path / "temp"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "a.txt").write_text("a", encoding="utf-8")
    (nested / "b.txt").write_text("b", encoding="utf-8")

    result = delete_folder_contents(folder)

    assert result.deleted == 3
    assert result.failed == 0
