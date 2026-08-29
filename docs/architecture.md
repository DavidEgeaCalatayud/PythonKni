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
existing repository baseline of **58.85%** with all 289 tests passing. Enforcing an
80% repository-wide threshold immediately would therefore make CI permanently red
without distinguishing new regressions from historical untested UI/OS paths.

PythonKni uses a ratchet instead: CI must never fall below conservative floors based
on the measured baseline, while new/refactored critical code is held to a stronger
standard.

```text
repository-wide branch coverage                   >= 58%
all pythonkni/*/service.py coverage                >= 64%
refactored process/config/infrastructure coverage  >= 80%
```

The long-term targets remain **80% repository-wide** and **85% for services**. The
ratchet floors should only move upward as additional tests are added; they should not
be reduced to make a failing change pass.

Coverage is a guardrail rather than a substitute for behavioral assertions. Security,
rollback, cancellation, process identity and destructive-operation behavior continue
to have dedicated regression tests.
