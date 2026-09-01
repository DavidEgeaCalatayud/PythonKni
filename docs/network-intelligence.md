# Network Intelligence

`Network Intelligence` is PythonKni's persistent local asset, exposure and change-intelligence layer. It sits above Network Explorer and the specialized device auditors.

Its purpose is no longer only to answer _what is on the network right now?_ It also answers:

- what devices have been seen before;
- how each device was classified;
- which services were observed;
- when the device first and last appeared;
- what changed between completed scans;
- what the current network exposure score is;
- which specialized auditor should inspect an asset next.

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

## Device Profile

Selecting an inventory row exposes the full persistent profile rather than only the latest scan output:

```text
192.168.1.34
NAS

Hostname      diskstation
MAC           AA:BB:CC:DD:EE:FF
Vendor        Synology
First seen    31/08/2026 17:42
Last seen     31/08/2026 19:10
Last change   31/08/2026 18:10
Status        Online

Services
✓ SMB           445
✓ NAS-Web-TLS   5001

Risk
LOW

Classification evidence
• Services or hostname compatible with NAS
```

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

The score is deliberately explainable: the UI shows the aggregate counts and the findings that caused deductions instead of presenting an opaque number.

## Device-specific auditors

Router, NAS, Printer and PC auditors consume the already persisted device snapshot. They do **not** repeat network discovery or arbitrary port scanning. Their findings map known exposure signals to defensive recommendations.

Camera assets retain the dedicated `Camera Exposure Auditor` hand-off and are opened with a single-host `/32` scope.

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
- cooperative cancellation through managed workers.

## Next platform layer

The persistent inventory now provides the data model required for a future topology view:

```text
Internet
   |
Router
   |
   +-- PC
   +-- NAS
   +-- Switch
          |
          +-- Camera
          +-- Printer
```

That view should be built from inventory relationships and network evidence rather than from a second independent scanner.
