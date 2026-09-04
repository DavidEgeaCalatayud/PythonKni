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

Conventional first-party domains follow the same structure under `pythonkni/` (Archive, Camera Auditor, Config, Converter, Disk Analyzer, Duplicate, Event Viewer, Network, **Network Monitor**, PDF, Process Manager, **Secure Transfer**, Startup, System Report, Temp Cleaner, **Web Recon** and WiFi).

Network Intelligence is intentionally broader because it composes persistence, classification, topology, history, scheduling, notifications, reporting and specialized Qt views. Its pure modules stay separate from presentation composition rather than being forced into one oversized service/window pair.

The architecture-boundary test declares every conventional domain centrally. This means adding Web Recon, Secure Transfer or Network Monitor cannot silently bypass the same models/service/window/tool-adapter contract used by the older tools.

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
- `infrastructure/paths.py` owns application runtime/data locations, including bounded Network Monitor history paths.

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

### Network Traffic Monitor integration boundary

Network Traffic Monitor is a separate first-party domain rather than a packet-capture implementation hidden inside Network Intelligence:

```text
pythonkni/network_monitor/
├─ models.py
├─ service.py
├─ intelligence.py
├─ capture.py
├─ integration.py
└─ window.py
          │
          ├─ read-only known-asset join
          │
          └─ canonical temporal events
                    ↓
pythonkni/network_intelligence/temporal_notifications.py
                    ↓
network_intelligence_notifications.json
                    ↓
History Center / temporal_history_window.py
```

`service.py`, `models.py`, `intelligence.py`, `capture.py` and `integration.py` remain outside the Qt presentation boundary. The monitor reads exact interface counters and OS socket telemetry, then derives bounded deterministic observations. It does not claim per-process byte counters when Windows only exposes socket ownership.

The Network Intelligence join is deliberately **read-only**. Monitor observations can refer to a known persisted asset but cannot create synthetic assets, rewrite classification or mutate persisted `RiskLevel`. Temporal publication reuses the canonical notification store and replay-safe occurrence identifiers, so exact replay deduplicates while a later recurrence remains a new observation.

Windows packet capture is a separate explicit capability boundary owned by `capture.py` and backed by `pktmon`; it is not enabled by normal passive monitoring. No monitor path performs packet injection, credential/default-password attempts, exploitation, payload decryption or internet-wide discovery. RIPEstat ASN/prefix enrichment is opt-in, bounded and the only external metadata lookup in this domain.

See [`network-traffic-monitor.md`](network-traffic-monitor.md) and [`network-monitor-intelligence-integration.md`](network-monitor-intelligence-integration.md).

### Web Recon boundary

`pythonkni/web_recon/` starts from one explicit HTTP/HTTPS URL or DNS hostname. It deliberately does not accept CIDR/range scope. DNS, TLS, HTTP and bounded discovery/enrichment components stay behind the first-party service boundary, with active behavior constrained to the explicit target model rather than general internet-wide discovery.

See [`web-recon-auditor.md`](web-recon-auditor.md).

### Offline OUI architecture

Runtime vendor resolution reads only `assets/network_oui_prefixes.csv`. The build/maintenance command `scripts/update_oui_registry.py` can consume the official IEEE Registration Authority MA-L CSV, normalize it deterministically and publish the CSV plus `network_oui_prefixes.meta.json`. CI/release validate the checked-in registry offline and retain the provenance metadata with artifacts. The current snapshot contains 40,046 unique OUI-24 assignments.

### Incremental typing architecture

`scripts/check_network_intelligence_typing.py` parses first-party Network Intelligence modules with `ast` and enforces structural annotation non-regression. The enforced threshold is versioned in the script/CI rather than copied here as a volatile snapshot. Fifteen strict modules must remain completely structurally annotated with no explicit `Any` under the current policy.

This gate does not infer types or prove semantic correctness and is explicitly not a replacement for `mypy` or `pyright`. See [`network-intelligence-quality-gates.md`](network-intelligence-quality-gates.md).

## Secure Transfer / Tailcat boundary

Secure Transfer keeps Tailcat behind `pythonkni/secure_transfer/tailcat_backend.py`; no other PythonKni layer parses or reimplements Tailcat's unstable ConnBlob/CBOR/wire format.

```text
secure_transfer/window.py
          ↓
secure_transfer/service.py
          ↓
secure_transfer/tailcat_backend.py
          ↓
pinned tailcat.exe
```

The supported Windows Tailcat executable is build-time staged from `third_party/tailcat.lock.json`, verified before packaging and rechecked through its real CLI contract. PythonKni-managed operations use ephemeral keys, subprocesses run without a shell, port forwarding binds only to `127.0.0.1`, directory receive is opt-in and file/folder send depends on the Windows OpenSSH `scp.exe` capability.

The domain does not modify the routing table/DNS, persist Tailcat keys, enable exit-node/auth-free-SSH/read-write-share behavior or expose PythonKni-created `0.0.0.0` forwards. See [`secure-transfer.md`](secure-transfer.md).

## Dependency and supply-chain architecture

Dependency policy is separated from the exact graph used for validated Windows builds:

```text
requirements.in      ──pip-tools──► requirements.txt
requirements-dev.in  ──pip-tools──► requirements-dev.txt
       ranges                    exact versions + SHA-256 hashes
```

The canonical environment is Windows / **CPython 3.13.15** using the normal GIL-enabled interpreter. `pyproject.toml` supports the Python 3.13 series (`>=3.13,<3.14`) and Ruff targets `py313`. Python 3.14+ and free-threaded builds are not currently claimed.

The lock contract requires exact pins, approved SHA-256 hashes, all direct policy requirements, compatible overlap between runtime/dev graphs and `pip --require-hashes` installation. CI additionally runs `pip check`, strict runtime/development `pip-audit` and CycloneDX SBOM generation. GitHub Actions are pinned to immutable commit SHAs.

Native optional engines/transports use independent reproducible locks. Nerva is pinned and staged for service intelligence; Tailcat is pinned and staged for Secure Transfer. Both are verified before PyInstaller packaging, and their staged/packaged contracts are exercised by CI rather than being downloaded dynamically by normal application runtime.

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
full pytest suite + branch coverage
          ↓
repository/service/priority/refactored-code coverage ratchets
          ↓
Network Intelligence benchmark smoke
          ↓
Network Intelligence typing ratchet
          ↓
Ruff check + format
          ↓
pinned Nerva + Tailcat staging/contract verification
          ↓
PyInstaller build
          ↓
packaged Nerva + Tailcat verification
          ↓
frozen PythonKni.exe --smoke-test
          ↓
ZIP + installer
          ↓
installed PythonKni.exe --smoke-test
          ↓
validated artifact upload
```

Release validation mirrors the same quality gates before publishing a tag-driven GitHub Release. CI and Release use the same coverage and Network Intelligence typing floors so distribution cannot bypass a regression rejected on normal candidate validation.

## Architecture enforcement

Architecture/runtime regressions verify, among other rules, that models/services preserve their dependency boundary, shared infrastructure stays framework-independent, Process Manager presentation does not own `psutil` termination, loader-facing modules remain adapters, windows preserve the `BaseTool` contract, and CI/release/OUI maintenance/project metadata/Ruff stay aligned on Python 3.13.

The domain matrix explicitly includes Network Monitor, Web Recon and Secure Transfer alongside the older first-party domains. Other focused suites protect archive extraction safety, Temp Cleaner path identity, startup rollback, duplicate revalidation/manifests, process PID identity, CSV injection, worker lifecycle, dependency/native-supply-chain locks, runtime contract, Network Intelligence history/notification/retention semantics, Network Monitor temporal integration and structured feedback behavior.

## Coverage model

Coverage is a non-regression guardrail, not a target to game. Historical progression is retained in the changelog and CI history, while this architecture contract records the currently enforced floors instead of a volatile test-count snapshot:

```text
repository branch coverage       >= 92.5%
aggregate service.py coverage    >= 93.0%
```

Additional service/window/refactored-code floors remain encoded directly in CI/release. Coverage expansion remains behavior-driven: tests should protect failure, cancellation, persistence, safety or orchestration contracts rather than merely increase a percentage.

See [`release-readiness.md`](release-readiness.md) for the release gate summary.