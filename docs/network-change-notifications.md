# Network Intelligence Change Notifications

`Change Notification Engine` turns consecutive automatic Network Intelligence snapshots into a small local inbox of meaningful state transitions.

It is deliberately downstream from scheduled discovery and automatic snapshot publication:

```text
Scheduled Network Intelligence run
        |
        v
Persist inventory + relationships
        |
        v
Publish automatic JSON snapshot
        |
        +-- previous successful automatic snapshot
        |
        v
Validated snapshot comparison
        |
        v
Change Notification Engine
        |
        v
Atomic local notification inbox
```

The engine does not start discovery, perform probes, read credentials or contact an external service. It only reads two already-created Network Intelligence snapshots plus the local notification inbox.

## Notification categories

Version 1 emits five categories:

- `new_device`: a new persisted asset appears in the current snapshot;
- `ports_opened`: an existing asset exposes one or more ports that were not open in the previous snapshot;
- `risk_changed`: an existing asset changes between `LOW`, `MEDIUM` and `HIGH` exposure risk;
- `security_score_drop`: the aggregate Network Security Score decreases;
- `relationships_changed`: persisted topology relationships were added, removed or had confidence/evidence changes.

The engine intentionally does **not** create notifications for ordinary observation churn. Changes limited to `first_seen`, `last_seen`, `last_change`, online/offline status, hostname, classification-confidence movement or closed ports are not notification events in v1. Those details remain available in the inventory, timeline and explicit snapshot-comparison workflows.

This distinction prevents a scheduled scan from turning normal LAN presence changes into a noisy alert stream.

## Severity

Severity is deterministic and intentionally simple:

| Change | Severity |
| --- | --- |
| New `HIGH`-risk device | `CRITICAL` |
| Other new device | `WARNING` |
| Risk increase to `HIGH` | `CRITICAL` |
| Other risk increase | `WARNING` |
| Risk decrease | `INFO` |
| New port on a `HIGH`-risk asset | `CRITICAL` |
| Other newly opened port | `WARNING` |
| Security Score drop of 10+ points | `CRITICAL` |
| Smaller Security Score drop | `WARNING` |
| Added/modified relationship evidence | `WARNING` |
| Relationship removals only | `INFO` |

These levels are project-defined prioritization semantics. They are not CVSS ratings, exploitability probabilities or proof that a device is compromised.

## Deterministic deduplication

Every notification receives a SHA-256 event identifier derived from:

- canonical scope;
- baseline snapshot timestamp;
- current snapshot timestamp;
- category;
- subject;
- relevant before/after state.

Re-processing the exact same snapshot pair therefore cannot create another copy of the same notification.

A real later recurrence is still allowed. For example, if port 443 opens, later closes and then opens again in a different snapshot pair, the later transition receives a different event identifier and can be reported again.

The inbox also rejects duplicate `event_id` values when loading persisted state.

## Local inbox

Notifications are stored in the standard PythonKni data directory as a versioned JSON document.

Properties:

- schema versioned;
- maximum 500 retained notifications;
- maximum 2 MiB input size when loading;
- strict field/type validation;
- timezone-aware UTC timestamps;
- read/unread state;
- atomic write using a temporary file, `fsync` and `os.replace`;
- a failed write leaves the previous valid inbox untouched.

If the inbox is corrupt or incompatible, PythonKni does not overwrite it automatically. The scheduled snapshot still succeeds, but notification processing for that run is skipped so deduplication state is not silently destroyed.

## Scheduler integration

The scheduler passes the previously successful automatic snapshot and the newly published snapshot to a post-publication hook.

The ordering is important:

1. scan completes;
2. inventory and relationships persist successfully;
3. current automatic snapshot is published atomically;
4. scheduler success metadata is persisted;
5. only then are notifications evaluated and stored.

Notification failure cannot roll back a successful scan or a valid snapshot. Conversely, a failed/cancelled scan or incomplete persistence still produces neither an automatic snapshot nor notifications.

The first successful automatic snapshot establishes a baseline and creates no change notification because there is no previous state to compare against.

## User interface

Network Intelligence adds a compact local notification center showing:

- unread count;
- unread critical count;
- unread warning count;
- total retained notifications;
- a `Ver cambios` action.

Opening the dialog displays the persisted events and marks them as read using the same atomic persistence path.

No blocking pop-up is shown automatically after every scheduled run. The main status line reports how many relevant changes were detected, while the notification center preserves the details for review.

## Security and privacy boundary

Change notifications are offline and read-only with respect to network state. They do not broaden the authorized scan scope introduced by scheduled monitoring.

In particular, the engine introduces no:

- internet access;
- credential attempts;
- default-password testing;
- new port scanning;
- packet capture;
- camera stream/image retrieval;
- OS background service or Scheduled Task;
- cloud notification transport.

Future delivery channels, if added, should consume the local notification model rather than weakening these boundaries or embedding network-discovery behavior into the notification layer.
