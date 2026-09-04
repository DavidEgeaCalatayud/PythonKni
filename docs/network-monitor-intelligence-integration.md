# Network Traffic Monitor → Network Intelligence

The Network Traffic Monitor is integrated with the existing Network Intelligence change/history pipeline instead of maintaining a separate canonical event inbox.

```text
Network Traffic Monitor
        ↓
MonitorEvent
        ↓ normalize
ChangeNotification
        ↓
network_intelligence_notifications.json
        ├── Change Notification Engine
        └── History Center · Telemetría temporal
```

## Canonical notification persistence

The application adapter routes monitor events through `pythonkni.network_intelligence.temporal_notifications.publish_monitor_events()`.

The seven monitor categories are preserved:

- `new_external_connection`
- `new_remote_host`
- `new_listening_port`
- `process_network_activity`
- `traffic_spike`
- `known_asset_connection`
- `unusual_destination`

They use the existing `ChangeNotification` schema, severity model, 500-item bounded inbox, read/unread state, ordering and merge/deduplication behavior. Monitor events carry an explicit `Source: Network Traffic Monitor` detail so they can be distinguished from snapshot-diff notifications without introducing another persistence format.

The old monitor `events.jsonl` writer is retained only as a recovery fallback if the canonical Network Intelligence inbox cannot be read or written. Successful normal operation does not duplicate monitor events into both stores. Periodic traffic history samples remain in the bounded monitor history JSONL because they are time-series samples rather than discrete Change Notification events.

## Temporal occurrence identity

A monitor event's domain `event_id` describes the logical event inside a monitoring session. Using that value directly in the global inbox would incorrectly suppress a later recurrence forever.

The integration therefore derives a notification occurrence id from:

```text
monitor event_id + exact observation timestamp
```

Consequences:

- replaying the exact same observation is idempotent;
- observing the same logical destination/process in a later session creates a new temporal record;
- Change Notification merge semantics remain deterministic.

## History Center

The composed Network Intelligence tool extends History Center with a **Telemetría temporal** table. It reads monitor-originated notifications from the canonical inbox and shows:

- detection time;
- severity;
- event category;
- subject;
- monitor scope;
- message.

The History Center period filter also filters temporal events. Snapshot scope filtering remains separate because passive monitor observations are not converted into synthetic Network Intelligence snapshots or assets.

## Live Change Notification refresh

Network Intelligence polls its local notification inbox every two seconds while its window is open. This lets a simultaneously running Network Traffic Monitor surface new unread events in the existing **Cambios de red** controls without requiring the user to reopen Network Intelligence.

The refresh is local-file only; it does not perform network discovery or external requests.

## Failure semantics

Failure to enrich or publish a temporal notification must not terminate passive monitoring. The application adapter falls back to the bounded legacy monitor event JSONL only when publishing to the canonical inbox raises an error. This preserves evidence while making the normal canonical path the Network Intelligence notification/history pipeline.

No part of this integration creates synthetic assets, changes device risk/classification, injects packets or enables active probing.
