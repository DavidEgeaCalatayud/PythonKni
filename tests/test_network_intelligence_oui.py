from __future__ import annotations

from pythonkni.network_intelligence.oui import (
    DEFAULT_OUI_REGISTRY,
    is_globally_administered_unicast,
    load_oui_registry,
    lookup_mac_vendor,
    normalize_mac,
)


def test_normalize_mac_accepts_common_eui48_notations():
    expected = "00:11:32:AA:BB:CC"
    assert normalize_mac("00:11:32:aa:bb:cc") == expected
    assert normalize_mac("00-11-32-AA-BB-CC") == expected
    assert normalize_mac("001132AABBCC") == expected
    assert normalize_mac("0011.32AA.BBCC") == expected


def test_normalize_mac_rejects_unknown_and_invalid_values():
    for value in (None, "", "Unknown", "N/A", "00:00:00:00:00:00", "bad-mac"):
        assert normalize_mac(value) is None


def test_randomized_multicast_and_broadcast_addresses_are_not_attributed():
    assert is_globally_administered_unicast("00:11:32:AA:BB:CC") is True
    assert is_globally_administered_unicast("02:11:32:AA:BB:CC") is False
    assert is_globally_administered_unicast("01:11:32:AA:BB:CC") is False
    assert is_globally_administered_unicast("FF:FF:FF:FF:FF:FF") is False
    assert lookup_mac_vendor("02:11:32:AA:BB:CC") is None


def test_bundled_registry_resolves_priority_network_vendors_offline():
    assert DEFAULT_OUI_REGISTRY.is_file()
    registry = load_oui_registry()
    assert len(registry) >= 100
    assert lookup_mac_vendor("00:11:32:AA:BB:CC") == "Synology"
    assert lookup_mac_vendor("24:5E:BE:00:00:01") == "QNAP"
    assert lookup_mac_vendor("0C:75:D2:12:34:56") == "Hikvision"
    assert lookup_mac_vendor("EC:71:DB:12:34:56") == "Reolink"
    assert lookup_mac_vendor("F0:9F:C2:12:34:56") == "Ubiquiti"
    assert lookup_mac_vendor("B8:27:EB:12:34:56") == "Raspberry Pi"


def test_custom_registry_is_supported_without_external_lookups():
    registry = {"001122": "Example Vendor"}
    assert lookup_mac_vendor("00:11:22:33:44:55", registry=registry) == "Example Vendor"
    assert lookup_mac_vendor("00:11:23:33:44:55", registry=registry) is None


def test_registry_loader_ignores_malformed_rows_and_missing_files(tmp_path):
    source = tmp_path / "oui.csv"
    source.write_text(
        "prefix,vendor\n00-11-22,Good Vendor\nINVALID,Bad Vendor\n00-11-23,\n",
        encoding="utf-8",
    )
    assert load_oui_registry(source) == {"001122": "Good Vendor"}
    assert load_oui_registry(tmp_path / "missing.csv") == {}
