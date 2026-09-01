# Network Intelligence

`Network Intelligence` is the local network-enrichment block that sits above the existing Network Explorer and Camera Exposure Auditor services.

Its purpose is to answer a higher-level question than a raw host or port scan:

> What kind of device is this host, what evidence supports that classification, and which specialized PythonKni tool should inspect it next?

## Flow

```text
Authorized local CIDR
        |
        v
Network host discovery
        |
        v
Bounded intelligence probes
        |
        +-- SSH / DNS / HTTP(S) / SMB
        +-- printing services
        +-- RTSP
        +-- NFS / common NAS management ports
        +-- RDP
        |
        +---- ONVIF WS-Discovery
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
Evidence + exposure risk
        |
        +-- Camera --> Open in Camera Exposure Auditor
```

## Architecture

```text
pythonkni/network_intelligence/
├── models.py
├── service.py
└── window.py

          reuses
            |
            +--> pythonkni/network/service.py
            |      host discovery
            |
            +--> pythonkni/camera_auditor/service.py
                   ONVIF / HTTP(S) / RTSP camera evidence
```

The domain is intentionally an orchestration layer. It does not duplicate Network Explorer or Camera Exposure Auditor logic.

## Classification model

Each classified host becomes a `NetworkIntelligenceDevice` containing:

- the original `DiscoveredHost` (`IP`, hostname and MAC);
- `DeviceKind`;
- the small set of observed service ports;
- normalized service labels;
- classification evidence;
- exposure risk;
- optional `CameraDevice` evidence when camera detection succeeds.

Classification is evidence-based and deliberately conservative. `Unknown` is preferred when there is not enough signal.

## Camera hand-off

When a device is classified as `Camera`, the UI enables **Open in Camera Auditor**.

The hand-off opens Camera Exposure Auditor with a single-host CIDR:

```text
192.168.1.44
      |
      v
192.168.1.44/32
      |
      v
Camera Exposure Auditor
```

This keeps the second-stage audit narrowly scoped to the selected device.

## Safety boundaries

Network Intelligence is designed for authorized LAN administration and intentionally keeps the same defensive boundaries as Camera Exposure Auditor:

- IPv4 local/private scopes only;
- maximum 256 hosts per run;
- bounded worker concurrency;
- short connection timeouts;
- a fixed, curated set of identification ports instead of arbitrary port ranges;
- ONVIF WS-Discovery limited to the selected local scope;
- no username/password attempts;
- no default-credential testing;
- no RTSP stream retrieval;
- no camera image retrieval;
- no internet-wide discovery, search-engine dorking or scraping;
- cooperative cancellation through the shared managed-worker lifecycle.

## Current heuristics

The classifier currently uses signals such as:

| Kind | Example signals |
|---|---|
| Camera | ONVIF evidence, RTSP `:554`, camera/vendor hostname hints |
| Printer | IPP `:631`, LPD `:515`, JetDirect `:9100`, printer hostname hints |
| NAS | NFS `:2049`, common NAS web ports `:5000/:5001`, NAS hostname hints |
| Router | router/gateway hostname hints or DNS + web services on a gateway-style address |
| PC | RDP, SSH or SMB without stronger NAS/printer/camera evidence |
| Unknown | insufficient evidence |

These are classification hints rather than vendor guarantees. The UI exposes the evidence so an operator can understand why a label was assigned.

## Future extensions

Good next steps that preserve the same model include:

- MAC OUI/vendor enrichment from an offline database;
- default-gateway identification to strengthen router classification;
- mDNS/SSDP enrichment for printers, NAS devices and media appliances;
- confidence scoring per classification;
- integration with Network Explorer results/history;
- device inventory snapshots and change detection;
- exportable network-intelligence reports;
- risk aggregation across a whole LAN.
