import pytest

from tools.network_tool import validate_port_range


def test_validate_port_range_accepts_valid_range():
    assert validate_port_range("20-80") == (20, 80)


@pytest.mark.parametrize("value", ["", "abc", "80", "90-20", "0-10", "1-70000"])
def test_validate_port_range_rejects_invalid_ranges(value):
    with pytest.raises(ValueError):
        validate_port_range(value)
