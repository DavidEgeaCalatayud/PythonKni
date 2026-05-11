import pytest

from tools.pdf_merge_tool import parse_page_list, parse_page_spec


def test_parse_page_list_accepts_single_pages_and_ranges():
    assert parse_page_list("1,3,5-7", max_pages=10) == [0, 2, 4, 5, 6]


def test_parse_page_list_removes_duplicates_preserving_order():
    assert parse_page_list("2,1-3,2", max_pages=5) == [1, 0, 2]


def test_parse_page_list_ignores_out_of_range_pages():
    assert parse_page_list("0,1,99", max_pages=2) == [0]


def test_parse_page_list_rejects_empty_or_invalid_specs():
    with pytest.raises(ValueError):
        parse_page_list("0,99", max_pages=2)


def test_parse_page_spec_returns_groups_per_comma():
    assert parse_page_spec("1-2,4", max_pages=5) == [[0, 1], [3]]
