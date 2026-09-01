# Network Intelligence

`Network Intelligence` is PythonKni's persistent local asset, exposure, relationship and change-intelligence layer. It sits above Network Explorer and the specialized device auditors.

Its purpose is no longer only to answer _what is on the network right now?_ It also answers:

- what devices have been seen before;
- how each device was classified and how strong that classification is;
- which weighted signals explain the classification;
- which services were observed;
- which vendor can be inferred from passive/local evidence;
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
        +-- Offline MAC OUI enrichment
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
        +-- Classification confidence (0..100)
        +-- Weighted explainability signals
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
├── classification.py
├── oui.py
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
├── confidence_window.py
├── auditors.py
├── audit_window.py
└── window.py

assets/
└── network_oui_prefixes.csv
```

The domain reuses `pythonkni/network/service.py` for host discovery and `pythonkni/camera_auditor/service.py` for ONVIF/HTTP(S)/RTSP camera evidence.

## Offline MAC OUI / Vendor Intelligence

Vendor enrichment is performed locally from the MAC address already discovered on the authorized LAN. PythonKni never sends a MAC address to an external lookup service.

The bundled `assets/network_oui_prefixes.csv` snapshot contains curated MA-L/OUI prefixes for high-value Network Intelligence manufacturers such as camera, NAS, networking and common endpoint vendors. It is intentionally a focused snapshot rather than a claim of complete IEEE registry coverage.

Resolution rules are deliberately conservative:

1. an explicit vendor learned from the Camera Auditor/ONVIF has precedence;
2. otherwise a globally administered unicast MAC may be resolved through the offline OUI snapshot;
3. hostname hints remain the final fallback;
4. multicast, broadcast, invalid and locally administered/randomized MAC addresses are never attributed to an OUI vendor.

OUI evidence can strengthen classification only for narrowly scoped manufacturers where the signal is useful, currently camera manufacturers (`Hikvision`, `Dahua`, `Reolink`, `Axis`) and NAS manufacturers (`Synology`, `QNAP`). Multi-purpose manufacturers such as `Ubiquiti`, `TP-Link`, `Apple` and `Raspberry Pi` enrich the profile but do not force a device type on their own.

This keeps vendor intelligence useful without pretending that an interface manufacturer always identifies the device's exact product or role.

## Classification confidence and explainability

The selected device type and its confidence are deliberately separate concepts. The existing conservative classification precedence still decides whether an asset is a Camera, Printer, NAS, Router, PC or Unknown. A second pure scoring layer then explains how strongly the available evidence supports that selected type.

Classification confidence is a deterministic `0..100` heuristic with three presentation bands:

- `LOW`: 0..39;
- `MEDIUM`: 40..69;
- `HIGH`: 70..100.

The score is **not** a statistical probability and is not an industry-standard metric. It is a project-defined explainability score whose weights are explicit and regression-tested.

Examples of weighted signals include:

- Camera: ONVIF evidence, RTSP `:554`, camera-specific OUI/vendor and hostname hints;
- Printer: JetDirect `:9100`, IPP `:631`, LPD `:515` and printer hostname hints;
- NAS: NFS `:2049`, common NAS management ports, NAS-specific OUI/vendor and hostname hints;
- Router: gateway-style DNS + web signature and router/gateway hostname hints;
- PC: RDP `:3389`, SSH `:22` and SMB `:445` when stronger NAS evidence is absent.

Every signal is persisted with its key, label, configured weight, matched state and human-readable evidence. The UI displays both matched and unmatched signals so the score can be inspected rather than treated as an opaque number.

Classification confidence is also explicitly independent from security risk. For example, an ONVIF camera can be classified with `HIGH` confidence while still having `LOW` exposure risk if only protected services are observed. Conversely, a device may have lower classification confidence while exposing a medium-risk clear-text service.

Existing SQLite inventories are migrated in place. Legacy assets receive neutral `0` confidence and an empty signal set until they are observed by a new Network Intelligence run; no existing asset or timeline data is discarded.

## Asset Inventory

The inventory uses the standard-library `sqlite3` module and stores its database under PythonKni's runtime data directory. No project or installation directory is used for mutable state.

An asset contains:

- stable asset identifier;
- current IP;
- MAC;
- hostname;
- inferred vendor when evidence exists;
- device type;
- classification confidence (`0..100`);
- structured weighted classification signals;
- normalized observed services and ports;
- exposure risk;
- classification evidence;
- first-seen timestamp;
- last-seen timestamp;
- last-change timestamp;
- online/offline state.

A valid MAC address is preferred as the stable identity so DHCP address changes do not create a new asset. When a usable MAC is unavailable, the IP address is used as the fallback identity.

## Network Timeline / Change Detection

Completed snapshots are compared with the previous persistent state. Network Intelligence records meaningful transitions such as:

- `new_device`;
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

The Network Security Score and Device Classification Confidence solve different problems: the former describes exposure posture, while the latter describes how strongly the observed evidence supports the inferred device role.

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
- persisted vendor/OUI evidence;
- classification confidence level and weighted signal evidence;
- relationship evidence and confidence;
- up to the latest 1000 persisted timeline events.

The report schema is versioned. Classification confidence and structured classification signals are introduced in schema version 2.

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
- OUI/vendor lookup is fully offline;
- classification confidence is computed locally from already-observed evidence;
- no MAC address is submitted to third-party services;
- no username/password attempts;
- no default-credential testing;
- no stream or camera image retrieval;
- no internet-wide discovery, search-engine dorking or scraping;
- cooperative cancellation through managed workers;
- reporting operates only on already-persisted local state.

## Next platform layers

Useful next extensions now that inventory, topology, physical evidence, reporting, vendor enrichment and classification explainability are present include:

- inventory/report comparison between two saved snapshots;
- scheduled local inventory checks with change notifications;
- richer risk aggregation by device type and relationship context;
- build-time expansion of the offline OUI snapshot without adding runtime network access.
