from __future__ import annotations

import json
import time

from pythonkni.network_intelligence.oui import load_oui_registry, lookup_mac_vendor

LOOKUP_CASES = (
    ("00:11:32:AA:BB:CC", "Synology"),
    ("24:5E:BE:11:22:33", "QNAP"),
    ("0C:75:D2:AA:BB:CC", "Hikvision"),
    ("74:C9:29:AA:BB:CC", "Dahua"),
    ("F0:9F:C2:AA:BB:CC", "Ubiquiti"),
    ("02:00:00:00:00:01", None),
    ("FF:FF:FF:FF:FF:FF", None),
)
LOOKUPS = 100_000


def main() -> None:
    registry = load_oui_registry()
    if not registry:
        raise SystemExit("OUI benchmark cannot run with an empty registry.")

    for mac, expected in LOOKUP_CASES:
        actual = lookup_mac_vendor(mac, registry=registry)
        if actual != expected:
            raise SystemExit(
                f"OUI benchmark preflight failed for {mac}: expected {expected!r}, got {actual!r}."
            )

    # Warm the Python/runtime path before timing. The benchmark is informational:
    # CI must fail on correctness regressions, not on shared-runner timing jitter.
    for mac, _ in LOOKUP_CASES:
        lookup_mac_vendor(mac, registry=registry)

    resolved = 0
    started = time.perf_counter()
    for index in range(LOOKUPS):
        mac, _ = LOOKUP_CASES[index % len(LOOKUP_CASES)]
        if lookup_mac_vendor(mac, registry=registry) is not None:
            resolved += 1
    elapsed = time.perf_counter() - started

    metrics = {
        "benchmark": "network-intelligence-oui-v1",
        "registry_entries": len(registry),
        "lookups": LOOKUPS,
        "resolved": resolved,
        "elapsed_seconds": round(elapsed, 6),
        "lookups_per_second": round(LOOKUPS / elapsed, 2) if elapsed else None,
        "timing_gate": False,
    }
    print(json.dumps(metrics, sort_keys=True))


if __name__ == "__main__":
    main()
