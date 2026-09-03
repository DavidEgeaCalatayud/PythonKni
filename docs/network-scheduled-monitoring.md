# Scheduled Network Intelligence

Scheduled Network Intelligence turns the existing local inventory/reporting pipeline into an opt-in monitor without adding an operating-system service or an internet dependency. Service Intelligence v2 optionally inserts bounded TCP fingerprinting into that pipeline without enabling the broader manual Nerva modes.

## Execution model

The scheduler is deliberately in-app only:

- monitoring is disabled by default;
- enabling it captures and persists one validated canonical local IPv4 scope;
- scheduled scans run only while the Network Intelligence window is alive inside PythonKni;
- PythonKni does not create a Windows Scheduled Task, service, startup entry or background daemon;
- if PythonKni was closed when a run became due, the overdue run is picked up after the window is opened again;
- the existing authorized-scope policy still applies: RFC1918, link-local or loopback IPv4 only, with at most 256 usable hosts;
- no credentials, default-password attempts, brute force, exploitation, stream retrieval or internet-wide discovery are introduced.

The UI offers 15 min, 30 min, 1 h, 3 h, 6 h, 12 h and 24 h intervals. The scheduling domain itself enforces a minimum of 15 minutes and a maximum of 24 hours.

## Persistent schedule state

The schedule is stored under PythonKni's runtime data directory in `network_intelligence_schedule.json`.

The versioned state contains:

- enabled/disabled state;
- canonical scope;
- interval in minutes;
- next scheduled run;
- last scheduled start;
- last successful scheduled run;
- path of the last automatic snapshot;
- configured fingerprint policy.

All timestamps are timezone-aware and persisted in UTC. Schedule updates use a same-directory temporary file, `fsync` and `os.replace()` so the previous valid configuration survives an interrupted write.

An invalid or unsupported schedule file is ignored rather than executed. Older valid schedule state without the new fingerprint field remains backward-compatible through the default manual policy.

## Fingerprint policy

The UI exposes four choices:

```text
Disabled
Manual only
Automatic after discovery
Only assets with known changes
```

`Disabled` and `Manual only` do not add a Nerva substep to scheduled work and preserve the previous immediate-snapshot behavior after successful discovery persistence.

The two automatic policies run service fingerprinting only after the scheduled discovery has persisted valid inventory/relationship state and before the automatic snapshot is published. `Only assets with known changes` limits candidates using persisted change timestamps relative to the previous successful scheduled run.

Automatic fingerprinting is intentionally narrower than Network Explorer's manual Service Intelligence features:

- existing online assets only;
- already-known TCP ports only;
- maximum **32 assets** per pass;
- maximum **16 ports per asset**;
- **8 Nerva workers**;
- maximum **2 connections per host**;
- **1500 ms** Nerva probe timeout;
- `misconfigs=False` unconditionally;
- no UDP;
- no SCTP.

The scheduler therefore cannot silently invoke **Check insecure configurations**, cannot start a UDP profile scan and cannot use advanced SCTP.

## No overlapping scans

The scheduler polls for due work while the application is open, but never starts a second Network Intelligence worker while another worker is running.

When a run becomes due, PythonKni first advances and persists `next_run_at` and only then starts the worker. This is intentional: a failed or cancelled run cannot become permanently overdue and retrigger every scheduler poll. The next attempt therefore follows the configured interval.

Manual scans remain available. They use the same selected/canonical scope but are not treated as scheduled runs and do not create automatic snapshots.

## Automatic snapshots

A scheduled run can publish one JSON Network Intelligence snapshot only after the required persistence/enrichment path for its configured policy has completed:

```text
scheduled discovery
       ↓
inventory + relationships persisted
       ↓
optional bounded automatic TCP fingerprinting
       ↓
automatic snapshot
       ↓
change notification / history pipeline
```

Snapshot contents include:

- Asset Inventory;
- persisted relationships;
- up to the latest 1000 timeline events;
- service/finding evidence already accepted into the inventory;
- the same context/finding-aware Network Security Score used by normal reporting.

If inventory persistence fails, logical relationships are not replaced from stale inventory data. If either inventory or relationship persistence is incomplete, the scheduled execution is not recorded as a successful snapshot run and no automatic snapshot is published.

If automatic Nerva fingerprinting is configured but the engine is unavailable or one host fails/times out, PythonKni treats that optional enrichment as degraded: valid discovery state remains usable and the snapshot can still be published with a warning/status summary. A deliberate cancellation of the fingerprinting substep is different: PythonKni skips that snapshot so it does not falsely represent the configured enrichment as completed.

Automatic snapshots use the existing report schema, so they can be opened by both `Compare saved snapshots` and `Security Score History` without a separate compatibility layer.

Snapshots are written under:

```text
<runtime data>/network_intelligence_reports/scheduled/
```

Names include the canonical scope and a UTC timestamp with microseconds, for example:

```text
scheduled_192.168.1.0_24_20260901T203000.123456Z.json
```

Publication is atomic: PythonKni writes a temporary JSON report first and only exposes the final snapshot through `os.replace()` after serialization succeeds.

## Retention

Scheduled monitoring must not grow the runtime-data directory without bound. PythonKni therefore retains at most **120 automatic snapshots per scope** by default, with the History Center retention layer providing configurable bounded cleanup.

Retention applies only to validated scheduler-owned snapshots. Manual reports and invalid/corrupt evidence are not silently deleted, and the newest two valid snapshots per scope remain protected so consecutive comparison/notification behavior keeps a baseline.

## Failure and cancellation semantics

A failed or cancelled scheduled discovery run does not create an automatic snapshot.

Cancellation continues to use the existing cooperative worker path. As with manual Network Intelligence runs, an incomplete scan does not mark absent assets as disappeared and does not replace relationship evidence with incomplete results.

If the schedule itself cannot be persisted before a due execution, the run is not started and scheduling is disabled for the current session rather than risking repeated uncontrolled execution.

If the scan completes but inventory or relationship persistence is incomplete, PythonKni keeps the successfully persisted state, reports the degraded persistence, and does not publish an automatic snapshot.

If the optional automatic fingerprint step fails as a component, PythonKni can preserve the valid inventory and continue to the snapshot with degraded status. If that step is deliberately cancelled, no snapshot is published for that run.

If discovery/enrichment requirements complete but automatic snapshot publication fails, the persisted state remains and PythonKni reports the snapshot failure separately.

## Security boundary

Scheduling changes *when* the existing bounded local workflow runs; it does not broaden *what* the workflow is allowed to inspect.

The scheduler never bypasses `parse_camera_scope()`, never expands a stored scope, never performs credential attempts and never contacts a third-party service. Scheduled Nerva execution is limited to known TCP ports and explicitly forces `misconfigs=False`; UDP, SCTP and misconfiguration checks remain manual/capability-aware Network Explorer operations.

See [`network-service-fingerprinting.md`](network-service-fingerprinting.md) for the Nerva trust/capability contract.
