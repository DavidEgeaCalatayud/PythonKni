# Architecture

PythonKni is a PyQt5 Windows desktop application with a dynamic tool loader and an explicitly layered first-party codebase. Domain behavior and operating-system integration are independently testable from Qt, while dependency integrity, presentation orchestration, packaging and the frozen executable are treated as architectural concerns rather than afterthoughts.

## Dependency rule

The enforced application direction is:

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

Responsibilities:

- `models.py` contains framework-independent values and must not import PyQt or presentation helpers.
- `service.py` owns domain rules, persistence, parsing, transformations and OS integration. It must not import PyQt or a window module.
- `window.py` owns widgets, dialogs, confirmations and background-worker orchestration. It delegates domain/OS mutations to services.
- `pythonkni/core/` and `pythonkni/infrastructure/` contain reusable framework-independent primitives.
- `tools/*_tool.py` is the dynamic-loader / legacy-compatibility edge, not an alternate service layer.

`tests/test_architecture_boundaries.py` enforces these rules in CI.

## Domain layout

First-party domains currently follow the same structure:

```text
pythonkni/
├─ archive/
├─ config/
├─ converter/
├─ disk_analyzer/
├─ duplicate/
├─ event_viewer/
├─ network/
├─ pdf/
├─ process_manager/
├─ startup/
├─ system_report/
├─ temp_cleaner/
└─ wifi/
```

Each domain exposes `models.py`, `service.py` and `window.py`, even when a domain currently has only minimal custom model state. This prevents future data structures from drifting into presentation code.

## Core and infrastructure

Framework-independent shared code sits below the domain/UI boundary:

```text
pythonkni/
├─ core/
│  └─ tasks.py
└─ infrastructure/
   ├─ archives.py
   └─ paths.py
```

- `core/tasks.py` defines cooperative cancellation primitives.
- `infrastructure/archives.py` owns archive path validation, extraction limits, staging/publication and ZIP/7Z safety rules.
- `infrastructure/paths.py` owns application runtime/data locations.

Legacy modules such as `tools.app_paths` and `tools.zip_7zip_utils` remain compatibility facades where required, but first-party services depend on framework-independent infrastructure directly.

Cross-cutting Qt/runtime helpers remain at the application edge:

- `tools/base_tool.py` — common tool-window lifecycle and managed-worker contract;
- `tools/worker.py` — reusable Qt worker/signal adapter;
- `tools/ui_feedback.py` — structured technical feedback renderer;
- `tools/theme_manager.py` / `tools/language_manager.py` — UI runtime managers;
- `tools/csv_utils.py` — spreadsheet-safe CSV presentation/export helper.

## Presentation boundary and worker lifecycle

Qt windows are orchestration layers, not passive views. They own contracts that are now explicitly regression-tested:

```text
user action
   ↓
validation / confirmation
   ↓
worker creation + signal wiring
   ↓
service operation
   ↓
progress / result / error / cancellation
   ↓
UI state restoration + safe close
```

Coverage suites exercise overlapping-work rejection, stale/current callback handling, cooperative cancellation, deferred close, progress and result rendering, file/folder dialogs, import/export paths and structured technical errors. Production code is not altered merely to satisfy coverage; tests protect existing observable behavior.

`BaseTool` centralizes managed-worker ownership where applicable so active `QThread` instances are not destroyed while native work is still running. Domain windows with specialized workers retain equivalent lifecycle guarantees.

## Structured technical feedback boundary

Technical failures should not force raw exception text into normal user-facing copy:

```text
service / worker exception
          ↓
window chooses actionable summary
          ↓
tools/ui_feedback.py
   ├─ primary text: concise user-facing state/action
   └─ details: original exception type/message or diagnostics
```

The renderer stays under `tools/` because it depends on Qt. Services remain completely unaware of dialog rendering.

The current migration covers loader/configuration failures and technical error paths across Archive, Process Manager, Converter, PDF, Network, System Report, Disk Analyzer, Startup Manager, Temp Cleaner, WiFi, Event Viewer and Duplicate Finder. Input validation, destructive confirmations and domain warnings intentionally remain domain-specific rather than being forced through a generic abstraction.

## Configuration boundary

Configuration persistence is split from runtime UI application:

```text
config/models.py
      ↑
config/service.py      # normalization + atomic persistence, no Qt/tools
      ↑
config/runtime.py      # applies values to UI managers
      ↑
config/window.py
```

A failed persistence operation therefore does not require service code to know how themes/languages are rendered. Presentation regressions cover valid load, invalid-file fallback, normalized save and runtime UI refresh.

## Process Manager boundary

`process_manager/service.py` owns process inspection, identity validation and termination. The window presents the confirmation flow and delegates the final mutation.

Immediately before `terminate()`, the service revalidates PID liveness and process `create_time`. This protects against targeting a different process if Windows reuses the PID after the user originally selected it.

Architecture tests prevent `psutil` from drifting back into `process_manager/window.py`. Presentation regressions separately protect process-refresh worker state, confirmation/error paths and VirusTotal orchestration.

## PDF boundary

PDF reading/writing is based on maintained `pypdf`. `pdf/service.py` owns document operations; the window does not depend on backend implementation details.

PyMuPDF, ReportLab, `pdf2image` and Tesseract retain narrower rendering/report/OCR roles where needed. `PythonKni.spec` collects `pypdf`, keeping source and frozen dependency graphs aligned.

## Compatibility and plugin boundary

`main.py` discovers modules ending in `tools/*_tool.py`. A loader-compatible module exposes a valid `Tool` inheriting `BaseTool`, overrides `setup_ui()` and declares non-empty `name`, `description` and `category` metadata.

First-party adapters are intentionally thin. This preserves the dynamic plugin/menu contract while allowing application logic to live under `pythonkni/<domain>/`.

## Dependency and supply-chain architecture

Dependency policy is separated from the exact graph used for validated Windows builds:

```text
requirements.in      ──pip-tools──► requirements.txt
requirements-dev.in  ──pip-tools──► requirements-dev.txt
       ranges                    exact versions + SHA-256 hashes
```

The canonical environment is Windows / **CPython 3.13.15** using the normal GIL-enabled interpreter. `pyproject.toml` supports the Python 3.13 series (`>=3.13,<3.14`) and Ruff targets `py313`. Python 3.14+ and free-threaded builds are not currently claimed.

The lock contract requires:

- exact `==` pins;
- one or more valid SHA-256 hashes for each resolved entry;
- all direct `.in` requirements to be present and satisfy their policy range;
- compatible identical pins where runtime/development graphs overlap;
- CI/release installation through `pip --require-hashes`.

`scripts/check_dependency_locks.py` and dedicated tests enforce this structure. CI additionally runs `pip check`, strict runtime/development `pip-audit` gates and a CycloneDX JSON SBOM generation step. `tests/test_python_runtime_contract.py` keeps the runtime pin, project metadata and Ruff target synchronized.

GitHub Actions references are pinned to immutable commit SHAs. Dependabot proposes Python/Action updates weekly, but every resulting change must still pass the same lock, audit, test, build and smoke gates.

## CI and release path

The canonical validation path is:

```text
CPython 3.13.15 / Windows
          ↓
hash-locked runtime + dev install
          ↓
lock validation + pip check
          ↓
runtime/dev pip-audit + CycloneDX SBOM
          ↓
compileall
          ↓
1,052 pytest tests + branch coverage
          ↓
repository/service/priority-window coverage ratchets
          ↓
Ruff check + format
          ↓
PyInstaller build
          ↓
frozen PythonKni.exe --smoke-test
          ↓
ZIP + SHA-256 + coverage.xml + SBOM + locks
```

Release validation mirrors the same quality gates before publishing a tag-driven GitHub Release. CI and Release use the same coverage floors so distribution cannot bypass a regression rejected on normal pushes. See [`python-runtime.md`](python-runtime.md) for the interpreter migration and support contract.

## Architecture enforcement

Architecture regressions verify, among other rules, that:

- every declared domain has `models.py`, `service.py` and `window.py`;
- models do not depend on Qt or `tools`;
- services do not depend on Qt, `tools.worker` or windows;
- `pythonkni.infrastructure` stays framework-independent;
- archive services consume framework-independent archive infrastructure;
- configuration persistence remains framework-independent;
- Process Manager presentation does not import `psutil`;
- loader-facing modules remain thin adapters;
- every domain window still satisfies the `BaseTool` contract;
- CI, release, maintenance, project metadata and Ruff remain aligned on the supported Python 3.13 runtime.

Other focused suites protect archive extraction safety, Temp Cleaner path identity, startup rollback, duplicate revalidation/manifests, process PID identity, CSV injection, worker lifecycle, dependency locks, runtime contract and structured feedback behavior.

## Coverage model

Coverage is a non-regression guardrail, not a target to game.

Historical progression:

```text
Initial measured baseline
289 tests
58.85% repository branch coverage
64.7% aggregated services

Service-hardening baseline
578 tests
86.4% repository branch coverage
93.2% aggregated services

Presentation-hardened baseline
686 tests
92.9% repository branch coverage
93.2% aggregated services

Current runtime-migration baseline
1,052 tests
92.8% repository branch coverage
93.5% aggregated services
```

Current service measurements include the established non-regression floors below; additional Network Intelligence services are covered by the repository and domain-specific suites.

```text
Archive service                 95.7%
Config service                  96.2%
Converter service               94.5%
Disk Analyzer service           95.0%
Duplicate service               90.5%
Event Viewer service            95.4%
Network service                 96.7%
PDF service                     95.3%
Process Manager service         99.3%
Startup service                 87.7%
System Report service           97.2%
Temp Cleaner service            86.4%
WiFi service                    96.0%
```

Current presentation measurements:

```text
Archive window                  97.2%
Config window                   90.7%
Converter window                86.9%
Disk Analyzer window            96.9%
Duplicate Finder window         97.4%
Event Viewer window             98.9%
Network window                  91.5%
PDF window                      93.1%
Process Manager window          98.0%
Startup window                  95.3%
System Report window            94.7%
Temp Cleaner window             94.2%
WiFi window                     95.0%
```

Coverage expansion remains behavior-driven: worker overlap and cancellation, stale/current results, deferred close behavior, conversion/dialog flows, Network history I/O, Process Manager/VirusTotal states, archive/duplicate operations, Disk Analyzer export paths, Temp Cleaner confirmation/error handling, Config load/save application, WiFi loading states, System Report generation/export orchestration and Network Intelligence persistence/history/notification contracts.

### Enforced ratchets

```text
repository-wide branch coverage                   >= 92.5%
all pythonkni/*/service.py coverage                >= 93.0%
Archive service coverage                           >= 95.0%
Converter service coverage                         >= 94.0%
Disk Analyzer service coverage                     >= 94.5%
Duplicate service coverage                         >= 90.0%
Network service coverage                           >= 96.0%
PDF service coverage                               >= 95.0%
Process Manager service coverage                   >= 99.0%
Startup service coverage                           >= 87.5%
Event Viewer service coverage                      >= 95.0%
System Report service coverage                     >= 97.0%
Temp Cleaner service coverage                      >= 86.0%
WiFi service coverage                              >= 95.5%
Archive window coverage                            >= 96.5%
Config window coverage                             >= 90.0%
Converter window coverage                          >= 86.0%
Disk Analyzer window coverage                      >= 96.0%
Duplicate Finder window coverage                   >= 97.0%
Event Viewer window coverage                       >= 98.0%
Network window coverage                            >= 91.0%
PDF window coverage                                >= 93.0%
Process Manager window coverage                    >= 97.5%
Startup window coverage                            >= 95.0%
System Report window coverage                      >= 94.0%
Temp Cleaner window coverage                       >= 93.5%
WiFi window coverage                               >= 94.5%
process/config/infrastructure aggregate             >= 88.5%
```

The floors deliberately retain margin below measured values. Converter remains the lowest measured first-party window, so future coverage work should focus only on meaningful uncovered orchestration/failure contracts rather than forcing every module toward an arbitrary identical percentage.
