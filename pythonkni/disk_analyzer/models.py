from __future__ import annotations
import csv
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiskItem:
    path: str
    name: str
    item_type: str
    size: int
