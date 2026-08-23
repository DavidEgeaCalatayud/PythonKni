
from tools.disk_analyzer_tool import DiskItem, Tool, analyze_directory, directory_size, format_bytes


def test_analyze_directory_sorts_by_size_and_respects_limit(tmp_path):
    (tmp_path / "small.bin").write_bytes(b"a" * 10)
    (tmp_path / "large.bin").write_bytes(b"b" * 50)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "inside.bin").write_bytes(b"c" * 30)

    items = analyze_directory(tmp_path, limit=2)

    assert [item.name for item in items] == ["large.bin", "nested"]
    assert [item.size for item in items] == [50, 30]
    assert directory_size(nested) == 30
    assert format_bytes(1024) == "1.00 KB"


def test_disk_analyzer_gui_renders_analysis_results(qtbot, tmp_path):
    (tmp_path / "one.bin").write_bytes(b"1" * 12)
    (tmp_path / "two.bin").write_bytes(b"2" * 24)

    tool = Tool()
    qtbot.addWidget(tool)
    tool.show()
    tool.current_folder = str(tmp_path)
    tool.btn_analyze.setEnabled(True)

    tool.start_analysis()
    qtbot.waitUntil(lambda: tool.btn_analyze.isEnabled(), timeout=5000)

    assert tool.table.rowCount() == 2
    assert tool.btn_export.isEnabled()
    assert "Elementos mostrados: 2" in tool.summary_label.text()
    displayed_names = {tool.table.item(row, 0).text() for row in range(tool.table.rowCount())}
    assert displayed_names == {"one.bin", "two.bin"}


def test_fill_table_keeps_raw_bytes_for_numeric_sorting(qtbot):
    tool = Tool()
    qtbot.addWidget(tool)
    items = [
        DiskItem("C:/a", "a", "Archivo", 1024),
        DiskItem("C:/b", "b", "Archivo", 10),
    ]

    tool.fill_table(items)

    assert tool.table.item(0, 3).data(0) == 1024
    assert tool.table.item(1, 3).data(0) == 10
