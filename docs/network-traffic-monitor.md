# Network Traffic Monitor

The Network Traffic Monitor adds passive temporal network telemetry to PythonKni. It complements Network Explorer and Network Intelligence rather than replacing their discovery, fingerprinting or snapshot responsibilities.

```text
Network Explorer
      ↓
known hosts / ports / services
      ↓
Network Intelligence
      ↓
inventory / risks / history
      ↓
Network Traffic Monitor
      ↓
live sockets / remote hosts / temporal events
```

## What it observes

The monitor uses `psutil` to enumerate local interfaces, read per-interface byte counters and inspect local TCP/UDP sockets. A monitoring session records local/remote endpoints, socket state, PID/process name when available, inferred application protocol, endpoint scope and first-seen temporal events.

Adapter RX/TX throughput is derived from operating-system interface byte counters. Process rows deliberately represent **socket activity**, not per-process byte counters: Windows does not expose a generally reliable, unprivileged per-process network-byte counter through the interface used by PythonKni, so the UI does not manufacture one.

## Host enrichment

Reverse DNS is bounded and cached inside the worker. At most four previously unseen remote IPs are resolved in one polling cycle.

ASN enrichment is optional and disabled by default. When enabled, PythonKni sends only public remote IP addresses to RIPEstat's `network-info` endpoint and caches the returned announcing ASN(s) and prefix. At most two new ASN lookups are attempted in one polling cycle. Private/LAN addresses are never sent for ASN enrichment, and the monitor continues normally if RIPEstat is unavailable.

## Passive event model

The first milestone emits deterministic local events for:

- `new_external_connection`
- `new_remote_host`
- `new_listening_port`
- `process_network_activity`
- `traffic_spike`
- `known_asset_connection`
- `unusual_destination`

`known_asset_connection` is a read-only join against the existing Network Intelligence inventory by IP. Live traffic never creates synthetic inventory assets or rewrites asset classification/risk.

Events and periodic history samples are persisted as bounded JSONL under the PythonKni application data directory. In-memory UI history keeps the latest 300 samples; the on-disk JSONL retention is bounded independently so long-running sessions cannot grow without limit.

## Packet capture on Windows

Packet capture is a separate explicit action. On Windows systems where `pktmon` is available, PythonKni starts an OS-native NIC capture, stops only the capture session it successfully started, and converts the resulting ETL file to PCAPNG using `pktmon etl2pcap`.

The capture backend does not add Npcap, Scapy or another packet-capture runtime dependency. `pktmon` may require elevated permissions depending on the host configuration. If it is unavailable or permission is denied, live socket/traffic monitoring remains usable.

The first implementation captures NIC traffic system-wide rather than pretending `pktmon` is restricted to the adapter selected for the socket view. The UI states this explicitly.

## Safety boundary

The monitor is observational:

- no packet injection;
- no exploitation;
- no credential/default-password attempts;
- no authentication attempts;
- no TLS or payload decryption;
- no payload/credential extraction;
- no internet-wide discovery.

Protocol names are inferred from transport and common ports only; this module does not perform active service probes. Nerva remains the explicit service-intelligence path for known services.

## Architecture

```text
pythonkni/network_monitor/
├── models.py        # immutable first-party telemetry models
├── service.py       # psutil adapters/sockets, rates, DNS/ASN and bounded JSONL
├── capture.py       # optional Windows pktmon adapter
├── intelligence.py  # temporal state, aggregation, events, inventory read bridge
└── window.py        # PyQt composition and managed workers

tools/network_monitor_tool.py
```

The service/model layers remain independent from Qt. The long-running monitor uses PythonKni's managed `Worker` and cooperative cancellation contract, so closing the tool does not terminate a running `QThread` unsafely.

## Current limitations

- Socket/process visibility depends on OS permissions; inaccessible processes are shown as unknown rather than causing the session to fail.
- Reverse DNS and optional ASN data are metadata enrichment, not authoritative identity.
- Per-process traffic byte attribution is intentionally not claimed.
- PCAP is Windows/`pktmon` capability-dependent and explicit.
- The Network Intelligence bridge is read-only in this milestone; live observations do not yet become canonical snapshot schema fields.
