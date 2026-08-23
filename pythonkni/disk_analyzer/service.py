from __future__ import annotations
from .models import (
    DiskItem,
)
from tools.csv_utils import safe_csv_row
import csv
import os
from dataclasses import dataclass
from pathlib import Path
from tools.theme_manager import ThemeManager
from .models import (
    DiskItem,
)

def format_bytes(num_bytes: int | float) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"
def directory_size(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not Path(root, d).is_symlink()]
        for file_name in files:
            try:
                file_path = Path(root) / file_name
                if not file_path.is_symlink():
                    total += file_path.stat().st_size
            except OSError:
                continue
    return total
def analyze_directory(path: Path, limit: int = 100) -> list[DiskItem]:
    items: list[DiskItem] = []

    with os.scandir(path) as entries:
        for entry in entries:
            try:
                entry_path = Path(entry.path)
                if entry.is_symlink():
                    continue

                if entry.is_dir(follow_symlinks=False):
                    size = directory_size(entry_path)
                    item_type = "Carpeta"
                elif entry.is_file(follow_symlinks=False):
                    size = entry.stat(follow_symlinks=False).st_size
                    item_type = "Archivo"
                else:
                    continue

                items.append(
                    DiskItem(
                        path=str(entry_path),
                        name=entry.name,
                        item_type=item_type,
                        size=size,
                    )
                )
            except (PermissionError, OSError):
                continue

    return sorted(items, key=lambda item: item.size, reverse=True)[:limit]
