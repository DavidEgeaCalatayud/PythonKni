# Architecture

PythonKni is a PyQt5 desktop application with a dynamic tool loader. User-facing domains follow a layered structure so domain rules and operating-system integration remain testable without constructing Qt widgets. Build and dependency integrity are treated as part of the architecture rather than as external release chores.

## Dependency rule

The main application dependency direction is:

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

- `models.py` contains framework-independent value objects. It must not import PyQt or `tools` modules.
- `service.py` owns domain rules, operating-system integration, persistence, parsing and transformations. It must not import PyQt, `tools.worker` or a window module.
- `window.py` owns PyQt widgets, dialogs, user confirmation and background-thread orchestration. It delegates state-changing OS operations to services.
- `pythonkni/infrastructure/` contains framework-independent technical building blocks shared by multiple domains.
- `tools/*_tool.py` remains only as the dynamic-loader/legacy compatibility edge.

This keeps business and operating-system behavior independently testable and prevents presentation modules from becoming alternate service layers.

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

Each domain exposes `models.py`, `service.py` and `window.py`. A domain that currently has no custom value object still keeps an explicit framework-independent `models.py` boundary rather than moving future data structures into its UI.

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

`pythonkni/infrastructure/archives.py` owns archive path validation, extraction limits, staging/publication and ZIP/7Z extraction safety. It deliberately has no Qt dependency. The Archive service consumes this module directly instead of reaching back into `tools/`.

`pythonkni/infrastructure/paths.py` owns application runtime/data paths. The old `tools.app_paths` path remains as a small compatibility alias so legacy imports continue to resolve while first-party code uses the infrastructure path.

Cross-cutting Qt/runtime infrastructure remains at the application edge:

- `tools/base_tool.py`: common Qt tool-window lifecycle contract.
- `tools/worker.py`: reusable Qt worker and signal adapter.
- `tools/ui_feedback.py`: structured Qt feedback renderer that separates user-facing summaries from optional expandable technical details.
- `tools/theme_manager.py` and `tools/language_manager.py`: UI runtime managers.
- `tools/csv_utils.py`: spreadsheet-safe CSV helper used by presentation/export paths.
- `assets/`: static UI assets.

## Structured UI feedback boundary

Technical failures should not force raw exception text into the primary message shown to a user. `tools/ui_feedback.py` provides a presentation-only model and renderer for information, warnings and errors:

```text
service/worker exception
        ↓
window.py chooses actionable summary
        ↓
tools/ui_feedback.py
        ├─ primary text: concise user-facing message
        └─ detailed text: exception type/message or diagnostics
```

The helper is intentionally kept at the Qt/application edge rather than under `pythonkni/infrastructure`, because it depends on `QMessageBox`. Domain services remain unaware of how errors are rendered.

The first migration tranche covers loader discovery failures, configuration persistence failures, Archive background-task failures and Process Manager refresh/VirusTotal worker failures. Domain confirmations, destructive-operation warnings and other business-specific dialogs keep their existing flows. Remaining windows can migrate technical failures incrementally without changing service contracts.

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

This keeps file-format and persistence rules testable without the UI while retaining the current global theme/language manager behavior.

## Process Manager boundary

Process inspection and termination are owned by `process_manager/service.py`. The window obtains a validated `ProcessDetails` snapshot, presents the required confirmation dialogs and then delegates termination back to the service.

The service revalidates both PID liveness and process `create_time` immediately before calling `terminate()`. This prevents PID reuse between user confirmation and the destructive operation from targeting a different process.

The window is explicitly prevented by architecture tests from importing `psutil`.

## PDF boundary

PDF document reading/writing is based on the maintained `pypdf` backend. `pythonkni/pdf/service.py` owns the PDF business operations and keeps the UI independent from backend implementation details.

Other libraries retain narrower roles where needed: PyMuPDF supports rendering/text-oriented operations, ReportLab supports generated PDF output, and `pdf2image`/Tesseract participate in optional OCR flows. `PythonKni.spec` collects `pypdf`, not the retired `PyPDF2` package, so source and frozen-package dependency graphs remain aligned.

## Compatibility adapters

The dynamic loader still discovers `tools/*_tool.py`, so the architecture changes do not alter the plugin contract or menu behavior. Migrated tool modules are thin adapters that expose the corresponding `pythonkni.<domain>.window` module.

Legacy compatibility modules that must continue to exist, such as `tools.app_paths` and `tools.zip_7zip_utils`, delegate to the new implementation. `tools.zip_7zip_utils` keeps only its old dialog-oriented helpers and forwards the archive security API to `pythonkni.infrastructure.archives`, including legacy monkeypatch behavior used by regression tests.

## Dependency and supply-chain architecture

PythonKni separates **dependency policy** from the exact dependency graph used for Windows builds:

```text
requirements.in      ──pip-tools──► requirements.txt
requirements-dev.in  ──pip-tools──► requirements-dev.txt
       ranges                    exact versions + SHA-256 hashes
```

The canonical resolver/build environment is Windows with CPython 3.10.11. `pyproject.toml` declares Python `>=3.10` and the package-level dependency ranges; the `.in` files are the operational source of truth for direct runtime/development ranges, while the `.txt` files are committed reproducible locks.

The lock contract is deliberately strict:

- every resolved package uses an exact `==` version;
- every package entry carries one or more valid SHA-256 hashes;
- runtime/development duplicates must resolve to compatible identical versions;
- every direct dependency declared by an `.in` file must appear in its lock and satisfy the requested range;
- installation in CI/release uses `pip --require-hashes` rather than accepting arbitrary artifacts for a pinned version;
- `scripts/check_dependency_locks.py` and dedicated regressions enforce the structure.

CI then performs `pip check`, audits both locks with `pip-audit`, and generates a CycloneDX JSON SBOM. A dependency advisory therefore fails the build instead of being silently recorded. During this hardening phase the development audit exposed `PYSEC-2026-3447` in `setuptools 80.10.2`; the policy and lock were moved to patched `setuptools 84.0.0` rather than suppressing the finding.

GitHub Actions references are pinned to immutable commit SHAs. Dependabot checks Python dependencies and Actions weekly, but dependency changes still pass through the same lock, audit, test, build and smoke-test gates.

These controls protect repeatability and artifact integrity, but they do not prove that an upstream package is benign and do not cover external executables such as Tesseract or Poppler.

## CI and release path

The canonical validation path is:

```text
CPython 3.10.11 / Windows
          ↓
hash-locked runtime + dev install
          ↓
lock validation + pip check
          ↓
runtime/dev pip-audit + CycloneDX SBOM
          ↓
compileall + pytest + branch coverage
          ↓
coverage ratchets
          ↓
Ruff check + format
          ↓
PyInstaller build
          ↓
frozen PythonKni.exe --smoke-test
          ↓
ZIP + SHA-256 + coverage.xml + SBOM + locks
```

The release workflow repeats the same integrity gates before publishing a tag-driven GitHub Release. This avoids treating a source-only test pass as sufficient evidence that the shipped Windows bundle is valid.

## Architecture enforcement

`tests/test_architecture_boundaries.py` turns application-layer rules into CI-enforced checks. It verifies that:

- every declared domain has `models.py`, `service.py` and `window.py`;
- models do not depend on Qt or `tools`;
- services do not depend on Qt, `tools.worker` or window modules;
- shared `pythonkni.infrastructure` modules do not depend on PyQt or `tools`;
- Archive consumes the framework-independent archive infrastructure;
- configuration persistence stays framework-independent;
- Process Manager presentation does not import `psutil`;
- loader-facing tool modules remain thin compatibility adapters;
- every domain window still implements the `BaseTool` contract.

Dependency-lock behavior has its own focused regressions covering valid locks, missing hashes, malformed SHA-256 values and direct-version policy violations. Structured-feedback regressions verify severity/icon mapping, expandable diagnostics and that migrated windows keep raw technical errors out of their primary user-facing message.

## Coverage ratchet

The first full branch-coverage measurement of `pythonkni` + `tools` established an initial repository baseline of **58.85%** with 289 tests passing, while aggregated `pythonkni/*/service.py` coverage measured **64.7%**.

Behavior-driven coverage hardening then raised the repository to **84.7% branch coverage** and the aggregated service layer to **91.5%**. The current suite contains **545 tests** after the first structured-feedback regressions. The new feedback tests cover presentation behavior rather than changing service-layer metrics.

Key measured service coverage:

```text
pythonkni/archive/service.py        95.7%
pythonkni/converter/service.py      94.5%
pythonkni/network/service.py        96.7%
pythonkni/pdf/service.py            95.3%
pythonkni/startup/service.py        87.7%
pythonkni/event_viewer/service.py   95.4%
pythonkni/system_report/service.py  97.2%
pythonkni/temp_cleaner/service.py   86.4%
```

Priority Qt windows:

```text
pythonkni/startup/window.py         95.8%
pythonkni/event_viewer/window.py    98.9%
pythonkni/pdf/window.py             93.4%
```

Additional windows improved by the structured-feedback tranche:

```text
pythonkni/archive/window.py         70.2%
pythonkni/config/window.py          85.0%
pythonkni/process_manager/window.py 74.6%
tools/ui_feedback.py                80.0%
```

PythonKni uses a ratchet: CI must not fall below measured floors, while focused services/windows keep their own gates so a regression cannot be hidden by gains in another module. Floors intentionally leave a small margin below the measured results.

```text
repository-wide branch coverage                   >= 84.0%
all pythonkni/*/service.py coverage                >= 91.0%
Archive service coverage                           >= 95.0%
Converter service coverage                         >= 94.0%
Network service coverage                           >= 96.0%
PDF service coverage                               >= 95.0%
Startup service coverage                           >= 87.5%
Event Viewer service coverage                      >= 95.0%
System Report service coverage                     >= 97.0%
Temp Cleaner service coverage                      >= 86.0%
Startup window coverage                            >= 95.0%
Event Viewer window coverage                       >= 98.0%
PDF window coverage                                >= 93.0%
refactored process/config/infrastructure coverage  >= 84.0%
```

Future coverage work is selective rather than target-chasing. Lower-coverage presentation modules such as Converter, Temp Cleaner, Network and System Report remain useful candidates when additional tests validate meaningful behavior.

Coverage is a guardrail rather than a substitute for behavioral assertions. Security, rollback, cancellation, process identity, dependency integrity, user-feedback and destructive-operation behavior continue to have dedicated regressions.
