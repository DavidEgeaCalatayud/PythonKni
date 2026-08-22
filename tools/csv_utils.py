from __future__ import annotations

from collections.abc import Iterable
from typing import Any


CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")
CSV_LEADING_WHITESPACE = " \t\r\n"


def safe_csv_cell(value: Any) -> Any:
    """Neutralize spreadsheet formulas while preserving non-string values.

    Excel and similar applications may interpret text beginning with =, +, - or @
    as a formula. Leading whitespace is ignored for detection so values such as
    ``"  =SUM(...)"`` cannot bypass the protection. Prefixing an apostrophe keeps
    the original content visible while forcing spreadsheet applications to treat
    the cell as text.
    """
    if not isinstance(value, str):
        return value

    candidate = value.lstrip(CSV_LEADING_WHITESPACE)
    if candidate.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_csv_row(values: Iterable[Any]) -> list[Any]:
    """Return a CSV row with every untrusted string cell neutralized."""
    return [safe_csv_cell(value) for value in values]
