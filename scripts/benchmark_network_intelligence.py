from __future__ import annotations

import json
import time

from pythonkni.network_intelligence.classification import score_device_classification
from pythonkni.network_intelligence.models import DeviceKind
from pythonkni.network_intelligence.oui import load_oui_registry, lookup_mac_vendor

LOOKUP_CASES = (
    ("00:11:32:AA:BB:CC", "Synology Incorporated"),
    ("24:5E:BE:11:22:33", "QNAP Systems, Inc."),
    (
        "0C:75:D2:AA:BB:CC",
        "Hangzhou Hikvision Digital Technology Co.,Ltd.",
    ),
    ("74:C9:29:AA:BB:CC", "Zhejiang Dahua Technology Co., Ltd."),
    ("F0:9F:C2:AA:BB:CC", "Ubiquiti Inc"),
    ("02:00:00:00:00:01", None),
    ("FF:FF:FF:FF:FF:FF", None),
)
MIN_REGISTRY_ENTRIES = 20_000
LOOKUPS = 100_000
CLASSIFICATIONS = 100_000


def _benchmark_oui(registry) -> dict[str, object]:
    if len(registry) < MIN_REGISTRY_ENTRIES:
        raise SystemExit(
            "OUI benchmark preflight failed: bundled registry contains "
            f"{len(registry)} entries; expected at least {MIN_REGISTRY_ENTRIES}."
        )

    for mac, expected in LOOKUP_CASES:
        actual = lookup_mac_vendor(mac, registry=registry)
        if actual != expected:
            raise SystemExit(
                f"OUI benchmark preflight failed for {mac}: expected {expected!r}, got {actual!r}."
            )

    for mac, _ in LOOKUP_CASES:
        lookup_mac_vendor(mac, registry=registry)

    resolved = 0
    started = time.perf_counter()
    for index in range(LOOKUPS):
        mac, _ = LOOKUP_CASES[index % len(LOOKUP_CASES)]
        if lookup_mac_vendor(mac, registry=registry) is not None:
            resolved += 1
    elapsed = time.perf_counter() - started
    return {
        "registry_entries": len(registry),
        "lookups": LOOKUPS,
        "resolved": resolved,
        "elapsed_seconds": round(elapsed, 6),
        "lookups_per_second": round(LOOKUPS / elapsed, 2) if elapsed else None,
    }


def _benchmark_classification() -> dict[str, object]:
    score, signals = score_device_classification(
        DeviceKind.CAMERA,
        (80, 443, 554),
        onvif=True,
        hostname_hint=True,
        vendor_hint=True,
    )
    if score != 100 or sum(signal.matched for signal in signals) != 4:
        raise SystemExit("Classification benchmark preflight produced an unexpected profile.")

    for _ in range(100):
        score_device_classification(DeviceKind.CAMERA, (80, 443, 554), onvif=True)

    checksum = 0
    started = time.perf_counter()
    for index in range(CLASSIFICATIONS):
        if index % 3 == 0:
            kind = DeviceKind.CAMERA
            ports = (554,)
            kwargs = {"onvif": True, "vendor_hint": True}
        elif index % 3 == 1:
            kind = DeviceKind.NAS
            ports = (445, 2049, 5001)
            kwargs = {"hostname_hint": True, "vendor_hint": True}
        else:
            kind = DeviceKind.ROUTER
            ports = (53, 80, 443)
            kwargs = {"gateway_signature": True}
        current_score, _signals = score_device_classification(kind, ports, **kwargs)
        checksum += current_score
    elapsed = time.perf_counter() - started
    return {
        "classifications": CLASSIFICATIONS,
        "checksum": checksum,
        "elapsed_seconds": round(elapsed, 6),
        "classifications_per_second": (round(CLASSIFICATIONS / elapsed, 2) if elapsed else None),
    }


def main() -> None:
    registry = load_oui_registry()
    if not registry:
        raise SystemExit("OUI benchmark cannot run with an empty registry.")

    metrics = {
        "benchmark": "network-intelligence-v2",
        "oui": _benchmark_oui(registry),
        "classification": _benchmark_classification(),
        "timing_gate": False,
    }
    print(json.dumps(metrics, sort_keys=True))


if __name__ == "__main__":
    main()
