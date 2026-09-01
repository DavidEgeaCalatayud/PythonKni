# Scheduled Network Intelligence

Scheduled Network Intelligence turns the existing local inventory/reporting pipeline into an opt-in monitor without adding an operating-system service or an internet dependency.

## Execution model

The scheduler is deliberately in-app only:

- monitoring is disabled by default;
- enabling it captures and persists one validated canonical local IPv4 scope;
- scheduled scans run only while the Network Intelligence window is alive inside PythonKni;
- PythonKni does not create a Windows Scheduled Task, service, startup entry or background daemon;
- if PythonKni was closed when a run became due, the overdue run is picked up after the window is opened again;
- the existing authorized-scope policy still applies: RFC1918, link-local or loopback IPv4 only, with at most 256 usable hosts;
- no credentials, default-password attempts, stream retrieval or internet-wide discovery are introduced.

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
- path of the last automatic snapshot.

All timestamps are timezone-aware and persisted in UTC. Schedule updates use a same-directory temporary file, `fsync` and `os.replace()` so the previous valid configuration survives an interrupted write.

An invalid or unsupported schedule file is ignored rather than executed.

## No overlapping scans

The scheduler polls for due work while the application is open, but never starts a second Network Intelligence worker while another worker is running.

When a run becomes due, PythonKni first advances and persists `next_run_at` and only then starts the worker. This is intentional: a failed or cancelled run cannot become permanently overdue and retrigger every scheduler poll. The next attempt therefore follows the configured interval.

Manual scans remain available. They use the same selected/canonical scope but are not treated as scheduled runs and do not create automatic snapshots.

## Automatic snapshots

A completed scheduled worker produces one JSON Network Intelligence snapshot from the resulting persisted state:

- Asset Inventory;
- persisted relationships;
- up to the latest 1000 timeline events;
- the same context-aware Network Security Score used by normal reporting.

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

Scheduled monitoring must not grow the runtime-data directory without bound. PythonKni therefore retains at most **120 automatic snapshots per scope**.

Retention applies only to files using the scheduler-owned naming convention inside the scheduled-snapshot directory. Manual reports and automatic snapshots belonging to other scopes are never deleted by this policy.

## Failure and cancellation semantics

A failed or cancelled scheduled run does not create an automatic snapshot.

Cancellation continues to use the existing cooperative worker path. As with manual Network Intelligence runs, an incomplete scan does not mark absent assets as disappeared and does not replace relationship evidence with incomplete results.

If the schedule itself cannot be persisted before a due execution, the run is not started and scheduling is disabled for the current session rather than risking repeated uncontrolled execution.

If the network run completes but automatic snapshot publication fails, the scan result remains persisted and PythonKni reports the snapshot failure separately.

## Security boundary

Scheduling changes *when* the existing bounded local workflow runs; it does not broaden *what* the workflow is allowed to inspect.

The scheduler never bypasses `parse_camera_scope()`, never expands a stored scope, never performs credential attempts, and never contacts a third-party service. Automatic reports are generated exclusively from local persisted Network Intelligence evidence.
