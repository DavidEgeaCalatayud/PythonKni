# Architecture

PythonKni is a PyQt5 desktop application with a dynamic tool loader. The core
architecture now separates domain logic from Qt windows for the largest tools.

## Dependency rule

The preferred dependency direction is:

`models.py` → standard-library/domain data only

`service.py` → models + infrastructure libraries, **never PyQt5**

`window.py` → PyQt5 + models + services

`tools/*_tool.py` → thin compatibility adapter exposing `Tool` to the dynamic loader

This lets business rules run in unit tests without constructing a QApplication
and prevents UI code from becoming the owner of persistence, parsing, operating
system calls, or document transformations.

## Current layout

- `main.py`: application entry point and dynamic tool menu.
- `pythonkni/event_viewer/`
  - `models.py`: `EventItem` and `EventResult`.
  - `service.py`: Windows event collection, parsing, risk classification and exports.
  - `window.py`: Qt worker, detail dialog and tool window.
- `pythonkni/startup/`
  - `models.py`: startup-entry domain model.
  - `service.py`: registry/startup-folder discovery and transactional enable/disable logic.
  - `window.py`: startup-manager Qt window.
- `pythonkni/system_report/`
  - `models.py`: report data model.
  - `service.py`: collection and TXT/HTML/PDF rendering.
  - `window.py`: report worker and Qt window.
- `pythonkni/pdf/`
  - `service.py`: PDF parsing, splitting, merging, OCR and reorder tasks.
  - `window.py`: PDF Toolkit Qt window.
- `tools/*_tool.py`: loader-compatible adapters. The four migrated tools contain
  no business implementation there.
- `tools/worker.py`: reusable asynchronous Qt worker infrastructure.
- `tools/app_paths.py`: application-specific filesystem paths.
- `assets/`: static UI assets.

## Migration strategy

The loader still discovers `tools/*_tool.py`, so the refactor does not change the
plugin contract or menu behavior. New or substantially modified tools should put
domain code under `pythonkni/<domain>/` first and keep the legacy module as an
adapter. Remaining tools can be migrated incrementally with the same pattern.

A `models.py` module is used when a domain has stable data structures. Domains
without a useful model should not create placeholder classes merely to satisfy a
folder convention.
