import csv
import io
from pathlib import Path

import pytest

from tools.csv_utils import safe_csv_cell, safe_csv_row


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+SUM(A1:A2)", "'+SUM(A1:A2)"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1:A2)", "'@SUM(A1:A2)"),
        ('  =HYPERLINK("https://example.invalid")', '\'  =HYPERLINK("https://example.invalid")'),
        ("\t+CMD", "'\t+CMD"),
    ],
)
def test_safe_csv_cell_neutralizes_formula_prefixes(value, expected):
    assert safe_csv_cell(value) == expected


def test_safe_csv_cell_preserves_normal_and_non_string_values():
    assert safe_csv_cell("normal text") == "normal text"
    assert safe_csv_cell("1-2") == "1-2"
    assert safe_csv_cell(42) == 42
    assert safe_csv_cell(None) is None


def test_safe_csv_row_is_safe_when_round_tripped_through_csv_writer():
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(safe_csv_row(["=1+1", "+2", "normal", 7]))

    output.seek(0)
    assert next(csv.reader(output, delimiter=";")) == ["'=1+1", "'+2", "normal", "7"]


@pytest.mark.parametrize(
    ("path", "function_name", "sanitizer"),
    [
        ("tools/disk_analyzer_tool.py", "def export_csv", "safe_csv_row("),
        ("tools/network_tool.py", "def export_history", "safe_csv_cell(line)"),
        ("pythonkni/startup/window.py", "def export_csv", "safe_csv_row("),
        ("pythonkni/event_viewer/window.py", "def export_csv", "safe_csv_row("),
    ],
)
def test_external_csv_exporters_use_shared_sanitizer(path, function_name, sanitizer):
    source = Path(path).read_text(encoding="utf-8")
    assert "from tools.csv_utils import" in source
    exporter = source.split(function_name, 1)[1]
    assert sanitizer in exporter
