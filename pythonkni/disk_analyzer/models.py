from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiskItem:
    path: str
    name: str
    item_type: str
    size: int
