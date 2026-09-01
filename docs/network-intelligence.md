# Network Intelligence

`Network Intelligence` is PythonKni's persistent local asset, exposure, relationship and change-intelligence layer. It sits above Network Explorer and the specialized device auditors.

Its purpose is no longer only to answer _what is on the network right now?_ It also answers:

- what devices have been seen before;
- how each device was classified;
- which services were observed;
- when the device first and last appeared;
- what changed between completed scans;
- how assets are related and what evidence supports those relationships;
- what the current network exposure score is;
- which specialized auditor should inspect an asset next;
- how to export a reproducible snapshot for later review.

## Platform flow

```text
Authorized local CIDR
        |
        v
Network host discovery
        |
        v
Bounded intelligence probes + ONVIF
        |
        v
Device classification
        |
        +-- PC
        +-- Router
        +-- Printer
        +-- NAS
        +-- Camera
        +-- Unknown
        |
        v
Persistent Asset Inventory (SQLite)
        |
        +-- Device Profile
        +-- Network Security Score
        +-- Network Timeline / Change Detection
        +-- Relationship Evidence
        +-- Network Topology
        +-- Snapshot Reporting
        |
        v
Device-specific auditor
        |
        +-- Camera -> Camera Exposure Auditor (/32)
        +-- Router -> Router Security Auditor
        +-- NAS -> NAS Exposure Auditor
        +-- Printer -> Printer Security Auditor
        +-- PC -> PC Security Auditor
```

## Architecture

```text
pythonkni/network_intelligence/
├── models.py
├── service.py
├── inventory.py
├── score.py
├── relationships.py
├── relationship_store.py
├── topology.py
├── topology_view.py
├── physical_evidence.py
├── physical_import.py
├── reporting.py
├── reporting_window.py
├── auditors.py
├── audit_window.py
└── window.py
```

The domain reuses `pythonkni/network/service.py` for host discovery and `pythonkni/camera_auditor/service.py` for ONVIF/HTTP(S)/RTSP camera evidence.

## Asset Inventory

The inventory uses the standard-library `sqlite3` module and stores its database under PythonKni's runtime data directory. No project or installation directory is used for mutable state.

An asset contains:

- stable asset identifier;
- current IP;
- MAC;
- hostname;
- inferred vendor when evidence exists;
- device type;
- normalized observed services and ports;
- exposure risk;
- classification evidence;
- first-seen timestamp;
- last-seen timestamp;
- last-change timestamp;
- online/offline state.

A valid MAC address is preferred as the stable identity so DHCP address changes do not create a new asset. When a usable MAC is unavailable, the IP address is used as the fallback identity.

If a device is first persisted with the provisional `ip:<address>` identity and a later observation exposes a valid MAC on that same scoped IP, the inventory promotes the existing record to `mac:<address>` instead of creating a second asset. The transaction preserves `first_seen`, rewrites historical timeline references, migrates topology/relationship references and records an explicit `identity_reconciled` event.

## Network Timeline / Change Detection

Completed snapshots are compared with the previous persistent state. Network Intelligence records meaningful transitions such as:

- `new_device`;
- `identity_reconciled`;
- `device_returned`;
- `device_disappeared`;
- `ip_changed`;
- `type_changed`;
- `risk_changed`;
- `port_opened`;
- `port_closed`.

Partial/cancelled scans never mark devices as disappeared. This prevents incomplete runs from corrupting the network timeline.

## Network Security Score

The dashboard calculates a deterministic `0..100` score from currently online assets. Deductions are applied for signals such as:

- high/medium-risk assets;
- unknown devices;
- cameras exposing RTSP;
- clear-text HTTP;
- unknown assets first observed today.

The score is deliberately explainable: the UI shows aggregate counts and the findings that caused deductions instead of presenting an opaque number.

## Relationship evidence and topology

Logical relationships are generated from known LAN/gateway evidence and persisted separately from the asset inventory. Relationship records carry explicit confidence and evidence rather than pretending that shared subnet membership proves physical cabling.

Administrative LLDP/MAC-table snapshots can add `PHYSICAL_LINK` relationships after validation against the current inventory. Import is transactional: a snapshot containing unresolved or invalid links does not replace the previous physical-evidence snapshot.

The topology view renders the persisted relationship graph and exposes confidence, protocol and endpoint-port metadata. Physical links therefore remain distinguishable from inferred logical relationships.

## Snapshot reporting

`Export snapshot report` serializes the already-persisted state. Export does not start discovery or perform any additional network probe.

Two formats are supported:

- JSON: complete structured snapshot with a versioned schema;
- ZIP evidence bundle: `report.json`, `assets.csv`, `relationships.csv` and `timeline.csv`.

Reports contain:

- canonical CIDR scope;
- UTC generation timestamp;
- asset/online/offline counts;
- Network Security Score and findings;
- deterministic asset ordering;
- relationship evidence and confidence;
- up to the latest 1000 persisted timeline events.

CSV values are neutralized against spreadsheet formula injection before being written to the evidence bundle.

## Device-specific auditors

Router, NAS, Printer and PC auditors consume the already persisted device snapshot. They do **not** repeat network discovery or arbitrary port scanning. Their findings map known exposure signals to defensive recommendations.

Camera assets retain the dedicated `Camera Exposure Auditor` hand-off and are opened with a single-host `/32` scope. Network Explorer also exposes a conservative hand-off for cameras whose current identity matches a persisted Camera asset.

## Safety boundaries

Network Intelligence is intended for authorized LAN administration and keeps the same boundaries as Camera Exposure Auditor:

- local/private IPv4 scopes only;
- maximum 256 hosts per run;
- bounded worker concurrency;
- short connection timeouts;
- fixed curated identification ports;
- ONVIF limited to the selected local scope;
- no username/password attempts;
- no default-credential testing;
- no stream or camera image retrieval;
- no internet-wide discovery, search-engine dorking or scraping;
- cooperative cancellation through managed workers;
- reporting operates only on already-persisted local state.

## Next platform layers

Useful next extensions now that inventory, topology, physical evidence and reporting are present include:

- offline MAC OUI/vendor enrichment;
- explicit per-device classification confidence;
- inventory/report comparison between two saved snapshots;
- scheduled local inventory checks with change notifications;
- richer risk aggregation by device type and relationship context.
