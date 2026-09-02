# Network Intelligence

`Network Intelligence` is PythonKni's persistent local asset, exposure, relationship, history and change-intelligence layer. It sits above Network Explorer and the specialized device auditors.

It answers both current-state and historical questions: what devices exist, how they were classified, what evidence supports that classification, how they are related, how exposure is scored, what changed between observations/snapshots, how those changes trend over time, and which changes deserve a local notification.

## Platform flow

```text
Authorized local CIDR
        ↓
Bounded host discovery + intelligence probes + ONVIF
        ↓
Offline MAC OUI enrichment
        ↓
Device classification + confidence/explainability
        ↓
Persistent Asset Inventory (SQLite)
        ├─ stable identity reconciliation
        ├─ relationship evidence / topology
        ├─ contextual Network Security Score
        ├─ timeline / device auditors
        └─ deterministic snapshot reporting
                       ↓
             automatic/saved snapshots
                ├─ offline comparison
                ├─ Security Score History
                ├─ History Center + trends
                ├─ retention policy
                └─ meaningful-change notifications
```

## Architecture

```text
pythonkni/network_intelligence/
├── models.py
├── service.py
├── classification.py
├── oui.py
├── identity.py
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
├── comparison.py
├── comparison_window.py
├── history.py
├── history_window.py
├── history_center_window.py
├── automatic_snapshot.py
├── retention.py
├── scheduler.py
├── scheduler_window.py
├── notifications.py
├── notification_window.py
├── confidence_window.py
├── risk_window.py
├── auditors.py
├── audit_window.py
└── window.py
```

The domain reuses `pythonkni/network/service.py` for host discovery and `pythonkni/camera_auditor/service.py` for ONVIF/HTTP(S)/RTSP camera evidence.

## Offline MAC OUI / Vendor Intelligence

Vendor enrichment is performed locally from the MAC address already discovered on the authorized LAN. PythonKni never sends a MAC address to an external lookup service during normal runtime operation.

The bundled `assets/network_oui_prefixes.csv` is generated from the official IEEE Registration Authority **MA-L** public CSV by the explicit build/maintenance tool `scripts/update_oui_registry.py`. The current checked-in registry contains **40,046 unique OUI-24 assignments**. `assets/network_oui_prefixes.meta.json` records source/provenance and SHA-256 integrity metadata; CI and Release validate both files offline.

The updater normalizes input deterministically, detects malformed/truncated data and records conflicting duplicate upstream assignments instead of silently choosing one. Monthly/manual maintenance can propose a PR, but the application runtime itself remains offline.

Resolution remains conservative: explicit Camera Auditor/ONVIF vendor evidence has precedence; otherwise a globally administered unicast MAC may resolve against the bundled snapshot; hostname hints remain a fallback; multicast/broadcast/invalid/locally administered MACs are never attributed to an OUI vendor. Vendor evidence strengthens device classification only where the signal is appropriately narrow; a manufacturer name is not treated as proof of an exact device role.

See [`network-oui-registry.md`](network-oui-registry.md).

## Classification confidence and explainability

The selected device type and its confidence are separate concepts. Conservative classification precedence decides Camera/Printer/NAS/Router/PC/Unknown; a deterministic `0..100` confidence heuristic then records weighted matched/unmatched signals explaining how strongly evidence supports that selection.

Confidence bands are LOW `0..39`, MEDIUM `40..69` and HIGH `70..100`. This score is not a statistical probability or industry standard. It is independent from exposure risk: a device can be classified confidently while having low current exposure, or vice versa.

## Asset Inventory and identity reconciliation

Inventory uses standard-library SQLite under PythonKni's runtime data directory. Assets persist stable identifier, IP/MAC/hostname/vendor, type/confidence/signals, services/ports, exposure risk/evidence, lifecycle timestamps and online/offline state.

A valid MAC is preferred as stable identity. An active `ip:<address>` fallback is promoted transactionally to `mac:<address>` when stronger evidence appears, preserving `first_seen` and rewriting timeline/relationship references. Legacy duplicates are repaired only with corroborated transition evidence; ambiguous offline IP reuse is deliberately **not** merged merely because the IP matches.

## Network Timeline / Change Detection

Completed snapshots record meaningful transitions including new/returned/disappeared devices, IP/type/risk changes, opened/closed ports and identity reconciliation. Partial/cancelled scans never mark devices disappeared.

## Network Security Score

The dashboard calculates a deterministic `0..100` score from online assets. Base deductions cover elevated risk, unknown devices, exposed RTSP/clear-text HTTP and newly observed unknown assets. A bounded contextual layer can add small review-priority deductions for elevated-risk Router/NAS roles, a **confirmed** default gateway and **confirmed physical links** to relevant infrastructure.

Inferred/unknown relationships and generic same-LAN membership do not receive contextual deductions. Offline assets are excluded and physical-link context is deduplicated. The score is a project-defined prioritization heuristic, not a vulnerability score, exploitability probability or compromise model.

## Relationship evidence and topology

Logical relationships are generated from local LAN/gateway evidence and persisted with explicit CONFIRMED/INFERRED/UNKNOWN confidence. Administrative LLDP/MAC-table snapshots can add validated `PHYSICAL_LINK` relationships transactionally. Topology renders the persisted graph; it does not trigger a second scan.

## Snapshot reporting and offline comparison

`Export snapshot report` serializes already-persisted state and performs no additional network probe. JSON reports and ZIP evidence bundles contain canonical scope, UTC generation time, assets, score/findings, vendor/confidence evidence, relationships and bounded timeline data.

`Compare saved snapshots` loads only validated saved JSON/ZIP reports, requires the same canonical scope and reports meaningful asset/service/risk/confidence/relationship/score changes while ignoring observation-only timestamp churn. It never reads current inventory or starts a worker.

See [`network-snapshot-comparison.md`](network-snapshot-comparison.md).

## Offline Security Score History

Security Score History loads two or more validated saved snapshots for one scope, sorts them chronologically and derives score delta/range plus device/risk/finding evolution. It is read-only and does not inspect live inventory or trigger discovery.

See [`network-score-history.md`](network-score-history.md).

## Scheduled monitoring and automatic snapshots

Scheduling is opt-in and in-process. A versioned schedule stores canonical local scope, interval, next run and success metadata. Scheduled checks run only while Network Intelligence is open; no Windows Scheduled Task, service or daemon is installed. An overdue run is picked up when the window is opened again.

A scheduler-owned JSON snapshot is published atomically only after the successful inventory/relationship persistence path. Failed/cancelled/incomplete-persistence runs create neither a successful automatic snapshot nor downstream change notification.

See [`network-scheduled-monitoring.md`](network-scheduled-monitoring.md).

## Change Notification Engine

Consecutive successful automatic snapshots feed a local deterministic change engine. It detects meaningful `new_device`, `ports_opened`, `risk_changed`, `security_score_drop` and `relationships_changed` events, assigns INFO/WARNING/CRITICAL severity and deduplicates exact reprocessing through SHA-256 event IDs.

Timestamp/status/hostname/confidence churn and closed ports are deliberately not treated as notification events. The first automatic snapshot establishes the baseline only. The inbox is versioned, bounded and atomically persisted; a corrupt/incompatible inbox is not automatically overwritten. Notification failures cannot roll back a successful scheduled snapshot.

See [`network-change-notifications.md`](network-change-notifications.md).

## History Center, trends and retention

History Center catalogs only scheduler-owned `scheduled_*.json` reports after validation. Corrupt/incompatible files are surfaced and preserved. Filters support scope plus 24h/7d/30d/90d/1y/all windows. Comparable single-scope views show dependency-free Qt trends for Security Score/high-risk evolution and summaries for device/risk changes, with previous/next navigation and comparison to the previous snapshot.

Retention is versioned/configurable by per-scope count (2..1000) plus optional age. Automatic/manual cleanup applies only to validated scheduler-owned snapshots, never to manual reports or invalid/corrupt snapshots, and always protects the newest **two** valid snapshots per scope so the notification engine keeps its consecutive baseline.

See [`network-history-center.md`](network-history-center.md).

## Device-specific auditors

Router, NAS, Printer and PC auditors consume the persisted device snapshot instead of repeating discovery/arbitrary scanning. Camera assets retain the dedicated Camera Exposure Auditor hand-off with one exact `/32` host.

## Quality gates

The retained Network Intelligence benchmark measures deterministic classification and OUI throughput but keeps shared-runner timing informational rather than a pass/fail threshold.

A separate AST structural typing ratchet prevents annotation regression. Current protected package metrics are **668/721 annotated slots (92.65%)**, **264 fully annotated / 303 tracked callables**, and **39 explicit `Any`** at most. Fifteen strict modules must remain fully annotated with zero explicit `Any`. This is intentionally incremental and does not claim semantic static type checking.

See [`network-intelligence-quality-gates.md`](network-intelligence-quality-gates.md).

## Safety boundaries

Network Intelligence is intended for authorized LAN administration and keeps these boundaries:

- private/local/link-local/loopback IPv4 only;
- maximum 256 hosts per Network Intelligence run;
- bounded concurrency and short timeouts;
- fixed curated identification ports/ONVIF within selected scope;
- OUI/vendor lookup fully offline at runtime;
- historical comparison/history/notification/retention read saved local state only;
- no username/password or default-credential attempts;
- no stream/camera-image retrieval;
- no internet-wide discovery, dorking or scraping;
- cooperative cancellation through managed workers;
- no cloud telemetry or OS background service.

## Current platform status and next layers

The previously planned layers for scheduled checks, change notifications, history/trends/retention and build-time OUI expansion are now implemented. Network Intelligence currently spans:

```text
Discover → Inventory → Classify → Relate → Score → Report
        → Schedule → Snapshot → Compare/History → Detect change → Notify/Retain
```

Future work should remain incremental: add further defensive device-role context only when backed by explicit persisted evidence, reduce remaining structural typing debt/promote more strict modules, and consider a semantic type checker as a separate migration rather than weakening the existing gate.