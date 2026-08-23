# Architecture

PythonKni is a PyQt5 desktop application with a dynamic tool loader. Every
user-facing domain follows the same layered structure so domain and operating
system logic are separated from Qt presentation code.

## Dependency rule

The dependency direction is:

```text
models.py  <-  service.py  <-  window.py  <-  tools/*_tool.py adapter
```

- `models.py` contains framework-independent value objects. It must not import
  PyQt or `tools` modules.
- `service.py` owns domain rules, operating-system integration, persistence,
  parsing and transformations. It must not import PyQt, `tools.worker` or a
  window module.
- `window.py` owns PyQt widgets, dialogs and background-thread orchestration.
- `tools/*_tool.py` remains only as the loader/legacy compatibility adapter.

This lets business rules run in unit tests without constructing a QApplication
and prevents UI modules from becoming the owner of persistence, parsing,
operating-system calls or document transformations. Cooperative task cancellation
uses `pythonkni/core/tasks.py`, so long-running services do not depend on the Qt
`Worker` implementation.

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

Each directory exposes `models.py`, `service.py` and `window.py`. A domain that
currently has no custom value object still keeps an explicit framework-independent
`models.py` boundary rather than putting future data structures back into a
service or window module.

## Shared infrastructure

Shared application infrastructure remains outside the domain packages where it is
intentionally cross-cutting:

- `main.py`: application entry point and dynamic tool menu.
- `pythonkni/core/tasks.py`: framework-independent cooperative cancellation.
- `tools/base_tool.py`: common Qt tool-window lifecycle contract.
- `tools/worker.py`: reusable Qt worker and signal adapter.
- `tools/app_paths.py`: application-specific filesystem paths.
- `tools/csv_utils.py`: shared spreadsheet-safe CSV helpers.
- `tools/theme_manager.py`, `tools/language_manager.py` and logging helpers:
  application-wide UI/runtime infrastructure.
- `assets/`: static UI assets.

These modules are infrastructure rather than user-facing domains; they are not
allowed to become alternate homes for domain business logic.

## Compatibility adapters

The dynamic loader still discovers `tools/*_tool.py`, so the migration does not
change the plugin contract or menu behavior. Migrated tool modules are thin
adapters that expose the corresponding `pythonkni.<domain>.window` module. Legacy
imports and existing tests therefore continue to resolve while the implementation
lives under `pythonkni/`.

Where older tests or integrations monkeypatch symbols through a legacy tool
module, the compatibility layer forwards those assignments to the separated
service module so dependency injection behavior is preserved during the migration.

## Architecture enforcement

`tests/test_architecture_boundaries.py` enumerates the complete domain set and
checks that:

- every domain has `models.py`, `service.py` and `window.py`;
- models do not depend on Qt or `tools`;
- services do not depend on Qt, `tools.worker` or windows;
- loader-facing tool modules stay thin compatibility adapters;
- every domain window still implements the `BaseTool` contract.

This turns the layered architecture into a CI-enforced boundary rather than a
convention that can silently regress.
