from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from pythonkni.infrastructure.paths import ASSETS_DIR

DEFAULT_OUI_REGISTRY = ASSETS_DIR / "network_oui_prefixes.csv"
_HEX_RE = re.compile(r"^[0-9A-F]+$")
_UNKNOWN_MACS = {
    "",
    "N/A",
    "UNKNOWN",
    "NO DISPONIBLE",
    "00:00:00:00:00:00",
    "FF:FF:FF:FF:FF:FF",
}


def normalize_mac(value: str | None) -> str | None:
    """Return a canonical EUI-48 string or None for unusable values."""
    candidate = (value or "").strip().upper()
    if candidate in _UNKNOWN_MACS:
        return None
    compact = candidate.replace(":", "").replace("-", "").replace(".", "")
    if len(compact) != 12 or not _HEX_RE.fullmatch(compact):
        return None
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def is_globally_administered_unicast(mac: str | None) -> bool:
    """Reject multicast, broadcast and locally administered/randomized MACs."""
    normalized = normalize_mac(mac)
    if normalized is None:
        return False
    first_octet = int(normalized[:2], 16)
    return first_octet & 0b11 == 0


def _normalize_prefix(value: str | None) -> str | None:
    candidate = (value or "").strip().upper()
    compact = candidate.replace(":", "").replace("-", "").replace(".", "")
    if len(compact) != 6 or not _HEX_RE.fullmatch(compact):
        return None
    return compact


@lru_cache(maxsize=8)
def _load_oui_registry(path_text: str) -> dict[str, str]:
    registry: dict[str, str] = {}
    try:
        with Path(path_text).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                prefix = _normalize_prefix(row.get("prefix"))
                vendor = (row.get("vendor") or "").strip()
                if prefix and vendor:
                    registry[prefix] = vendor
    except (OSError, csv.Error):
        return {}
    return registry


def load_oui_registry(path: str | Path = DEFAULT_OUI_REGISTRY) -> dict[str, str]:
    """Load and cache a local prefix registry. No network access is performed."""
    return _load_oui_registry(str(Path(path)))


def lookup_mac_vendor(
    mac: str | None,
    *,
    registry: dict[str, str] | None = None,
) -> str | None:
    """Resolve a globally administered EUI-48 MAC using the bundled registry."""
    normalized = normalize_mac(mac)
    if normalized is None or not is_globally_administered_unicast(normalized):
        return None
    table = registry if registry is not None else load_oui_registry()
    return table.get(normalized.replace(":", "")[:6])
