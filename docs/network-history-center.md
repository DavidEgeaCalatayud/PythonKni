# Network Intelligence History Center

PythonKni keeps scheduled Network Intelligence snapshots entirely local. The History Center turns those snapshots into a managed operational history without adding cloud storage, telemetry or a background service.

## Scope

The History Center indexes only scheduler-owned JSON snapshots stored under the Network Intelligence `scheduled` reports directory. Manual reports remain outside automatic retention and are never deleted by this feature.

Each indexed snapshot is validated with the existing Network Intelligence report validator before it can participate in trends, navigation, comparisons or cleanup. Invalid/corrupt scheduled files are reported as skipped and deliberately preserved so a malformed file is not silently destroyed.

## History catalog and filters

The catalog records, per snapshot:

- generated timestamp and IPv4 scope;
- report schema version;
- Security Score;
- total, high-risk, medium-risk, low-risk and unknown-device counts;
- current score findings;
- source path and file size.

The UI can filter the catalog by scope and by common time windows: all history, 24 hours, 7 days, 30 days, 90 days and one year.

The catalog is bounded to the newest 2,000 scheduler-owned files per load. If more files exist, the UI reports the number not indexed in that view instead of attempting an unbounded scan.

## Trends

For the current filter the History Center calculates:

- first/latest Security Score and total delta;
- minimum/maximum Security Score;
- device-count delta;
- high-risk, medium-risk and unknown-device deltas.

A native Qt chart visualizes Security Score over time and, when present, high-risk device evolution. It does not introduce a plotting/runtime dependency.

## Snapshot navigation and comparison

The table is chronological and supports previous/next navigation. Selecting a snapshot shows its score, risk distribution, findings, size and source path.

`Compare with previous snapshot in the same scope` reuses the existing snapshot comparison engine and dialog. A snapshot from another scope is never used as a comparison baseline.

The existing manual `Security Score History` and saved-snapshot comparison tools remain available for arbitrary user-selected JSON/ZIP reports. History Center is specifically the automatic scheduled-history UX.

## Retention policy

Retention is stored locally in `network_intelligence_retention.json`, schema version 1.

Current fields:

```json
{
  "schema_version": 1,
  "keep_per_scope": 120,
  "max_age_days": null
}
```

`keep_per_scope` is a maximum number of valid scheduled snapshots per IPv4 scope. The supported range is 1–1,000 and defaults to 120.

`max_age_days` is optional. `null` disables age-based cleanup; otherwise the supported range is 1–3,650 days.

The two rules are combined: a snapshot can become eligible because it exceeds the count limit or because it is older than the age limit. The newest valid snapshot in every scope is always preserved as a baseline even when it is older than the configured age.

## Automatic retention

After a scheduled scan has completed and its snapshot has been atomically published, the scheduler applies the current in-memory retention policy to that scope. The cleanup result is reported through the existing scheduled-scan status text.

Retention remains downstream of scan persistence. It does not change the rules introduced by scheduled monitoring:

- incomplete inventory/relationship persistence still prevents snapshot publication;
- failed/cancelled scans still produce no automatic snapshot;
- notification evaluation still runs only after a successfully published snapshot;
- retention does not start scans or broaden network scope.

## Manual cleanup

`Clean now` first calculates the valid scheduled snapshots that would be removed under the controls currently shown in the dialog. The user is shown the number of snapshots and approximate disk space before deletion and must confirm explicitly.

If a scope filter is selected, cleanup is limited to that scope. With `All scopes`, the same policy is applied independently to every indexed scope.

Manual cleanup:

- deletes only validated scheduler-owned `scheduled_*.json` files;
- preserves the newest valid snapshot per scope;
- never deletes manual reports;
- never deletes skipped/corrupt files automatically;
- reports reclaimed bytes after completion.

The policy used by a confirmed manual cleanup is persisted for future automatic snapshots. If cleanup succeeds but policy persistence fails, the deletion is not rolled back and the UI reports the persistence problem explicitly.

## Persistence safety

Retention configuration uses the same atomic write pattern as scheduler and notification state:

1. create a temporary file in the destination directory;
2. serialize JSON;
3. flush and `fsync`;
4. replace the destination atomically.

A failed replacement leaves the previous valid policy intact and temporary files are cleaned up best-effort.

## Security boundary

History Center is offline and reads only local saved Network Intelligence reports. It does not:

- perform discovery or port scanning;
- contact devices;
- attempt credentials;
- query cloud services;
- upload history or telemetry;
- install an OS scheduler/service;
- delete arbitrary report files.

Its cleanup boundary is deliberately narrower than the reports directory: only valid automatic JSON snapshots matching the scheduled-file namespace can be removed.
