# Network Security Score History

`Security Score History` provides an offline historical view of previously exported Network Intelligence snapshots. It is intentionally read-only: it loads saved reports and does not inspect the live Asset Inventory, start discovery, or perform any network probe.

## Inputs

The workflow accepts two or more existing Network Intelligence snapshots in the formats already supported by the validated report loader:

- `.json` snapshot reports;
- `.zip` evidence bundles, reading only the fixed `report.json` member.

Duplicate file selections are ignored. After deduplication, at least two distinct snapshots are required.

All selected reports must describe the same canonical IPv4 scope and must have unique timezone-aware `generated_at` timestamps. Mixed scopes and duplicate timestamps are rejected instead of being combined into a misleading trend.

## Ordering and history model

Snapshots are ordered chronologically by `generated_at`, independent of the order in which the user selected the files.

For each point the history records:

- generation timestamp and source file;
- report schema version;
- Network Security Score (`0..100`);
- score delta from the previous snapshot;
- total device count;
- High, Medium and Low risk counts;
- Unknown-device count;
- score findings;
- findings added since the previous snapshot;
- findings resolved since the previous snapshot.

The first snapshot is the baseline and therefore has no score delta or added/resolved finding comparison.

The aggregate history also exposes the first score, latest score, total period delta, minimum score and maximum score.

## UI

The `Security Score History` action opens a read-only Qt dialog with a chronological table and per-snapshot details. The action is disabled while a Network Intelligence scan is actively mutating state, matching the other historical/reporting actions.

Selecting a history row shows the source snapshot, score/delta, device and risk counters, current findings, and findings that appeared or were resolved relative to the previous point.

## Offline boundary

Security Score History is deliberately composed above the existing snapshot-report loader rather than the live inventory service.

It does not:

- query the current SQLite Asset Inventory;
- start a Network Intelligence worker;
- discover hosts;
- probe ports or services;
- perform ONVIF discovery;
- query an external service;
- modify the selected snapshots.

This makes the same historical dataset reproducible later, even when the current network state has changed.

## Relationship to snapshot comparison

`Compare saved snapshots` answers what changed between two saved reports in detail. `Security Score History` answers how the aggregate security posture evolved across two or more reports.

Both workflows consume the same validated saved-report format and require one canonical scope, but they serve different review tasks:

- snapshot comparison: detailed two-point asset/relationship/finding delta;
- score history: ordered multi-point score, risk-count and finding evolution.

## Current scope

The first version is intentionally tabular and deterministic. Automatic scheduled snapshots, retention policies, notifications and chart-based trend visualization remain separate future layers rather than being hidden inside this read-only historical analysis.
