# Physical network evidence

PythonKni can model physical attachment evidence without pretending that logical LAN membership proves cabling or switch-port topology.

This layer is intentionally import-driven. It does not probe managed switches, guess SNMP credentials, inject traffic, or discover physical links by attacking the network. The input is an administrative snapshot exported from infrastructure the operator is authorized to inspect.

## Supported evidence

Version 1 accepts:

- `LLDP`: an administrative LLDP neighbor export.
- `MAC_TABLE`: an administrative forwarding/MAC-table export. A source port is mandatory because the useful physical fact is that the target identity was observed behind that managed port.

## Confidence

A physical observation is stored as `RelationshipKind.PHYSICAL_LINK`.

- `CONFIRMED`: both endpoints resolve to inventory assets through a strong identifier (`asset_id` or MAC address).
- `INFERRED`: at least one endpoint resolves only through its IPv4 address.
- rejected with a warning: identifiers conflict, an endpoint is missing from inventory, the link loops to the same asset, the protocol is unsupported, or required port evidence is absent.

`CONFIRMED` means the imported administrative snapshot supports that attachment. It does not prove cable integrity, current link state after the snapshot timestamp, or an unobserved intermediate device.

## Snapshot format

```json
{
  "version": 1,
  "scope": "192.168.1.0/24",
  "observed_at": "2026-09-01T00:00:00Z",
  "links": [
    {
      "protocol": "LLDP",
      "source": {
        "mac": "AA:BB:CC:DD:EE:02",
        "port": "Gi1/0/1"
      },
      "target": {
        "mac": "AA:BB:CC:DD:EE:30",
        "port": "eth0"
      },
      "evidence": [
        "exported from managed infrastructure"
      ]
    }
  ]
}
```

Each endpoint requires at least one of:

- `asset_id`
- `mac`
- `ip`

When multiple identifiers are supplied they must all resolve to the same inventory asset. This is an important anti-false-positive rule.

## Persistence

Physical and logical evidence have independent snapshot lifecycles:

- `replace_logical()` refreshes default-gateway and LAN-membership relationships while preserving imported physical links.
- `replace_physical()` refreshes the physical snapshot while preserving logical relationships.
- `replace()` remains available for callers that intentionally want to replace the complete relationship snapshot.

SQLite migrations add `source_port`, `target_port`, and `protocol` to existing `network_relationships` databases without discarding prior relationship evidence.

## Topology

When at least one confirmed physical link exists, `NetworkTopology.physical_links_known` becomes `True` and topology edges retain:

- protocol
- source port
- target port
- confidence
- evidence

Logical relationships remain visible because they answer different questions. A confirmed physical link does not replace the default-route or LAN-membership evidence.
