# Architecture

PythonKni is a PyQt5 desktop application with a dynamic tool loader. User-facing
domains follow a layered structure so domain rules and operating-system integration
remain testable without constructing Qt widgets.

## Dependency rule

The main dependency direction is:

```text
pythonkni/core + pythonkni/infrastructure
                 ↑
              models.py
                 ↑
              service.py
                 ↑
              window.py
                 ↑
         tools/*_tool.py adapter
```

- `models.py` contains framework-independent value objects. It must not import
  PyQt or `tools` modules.
- `service.py` owns domain rules, operating-system integration, persistence,
  parsing and transformations. It must not import PyQt, `tools.worker` or a
  window module.
- `window.py` owns PyQt widgets, dialogs, user confirmation and background-thread
  orchestration. It delegates state-changing OS operations to services.
- `pythonkni/infrastructure/` contains framework-independent technical building
  blocks shared by multiple domains.
- `tools/*_tool.py` remains only as the dynamic-loader/legacy compatibility edge.

This keeps business and operating-system behavior independently testable and
prevents presentation modules from becoming alternate service layers.

## Domain layout

The layered domains are:

- `pythonkni/archive/`
- `pythonkni/config/`
- `pythonkni/converter/`
- `pythonkni/disk_analyzer/`
- `pythonkni/duplicate/`
- `pythonkni/event_viewer/`
- `pythonkni/network/`
- `pythonkni/pdf/`
- `pythonkni/process_manager/`
- `pythonkni/startup/`
- `pythonkni/system_report/`
- `pythonkni/temp_cleaner/`
- `pythonkni/wifi/`

Each domain exposes `models.py`, `service.py` and `window.py`. A domain that
currently has no custom value object still keeps an explicit framework-independent
`models.py` boundary rather than moving future data structures into its UI.

## Core and infrastructure

Framework-independent shared code lives below the domain/UI boundary:

```text
pythonkni/
├─ core/
│  └─ tasks.py
└─ infrastructure/
   ├─ archives.py
   └─ paths.py
```

`pythonkni/core/tasks.py` contains cooperative cancellation primitives.

`pythonkni/infrastructure/archives.py` owns archive path validation, extraction
limits, staging/publication and ZIP/7Z extraction safety. It deliberately has no
Qt dependency. The Archive service consumes this module directly instead of
reaching back into `tools/`.

`pythonkni/infrastructure/paths.py` owns application runtime/data paths. The old
`tools.app_paths` path remains as a very small compatibility alias so legacy imports
continue to resolve while first-party code can migrate to the infrastructure path.

Cross-cutting Qt/runtime infrastructure remains at the application edge:

- `tools/base_tool.py`: common Qt tool-window lifecycle contract.
- `tools/worker.py`: reusable Qt worker and signal adapter.
- `tools/theme_manager.py` and `tools/language_manager.py`: UI runtime managers.
- `tools/csv_utils.py`: spreadsheet-safe CSV helper used by presentation/export paths.
- `assets/`: static UI assets.

## Configuration boundary

Configuration persistence is split from UI runtime application:

```text
config/models.py
      ↑
config/service.py      # normalization + atomic persistence, no Qt/tools
      ↑
config/runtime.py      # applies values to ThemeManager/LanguageManager
      ↑
config/window.py
```

This keeps file-format and persistence rules testable without the UI while retaining
the current global theme/language manager behavior.

## Process Manager boundary

Process inspection and termination are owned by `process_manager/service.py`.
The window obtains a validated `ProcessDetails` snapshot, presents the required
confirmation dialogs and then delegates termination back to the service.

The service revalidates both PID liveness and process `create_time` immediately
before calling `terminate()`. This prevents PID reuse between user confirmation and
the destructive operation from targeting a different process.

The window is explicitly prevented by architecture tests from importing `psutil`.

## Compatibility adapters

The dynamic loader still discovers `tools/*_tool.py`, so the architecture changes do
not alter the plugin contract or menu behavior. Migrated tool modules are thin
adapters that expose the corresponding `pythonkni.<domain>.window` module.

Legacy compatibility modules that must continue to exist, such as
`tools.app_paths` and `tools.zip_7zip_utils`, delegate to the new implementation.
`tools.zip_7zip_utils` keeps only its old dialog-oriented helpers and forwards the
archive security API to `pythonkni.infrastructure.archives`, including legacy
monkeypatch behavior used by regression tests.

## Architecture enforcement

`tests/test_architecture_boundaries.py` turns these rules into CI-enforced checks.
It verifies that:

- every declared domain has `models.py`, `service.py` and `window.py`;
- models do not depend on Qt or `tools`;
- services do not depend on Qt, `tools.worker` or window modules;
- shared `pythonkni.infrastructure` modules do not depend on PyQt or `tools`;
- Archive consumes the framework-independent archive infrastructure;
- configuration persistence stays framework-independent;
- Process Manager presentation does not import `psutil`;
- loader-facing tool modules remain thin compatibility adapters;
- every domain window still implements the `BaseTool` contract.

## Coverage ratchet

The first full branch-coverage measurement of `pythonkni` + `tools` established an
initial repository baseline of **58.85%** with 289 tests passing, while aggregated
`pythonkni/*/service.py` coverage measured **64.7%**.

A focused coverage-hardening tranche then exercised the previously weakest
Windows-heavy services through deterministic unit tests that mock operating-system
boundaries instead of mutating the runner. The measured suite now contains **415
passing tests**, reaches **66.7% repository-wide branch coverage** and **81.1%
aggregated service-layer coverage**.

The targeted services now measure:

```text
pythonkni/startup/service.py        87.7%
pythonkni/event_viewer/service.py   95.4%
pythonkni/system_report/service.py  97.2%
```

PythonKni uses a ratchet: CI must not fall below measured floors, while focused
services keep their own gates so a regression cannot be hidden by improvements in
another module.

```text
repository-wide branch coverage                   >= 66.5%
all pythonkni/*/service.py coverage                >= 81.0%
Startup service coverage                           >= 87.5%
Event Viewer service coverage                      >= 95.0%
System Report service coverage                     >= 97.0%
refactored process/config/infrastructure coverage  >= 80%
```

The long-term targets remain **80% repository-wide** and **85% for the aggregated
service layer**. Remaining sub-80 service coverage is concentrated mainly in
Converter, Archive, PDF, Network and Temp Cleaner, making those the next useful
coverage targets.

Coverage is a guardrail rather than a substitute for behavioral assertions. Security,
rollback, cancellation, process identity and destructive-operation behavior continue
to have dedicated regression tests.
