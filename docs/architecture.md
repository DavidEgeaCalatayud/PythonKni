# Architecture

PythonKni is a PyQt5 Windows desktop application with a dynamic tool loader and an explicitly layered first-party codebase. Domain behavior and operating-system integration are independently testable from Qt, while dependency integrity, presentation orchestration, Network Intelligence quality controls, packaging and the frozen executable are treated as architectural concerns rather than afterthoughts.

## Dependency rule

The enforced application direction for conventional first-party domains is:

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

Conventional first-party domains follow the same structure under `pythonkni/` (Archive, Config, Converter, Disk Analyzer, Duplicate, Event Viewer, Network, PDF, Process Manager, Startup, System Report, Temp Cleaner and WiFi). Camera Auditor also keeps its models/service/window separation.

Network Intelligence is intentionally broader because it composes persistence, classification, topology, history, scheduling, notifications, reporting and specialized Qt views. Its pure modules stay separate from presentation composition rather than being forced into one oversized service/window pair.

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

Cross-cutting Qt/runtime helpers remain at the application edge: `tools/base_tool.py`, `tools/worker.py`, `tools/ui_feedback.py`, theme/language managers and spreadsheet-safe CSV helpers.

## Presentation boundary and worker lifecycle

Qt windows are orchestration layers, not passive views:

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

Coverage suites exercise overlapping-work rejection, stale/current callback handling, cooperative cancellation, deferred close, progress/result rendering, file/folder dialogs, import/export paths and structured technical errors. `BaseTool` centralizes managed-worker ownership where applicable so active `QThread` instances are not destroyed while native work is still running.

## Structured technical feedback boundary

Technical failures should not force raw exception text into normal user-facing copy. `tools/ui_feedback.py` keeps concise user-facing state/action separate from expandable exception/diagnostic details. Services remain unaware of dialog rendering; input validation, destructive confirmations and domain warnings remain domain-specific.

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

A failed persistence operation therefore does not require service code to know how themes/languages are rendered.

## Process Manager boundary

`process_manager/service.py` owns process inspection, identity validation and termination. Immediately before `terminate()`, the service revalidates PID liveness and process `create_time`, protecting against PID reuse. Presentation owns confirmation/orchestration, not the destructive OS call.

## PDF boundary

PDF reading/writing is based on maintained `pypdf`. PyMuPDF, ReportLab, `pdf2image` and Tesseract retain narrower rendering/report/OCR roles where needed. `PythonKni.spec` keeps the frozen dependency graph aligned with source behavior.

## Compatibility and plugin boundary

`main.py` discovers modules ending in `tools/*_tool.py`. A loader-compatible module exposes a valid `Tool` inheriting `BaseTool`, overrides `setup_ui()` and declares non-empty `name`, `description` and `category` metadata. First-party adapters remain intentionally thin.

## Network Intelligence boundaries

Network Intelligence is a local/persisted intelligence composition rather than an unrestricted scanner. The runtime boundary remains private/local/link-local/loopback IPv4, bounded to at most 256 hosts per Network Intelligence run, with no credential/default-password attempts, no camera-content retrieval and no internet-wide discovery.

Downstream components operate on already persisted or validated saved state:

```text
bounded local discovery
       ↓
inventory + relationships
       ↓
score / topology / reporting
       ↓
automatic snapshots
       ↓
history + comparison + notifications + retention
```

History/comparison/notification analysis does not silently trigger a network scan. Scheduler execution is opt-in and in-process while the Network Intelligence window is open; it is not a Windows service/daemon.

### Offline OUI architecture

Runtime vendor resolution reads only `assets/network_oui_prefixes.csv`. The build/maintenance command `scripts/update_oui_registry.py` can consume the official IEEE Registration Authority MA-L CSV, normalize it deterministically and publish the CSV plus `network_oui_prefixes.meta.json`. CI/release validate the checked-in registry offline and retain the provenance metadata with artifacts. The current snapshot contains 40,046 unique OUI-24 assignments.

### Incremental typing architecture

`scripts/check_network_intelligence_typing.py` parses first-party Network Intelligence modules with `ast` and enforces structural annotation non-regression. The protected package baseline is:

```text
tracked callables                  >= 303
fully annotated callables         >= 263   (current: 264)
annotation slots                  >= 721
annotated slots                   >= 668
annotation coverage               >= 92.64% (current: 92.65%)
explicit Any                      <= 39
```

Fifteen strict modules must remain 100% structurally annotated and contain no explicit `Any`. This gate does not infer types or prove semantic correctness and is explicitly not a replacement for `mypy` or `pyright`. See [`network-intelligence-quality-gates.md`](network-intelligence-quality-gates.md).

## Dependency and supply-chain architecture

Dependency policy is separated from the exact graph used for validated Windows builds:

```text
requirements.in      ──pip-tools──► requirements.txt
requirements-dev.in  ──pip-tools──► requirements-dev.txt
       ranges                    exact versions + SHA-256 hashes
```

The canonical environment is Windows / **CPython 3.13.15** using the normal GIL-enabled interpreter. `pyproject.toml` supports the Python 3.13 series (`>=3.13,<3.14`) and Ruff targets `py313`. Python 3.14+ and free-threaded builds are not currently claimed.

The lock contract requires exact pins, approved SHA-256 hashes, all direct policy requirements, compatible overlap between runtime/dev graphs and `pip --require-hashes` installation. CI additionally runs `pip check`, strict runtime/development `pip-audit` and CycloneDX SBOM generation. GitHub Actions are pinned to immutable commit SHAs.

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
compileall + bundled IEEE OUI validation
          ↓
1,060 pytest tests + branch coverage
          ↓
repository/service/priority coverage ratchets
          ↓
Network Intelligence benchmark smoke
          ↓
Network Intelligence typing ratchet
          ↓
Ruff check + format
          ↓
PyInstaller build
          ↓
frozen PythonKni.exe --smoke-test
          ↓
ZIP + SHA-256 + coverage.xml + benchmark + SBOM + OUI metadata + locks
```

Release validation mirrors the same quality gates before publishing a tag-driven GitHub Release. CI and Release use the same coverage and Network Intelligence typing floors so distribution cannot bypass a regression rejected on normal pushes.

## Architecture enforcement

Architecture/runtime regressions verify, among other rules, that models/services preserve their dependency boundary, shared infrastructure stays framework-independent, Process Manager presentation does not own `psutil` termination, loader-facing modules remain adapters, windows preserve the `BaseTool` contract, and CI/release/OUI maintenance/project metadata/Ruff stay aligned on Python 3.13.

Other focused suites protect archive extraction safety, Temp Cleaner path identity, startup rollback, duplicate revalidation/manifests, process PID identity, CSV injection, worker lifecycle, dependency locks, runtime contract, Network Intelligence history/notification/retention semantics and structured feedback behavior.

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

Current pre-release quality-gate baseline
1,060 tests
92.8% repository branch coverage
93.5% aggregated services
Network Intelligence typing coverage 92.65%
```

Current service measurements remain protected by the established individual ratchets; repository-wide branch coverage must stay >=92.5%, aggregate `service.py` coverage >=93.0%, and the process/config/infrastructure aggregate >=88.5%. Priority window/service floors remain encoded directly in CI/release.

Coverage expansion remains behavior-driven: tests should protect failure, cancellation, persistence, safety or orchestration contracts rather than merely increase a percentage.

See [`release-readiness.md`](release-readiness.md) for the first-release gate summary.