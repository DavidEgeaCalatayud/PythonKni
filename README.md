# PythonKni

![Python](https://img.shields.io/badge/Python-3.13-3776AB)
![PyQt5](https://img.shields.io/badge/UI-PyQt5-41CD52)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)
![Tests](https://img.shields.io/badge/tests-full%20CI%20suite-green)
![Coverage](https://img.shields.io/badge/branch%20coverage-%3E%3D92.5%25-green)
![Services](https://img.shields.io/badge/service%20coverage-%3E%3D93.0%25-green)
![Dependencies](https://img.shields.io/badge/dependencies-SHA--256%20locked-blueviolet)
![Audit](https://img.shields.io/badge/security-pip--audit-success)
![Lint](https://img.shields.io/badge/lint-Ruff%20F%20%2B%20I-purple)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

PythonKni is a **local-first Windows desktop utility suite** built with Python and PyQt5. It combines file/PDF/archive operations, duplicate detection, network discovery and Network Intelligence, passive network traffic observability, hop-by-hop path/latency diagnostics, explicit-target web reconnaissance, secure peer-to-peer transfer, process inspection, startup management, Windows event analysis, system reporting, WiFi diagnostics and safe temporary-file cleanup in one application.

The repository is maintained as an application rather than a collection of scripts. First-party domains follow enforced dependency boundaries, long-running work is moved away from the GUI thread, destructive operations have explicit safeguards, dependencies are reproducibly locked and audited, pinned native components are verified before packaging, and every candidate is validated through the real Windows packaging/installer path.

> Use system, network, process, web-reconnaissance and WiFi capabilities only on systems and networks you own or are explicitly authorized to administer.

---

## Toolset

| Tool | Main capabilities |
|---|---|
| **Archive Manager** | Create/extract ZIP and 7Z archives with hardened validation, staging, progress and cancellation |
| **File Converter** | Convert images, PDF, DOCX, TXT and KML, including batch TXT/KML workflows |
| **PDF Toolkit** | Merge, split, extract, reorder and read PDFs through `pypdf`; optional OCR for scanned documents |
| **Duplicate Finder** | Detect duplicates through staged hashing plus byte verification and move copies with restoration manifests |
| **Network Explorer** | Discover IPv4 interfaces/hosts, scan bounded TCP ranges, identify known-open TCP services, explicitly probe bounded UDP profiles, run explicit Nerva misconfiguration checks and expose SCTP only when the upstream platform capability exists |
| **Camera Exposure Auditor** | Audit authorized local camera exposure through bounded ONVIF/HTTP(S)/RTSP evidence without credentials or media retrieval |
| **Web Recon Auditor** | Audit DNS, TLS, HTTP security posture and bounded web-surface evidence for one explicit URL/hostname without CIDR or internet-wide discovery |
| **Network Intelligence** | Persist assets/relationships and service evidence, apply bounded finding-aware Security Score rules, compare/history snapshots, schedule checks, optionally fingerprint known TCP services before snapshots, detect meaningful changes and manage retention |
| **Network Traffic Monitor** | Observe local adapter RX/TX rates and TCP/UDP socket/process/host activity, generate temporal alerts/history, optionally enrich public destinations, and explicitly capture with Windows `pktmon` |
| **Network Path Analyzer** | Trace one explicit target through ICMP/UDP/TCP, aggregate per-hop RTT/loss/jitter, identify stable route changes/latency jumps and publish path events to History Center through a pinned Trippy backend |
| **Secure Transfer** | Send text/files/folders and create temporary secure tunnels/localhost-only port forwards through an isolated, pinned Tailcat transport |
| **Process Manager** | Inspect processes, filter resource use, safely terminate selected processes and query optional VirusTotal reports |
| **Temporary Cleaner** | Preview and clean explicitly authorized temporary/cache targets without following symlinks/reparse points |
| **WiFi Profiles** | Read locally stored Windows WiFi profiles for authorized support/diagnostics |
| **Disk Analyzer** | Rank large files/directories and export analysis results |
| **Windows Startup Manager** | Inspect and reversibly enable/disable supported registry/folder startup entries |
| **Windows Event Viewer** | Read, classify, filter and export Windows event information |
| **System Report** | Collect system/disk/network/process/temp diagnostics and export TXT/HTML/PDF reports |
| **Configuration** | Persist theme/language settings outside the repository using atomic writes |

---

## Architecture

The enforced dependency direction for conventional first-party domains is:

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

At runtime:

```text
main.py
  │
  ├─ discovers tools/*_tool.py
  ▼
thin adapter
  ▼
pythonkni/<domain>/window.py
  │  Qt presentation, confirmations, worker orchestration
  ▼
pythonkni/<domain>/service.py
  │  domain rules, OS integration, persistence, transformations
  ▼
pythonkni/<domain>/models.py
     framework-independent values

services ─────► pythonkni/core + pythonkni/infrastructure
```

`tests/test_architecture_boundaries.py` makes these rules executable. Models and infrastructure cannot depend on Qt/tool presentation code, services cannot import windows, and OS mutations remain in the owning service instead of leaking into widgets. Network Monitor, Network Path, Web Recon and Secure Transfer are included in the same domain matrix as the established first-party tools.

Network Intelligence is a larger composed domain under `pythonkni/network_intelligence/`; persistence, scoring, fingerprints, scheduling, history and notification logic remain separated from Qt composition and are covered by domain-specific regressions and an incremental structural typing ratchet.

See [`docs/architecture.md`](docs/architecture.md) for the detailed dependency rules and quality gates.

---

## Engineering highlights

### Managed background work

Long-running operations use reusable worker/lifecycle infrastructure and cooperative cancellation. `BaseTool` owns worker lifetime so active `QThread` instances are not destroyed when a window closes.

### Structured technical feedback

Technical failures across first-party windows use the shared `tools/ui_feedback.py` presentation contract where appropriate:

```text
service/worker exception
        ↓
window chooses actionable summary
        ↓
primary message + expandable diagnostics
```

Raw exception text is kept out of normal user-facing copy while the original diagnostic remains available through **Show Details**. Input validation, destructive-operation confirmations and business/domain warnings intentionally remain explicit domain dialogs rather than being forced through a generic error abstraction.

### Safer destructive operations

PythonKni treats destructive filesystem/system operations as explicit trust boundaries:

- archive extraction rejects traversal, unsafe Windows paths, links/special files and suspicious archive limits before publishing staged output;
- duplicate detection uses size, quick hashing, SHA-256 and final byte equality, ignores hardlinks and revalidates candidates before movement;
- duplicate moves keep restoration manifests with completed/failed/cancelled state;
- converter/PDF publication is staged or transactional where supported;
- startup changes preserve recoverable state and rollback metadata;
- CSV exports neutralize spreadsheet-formula injection;
- Temp Cleaner validates exact authorized roots, rejects symlink/reparse traversal and revalidates directory identity around deletion;
- process termination revalidates PID liveness and `create_time` immediately before mutation.

### Reproducible dependency and supply-chain controls

Dependency policy and the exact build graph are intentionally separate:

```text
requirements.in      ──pip-tools──► requirements.txt
requirements-dev.in  ──pip-tools──► requirements-dev.txt
       ranges                     exact pins + SHA-256 hashes
```

The canonical resolver/build environment is Windows with **CPython 3.13.15** using the normal GIL-enabled interpreter. PythonKni supports the Python 3.13 series (`>=3.13,<3.14`). CI and release jobs install both locks with `pip --require-hashes`, validate lock structure and installed consistency, run strict runtime/development `pip-audit`, and generate a CycloneDX JSON SBOM before application validation continues.

Native optional components are also reproducible rather than runtime-downloaded:

- `third_party/nerva.lock.json` pins **Nerva v1.69.4** for Windows amd64 and verifies the upstream archive/license before staging;
- `third_party/tailcat.lock.json` pins **Tailcat v0.5.0** for Windows amd64; staging verifies the official archive SHA-256, records/revalidates the executable digest and runs a real CLI contract smoke before Secure Transfer accepts it;
- `third_party/trippy.lock.json` pins **Trippy v0.13.0** for Windows x86_64 MSVC; staging verifies the official archive SHA-256, the extracted executable digest and every CLI option consumed by Network Path Analyzer before packaging.

GitHub Actions are pinned by immutable commit SHA and Dependabot checks Python dependencies and Actions weekly. See [`docs/python-runtime.md`](docs/python-runtime.md), [`docs/network-service-fingerprinting.md`](docs/network-service-fingerprinting.md), [`docs/secure-transfer.md`](docs/secure-transfer.md) and [`docs/network-path-analyzer.md`](docs/network-path-analyzer.md).

### Service Intelligence v2

Network Explorer deliberately separates increasingly active operations:

```text
TCP port discovery
      ↓ explicit
Identify services
      ↓ separate explicit action
Check insecure configurations (--misconfigs)

UDP profile/probe ── explicit + bounded
SCTP ─────────────── advanced + capability-aware
```

Normal TCP service identification still operates on ports already confirmed open. UDP probing uses finite selected profiles/timeouts and preserves protocol uncertainty: an identified responder is `open`, while an unanswered probe is `open|filtered` rather than falsely marked closed. The first-party model also supports `closed` and `unknown` when explicit evidence exists.

`--misconfigs` is only enabled by the dedicated **Check insecure configurations** action. Its normalized findings retain id, severity, title, description, impact, recommendation, CVSS and evidence. No mode performs credentials/default-password guessing, brute force or exploitation.

SCTP is modeled but Nerva v1.69.4 exposes it only on Linux, so the validated Windows application disables/refuses SCTP instead of claiming unsupported behavior.

Network Intelligence persists UDP/SCTP observations as transport-qualified evidence rather than inserting them into the legacy TCP `open_ports` tuple. Security findings can influence the project-defined Security Score only through deterministic bounded deductions: critical `-12`, high `-8`, medium `-4`, low `-1`, info/unknown `0`, maximum **20 points per asset**. Service evidence alone does not rewrite the device classification or persisted `RiskLevel`.

Scheduled monitoring offers `Disabled`, `Manual only`, `Automatic after discovery` and `Only assets with known changes`. Automatic modes are intentionally narrower than the manual UI: known TCP ports only, maximum 32 assets and 16 ports per asset, 8 Nerva workers, 2 connections per host, 1500 ms timeout, and **never** `--misconfigs`, UDP or SCTP.

See [`docs/network-service-fingerprinting.md`](docs/network-service-fingerprinting.md) and [`docs/network-intelligence.md`](docs/network-intelligence.md).

### Network Traffic Monitor

Network Traffic Monitor is a first-party passive temporal-observability domain, not an unrestricted packet sniffer and not a hidden mutation path into Network Intelligence.

```text
Windows adapter counters + socket table
              ↓
pythonkni/network_monitor/service.py
              ↓
bounded deterministic observations
              ↓
network_monitor/intelligence.py
              ↓
read-only known-asset join + canonical temporal publication
              ↓
Network Intelligence notifications / History Center
```

The monitor reports exact adapter RX/TX rates and current TCP/UDP socket ownership where Windows exposes it. Process rows describe socket activity; PythonKni does **not** fabricate per-process byte counters. Reverse DNS is bounded and public ASN/prefix enrichment through RIPEstat is opt-in.

Temporal events include new external connections/remote hosts/listening ports, process network activity, traffic spikes, known-asset connections and unusual destinations. Canonical publication uses replay-safe occurrence identifiers: exact replay deduplicates while later recurrences remain temporal history. The asset join is read-only and cannot synthesize Network Intelligence assets, rewrite classification or mutate persisted `RiskLevel`.

Packet capture remains a separate explicit action backed by Windows `pktmon`, with ETL -> PCAPNG conversion where supported. No monitor path performs packet injection, credential/default-password attempts, exploitation, payload decryption or internet-wide discovery.

See [`docs/network-traffic-monitor.md`](docs/network-traffic-monitor.md) and [`docs/network-monitor-intelligence-integration.md`](docs/network-monitor-intelligence-integration.md).

### Network Path Analyzer

Network Path Analyzer is the hop-by-hop diagnostic layer that sits naturally after discovery, intelligence and passive traffic observation:

```text
Network Explorer        -> what exists?
Network Intelligence    -> what do we know/history?
Network Traffic Monitor -> what connections are happening?
Network Path Analyzer   -> where does path latency/degradation begin?
```

PythonKni accepts one explicit hostname/IP and uses an isolated, pinned **Trippy 0.13.0** backend for ICMP/UDP/TCP path probes. The Trippy TUI is not embedded. The first-party `network_path` domain owns validation, rolling statistics, route comparison, temporal-event semantics, persistence and Qt presentation.

The Path view exposes responding host/IP sets, response loss, last/average/min/max RTT, jitter and status per TTL plus a destination RTT timeline. Route changes require repeated confirmation. `destination_unreachable` requires repeated destination misses. `latency_spike` requires both an absolute and relative deviation from a rolling destination baseline.

Most importantly, PythonKni does **not** interpret one intermediate router failing to return TTL-expired/ICMP diagnostic traffic as end-to-end packet loss. `packet_loss` is based on destination observations, while transient silent middle hops are retained against the confirmed route for comparison. This avoids a common traceroute/MTR false-positive pattern caused by router rate limiting.

Path events (`route_changed`, `latency_spike`, `packet_loss`, `hop_added`, `hop_removed`, `destination_unreachable`) publish into the same canonical Change Notification inbox and History Center used by Network Traffic Monitor, tagged with source `Network Path Analyzer` and without creating synthetic Network Intelligence assets.

On Windows, Trippy's tracing modes require Administrator privileges for raw sockets. PythonKni reports that requirement explicitly instead of silently changing measurement semantics.

See [`docs/network-path-analyzer.md`](docs/network-path-analyzer.md).

### Web Recon Auditor

Web Recon starts from one explicit HTTP/HTTPS URL or DNS hostname. It does not accept CIDR/range input. DNS, TLS, HTTP security posture and bounded discovery/enrichment remain behind first-party components and do not turn a single target into internet-wide discovery.

See [`docs/web-recon-auditor.md`](docs/web-recon-auditor.md).

### Secure Transfer

Secure Transfer isolates Tailcat behind `pythonkni/secure_transfer/tailcat_backend.py`; PythonKni does not parse or reimplement Tailcat's unstable wire format. PythonKni-managed operations use the exact supported runtime and ephemeral keys, file/folder sends require Windows OpenSSH `scp.exe`, directory receiving is opt-in and port forwarding binds only to `127.0.0.1`.

The feature does not modify Windows routing/DNS, persist Tailcat keys, enable exit-node/auth-free-SSH/read-write-share behavior or create `0.0.0.0` forwards. Tailcat's public DERP relays are upstream fallback infrastructure, not a PythonKni availability SLA.

See [`docs/secure-transfer.md`](docs/secure-transfer.md).

### Network Intelligence quality controls

Network Intelligence keeps normal runtime OUI lookup fully offline while a build/maintenance-time updater can regenerate the bundled registry from the official IEEE MA-L CSV. The checked-in snapshot currently contains **40,046 unique OUI-24 assignments** plus provenance/hash metadata; normal runtime operation performs no IEEE lookup.

CI/release enforce an incremental structural typing ratchet for `pythonkni/network_intelligence`. The threshold is encoded in the checker/workflows and strict modules cannot regress. This AST annotation guardrail is not a substitute for semantic checking by `mypy`/`pyright`.

See [`docs/network-intelligence-quality-gates.md`](docs/network-intelligence-quality-gates.md) and [`docs/network-oui-registry.md`](docs/network-oui-registry.md).

### Real distributable validation

A source-test pass is not considered sufficient. CI stages and verifies the exact pinned native components supported by the source, builds the actual PyInstaller Windows bundle and verifies the packaged application before distribution.

The validated bundle is packaged as ZIP/checksum, compiled into a per-user Inno Setup installer and exercised through a second real lifecycle smoke: silent install, execution of the **installed** EXE, silent uninstall and cleanup verification. The common ZIP packager also refuses a source that declares Nerva/Tailcat/Trippy but is missing the corresponding valid packaged runtime. See [`docs/release-readiness.md`](docs/release-readiness.md) and [`docs/windows-installer.md`](docs/windows-installer.md).

---

## Project structure

```text
PythonKni/
├─ .github/
│  ├─ dependabot.yml
│  └─ workflows/
│     ├─ ci.yml
│     └─ release.yml
├─ assets/
│  ├─ network_oui_prefixes.csv
│  └─ network_oui_prefixes.meta.json
├─ docs/
│  ├─ architecture.md
│  ├─ network-intelligence.md
│  ├─ network-service-fingerprinting.md
│  ├─ network-traffic-monitor.md
│  ├─ network-monitor-intelligence-integration.md
│  ├─ network-path-analyzer.md
│  ├─ web-recon-auditor.md
│  ├─ secure-transfer.md
│  ├─ network-scheduled-monitoring.md
│  ├─ network-change-notifications.md
│  ├─ network-history-center.md
│  ├─ network-score-history.md
│  ├─ network-snapshot-comparison.md
│  ├─ network-oui-registry.md
│  ├─ network-intelligence-quality-gates.md
│  ├─ python-runtime.md
│  ├─ release-readiness.md
│  ├─ security.md
│  ├─ usage.md
│  └─ windows-installer.md
├─ installer/
│  └─ PythonKni.iss
├─ pythonkni/
│  ├─ core/
│  ├─ infrastructure/
│  ├─ network/
│  ├─ network_intelligence/
│  ├─ network_monitor/
│  ├─ network_path/
│  ├─ web_recon/
│  └─ secure_transfer/
├─ scripts/
│  ├─ benchmark_network_intelligence.py
│  ├─ build_windows_installer.ps1
│  ├─ check_dependency_locks.py
│  ├─ check_network_intelligence_typing.py
│  ├─ check_tailcat_contract.ps1
│  ├─ check_trippy_contract.ps1
│  ├─ fetch_nerva.ps1
│  ├─ fetch_tailcat.ps1
│  ├─ fetch_trippy.ps1
│  ├─ package_windows_bundle.ps1
│  ├─ smoke_test_windows_installer.ps1
│  └─ update_oui_registry.py
├─ third_party/
│  ├─ NOTICE.md
│  ├─ nerva.lock.json
│  ├─ tailcat.lock.json
│  └─ trippy.lock.json
├─ tests/
├─ tools/                       # adapters + shared Qt/runtime helpers
├─ main.py
├─ PythonKni.spec
├─ pyproject.toml
├─ requirements.in
├─ requirements.txt
├─ requirements-dev.in
├─ requirements-dev.txt
├─ CHANGELOG.md
└─ LICENSE
```

---

## Requirements and installation

PythonKni supports:

```text
Python >= 3.13, < 3.14
```

The canonical Windows CI/release environment is **CPython 3.13.15** using the normal GIL-enabled build. Python 3.14+ and free-threaded CPython builds are not currently claimed as supported.

```powershell
git clone https://github.com/DavidEgeaCalatayud/PythonKni.git
cd PythonKni
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python main.py
```

For development/CI tooling:

```powershell
python -m pip install --require-hashes -r requirements-dev.txt
```

Optional OCR/document workflows can additionally require Tesseract OCR and Poppler. Secure Transfer file/folder sending additionally requires Windows OpenSSH Client (`scp.exe`). Network Path Analyzer's Trippy backend is staged by the build rather than installed through pip; on Windows its tracing modes require running PythonKni with Administrator privileges. These executables/native capabilities are outside the Python dependency lock and Python SBOM.

---

## Configuration and privacy

Runtime data is stored outside the source tree under:

```text
%LOCALAPPDATA%\PythonKni\
```

PythonKni does not require an application account or backend service. Optional VirusTotal process analysis reads `VIRUSTOTAL_API_KEY`, hashes the selected executable locally and queries by SHA-256; it does not upload the executable itself, although the hash is disclosed to the provider. Network Traffic Monitor ASN/prefix enrichment is opt-in and discloses public-destination lookup data to RIPEstat when enabled. Web Recon can contact the explicitly selected target and its documented optional enrichment sources. Secure Transfer uses the upstream Tailcat data plane/DERP behavior described in its dedicated trust documentation. Network Path Analyzer sends only the explicitly requested ICMP/UDP/TCP diagnostic probes toward the chosen target/path and forces Trippy DNS resolution through the system resolver; it does not enable Trippy ASN lookups.

Never commit or publicly share real API keys, WiFi credentials, private logs, scan histories, transfer tokens or diagnostic reports. See [`docs/security.md`](docs/security.md).

---

## Testing and quality gates

The canonical Windows workflow runs the **full current test suite** on the candidate commit instead of documenting a test-count snapshot that becomes stale as domains are added.

```text
Repository-wide branch coverage floor            >=92.5%
All pythonkni/*/service.py coverage floor         >=93.0%
Additional service/window/refactored-code floors  enforced by CI/Release
```

Network Intelligence additionally has its structural typing ratchet. CI's grouped PowerShell coverage gates explicitly fail on any native subcommand error so an individual ratchet cannot be masked by a later successful command.

### CI-equivalent validation

```powershell
python scripts/check_dependency_locks.py
python -m pip check
python -m pip_audit -r requirements.txt --no-deps --strict --progress-spinner=off
python -m pip_audit -r requirements-dev.txt --no-deps --strict --progress-spinner=off
python -m compileall .
python scripts/update_oui_registry.py validate
python -m pytest --cov=pythonkni --cov=tools --cov-branch --cov-report=term-missing --cov-report=xml
python -m coverage report --fail-under=92.5
python -m coverage report --include="pythonkni/*/service.py" --fail-under=93.0
python -m scripts.benchmark_network_intelligence
python -m scripts.check_network_intelligence_typing
python -m ruff check .
python -m ruff format --check .
.\scripts\fetch_nerva.ps1
.\scripts\fetch_tailcat.ps1
.\scripts\fetch_trippy.ps1
pyinstaller --noconfirm --clean PythonKni.spec
dist\PythonKni\PythonKni.exe --smoke-test
.\scripts\package_windows_bundle.ps1 -OutputPrefix "PythonKni-windows-x64"
.\scripts\build_windows_installer.ps1 -OutputPrefix "PythonKni-windows-x64-setup"
.\scripts\smoke_test_windows_installer.ps1 -InstallerPath ".\dist\PythonKni-windows-x64-setup.exe"
```

The workflow also applies individual coverage ratchets, verifies staged/packaged native components and retains the validated Windows artifact plus dependency/supply-chain evidence.

---

## Packaging and releases

Local Windows build:

```powershell
.\scripts\fetch_nerva.ps1
.\scripts\fetch_tailcat.ps1
.\scripts\fetch_trippy.ps1
pyinstaller --noconfirm --clean PythonKni.spec
dist\PythonKni\PythonKni.exe --smoke-test
.\scripts\package_windows_bundle.ps1 -OutputPrefix "PythonKni-windows-x64"
.\scripts\build_windows_installer.ps1 -OutputPrefix "PythonKni-windows-x64-setup"
.\scripts\smoke_test_windows_installer.ps1 -InstallerPath ".\dist\PythonKni-windows-x64-setup.exe"
```

Tags matching exact `vX.Y.Z` trigger `.github/workflows/release.yml`. Release validation repeats dependency integrity/audit gates, OUI validation, tests, coverage and Network Intelligence typing ratchets, lint/format, pinned native-component staging/verification, PyInstaller build and frozen smoke testing. Installer-enabled release source additionally builds and smoke-tests the version-bound Inno Setup installer before publication.

`v0.1.0` is the first published public release and intentionally retains its original immutable source/assets. Installer, Nerva, Tailcat and Trippy packaging were added afterward; historical recovery never injects current installer/native binaries into old immutable tags. See [`docs/release-readiness.md`](docs/release-readiness.md), [`docs/network-service-fingerprinting.md`](docs/network-service-fingerprinting.md), [`docs/secure-transfer.md`](docs/secure-transfer.md), [`docs/network-path-analyzer.md`](docs/network-path-analyzer.md) and [`docs/windows-installer.md`](docs/windows-installer.md).

Windows Authenticode signing is not yet implemented and remains a separate release-engineering milestone.

---

## Adding a first-party tool

A loader-compatible module under `tools/` must end in `_tool.py`, expose `Tool`, inherit `tools.base_tool.BaseTool`, override `setup_ui()`, and define non-empty `name`, `description` and `category` metadata.

Minimal loader-facing contract:

```python
from tools.base_tool import BaseTool


class Tool(BaseTool):
    name = "My New Tool"
    description = "Describe what the tool does"
    category = "Utilities"

    def setup_ui(self):
        # Build the Qt presentation layer here.
        pass
```

For a conventional first-party domain, keep the adapter thin and put business/OS behavior in `service.py` and Qt orchestration in `window.py`. The loader/plugin contract is regression-tested by `tests/test_tool_contract.py` and `tests/test_architecture_boundaries.py`.

---

## Current limitations

- Windows is the only platform currently packaged and enforced by CI.
- Compatibility is currently claimed only for the Python 3.13 series and the normal GIL-enabled interpreter, not Python 3.14+, free-threaded builds or a broader platform matrix.
- OCR depends on local Tesseract/Poppler installation and document quality.
- DOCX -> PDF conversion is intentionally simplified and cannot reproduce every Microsoft Word layout feature.
- Network/system capabilities depend on Windows permissions, topology, firewall policy and available OS utilities.
- Network Traffic Monitor visibility depends on Windows counters/socket telemetry and socket lifetime; absence of an observation is not proof that traffic did not exist.
- Network Path Analyzer requires Administrator privileges on Windows for Trippy raw-socket tracing; intermediate diagnostic response loss is not automatically forwarding loss, and a target can filter one probe protocol while remaining otherwise reachable.
- Nerva SCTP fingerprinting is unavailable in the validated Windows package because Nerva v1.69.4 restricts SCTP to Linux.
- UDP probing is intentionally bounded and preserves `open|filtered` uncertainty when there is no conclusive response.
- Misconfiguration checks are explicit only and are never part of normal or scheduled fingerprinting.
- Tailcat is experimental upstream and does not promise stable CLI/API/wire format; Secure Transfer therefore pins one supported release and isolates it behind a replaceable backend.
- Tailcat public DERP relays are fallback infrastructure with rate limits/no PythonKni SLA; mutually untrusted-party use remains subject to upstream trust-model limitations.
- Secure Transfer file/folder send requires Windows OpenSSH `scp.exe`.
- Localization infrastructure exists, but not every user-visible string is extracted/translated.
- Windows executable/installer Authenticode signing remains release-engineering work.

---

## Roadmap

### Release engineering

- [x] Publish and verify the first tagged GitHub Release (`v0.1.0`) from a fully green `main` commit.
- [x] Add per-user Windows installer generation and installed-app smoke validation.
- [x] Add reproducible Nerva, Tailcat and Trippy native-component staging/packaging verification.
- [ ] Add screenshots/demo media for the main application and representative tools.
- [ ] Add Windows Authenticode signing after certificate/identity and secret-handling policy is defined.

### Reliability and code quality

- [ ] Continue behavior-driven coverage where uncovered branches represent real failure, cancellation or OS-integration contracts; avoid percentage-only tests.
- [ ] Expand the Network Intelligence structural typing ratchet by removing legacy explicit `Any` and promoting additional modules to the strict set; evaluate a semantic `mypy`/`pyright` gate as a separate migration.
- [ ] Audit remaining long-running operations for consistent progress/cancellation semantics.
- [ ] Migrate deprecated PyMuPDF `fitz` imports to the current `pymupdf` API where applicable and review avoidable PyInstaller collection warnings.

### Product evolution

- [x] Add pinned Nerva-backed application-layer service fingerprinting and explicit Network Intelligence enrichment for known-open TCP ports.
- [x] Add Service Intelligence v2: explicit misconfiguration checks, bounded UDP probing, capability-aware SCTP and scheduled TCP fingerprint policies.
- [x] Add Web Recon Auditor for explicit-target web reconnaissance.
- [x] Add Secure Transfer with isolated pinned Tailcat transport.
- [x] Add passive Network Traffic Monitor with temporal Network Intelligence integration and explicit Windows capture.
- [x] Add Trippy-backed Network Path Analyzer with conservative hop/path diagnostics and History Center integration.
- [ ] Build a **PC Health / System Intelligence dashboard** that composes existing services instead of duplicating their domain logic.
- [ ] Add a unified operation/history and recovery center for reversible maintenance actions.
- [ ] Add further defensive device-role context only when backed by explicit persisted evidence.
- [ ] Improve DOCX -> PDF formatting fidelity.
- [ ] Complete localization of user-visible strings.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — dependency boundaries, quality and packaging gates
- [`docs/network-intelligence.md`](docs/network-intelligence.md) — Network Intelligence architecture, service evidence, scheduling and safety boundaries
- [`docs/network-service-fingerprinting.md`](docs/network-service-fingerprinting.md) — pinned Nerva trust model, TCP/UDP/SCTP/misconfiguration modes and scheduled fingerprint contract
- [`docs/network-traffic-monitor.md`](docs/network-traffic-monitor.md) — passive traffic telemetry, capture and operational limits
- [`docs/network-monitor-intelligence-integration.md`](docs/network-monitor-intelligence-integration.md) — temporal publication/read-only Network Intelligence integration
- [`docs/network-path-analyzer.md`](docs/network-path-analyzer.md) — pinned Trippy backend, hop/path semantics, route changes and temporal integration
- [`docs/web-recon-auditor.md`](docs/web-recon-auditor.md) — explicit-target web reconnaissance and scope limits
- [`docs/secure-transfer.md`](docs/secure-transfer.md) — Tailcat transport pin, trust model and secure-transfer behavior
- [`docs/network-scheduled-monitoring.md`](docs/network-scheduled-monitoring.md) — in-app scheduling and automatic snapshot semantics
- [`docs/network-change-notifications.md`](docs/network-change-notifications.md) — meaningful-change notification engine
- [`docs/network-history-center.md`](docs/network-history-center.md) — automatic history catalog, trends and retention
- [`docs/network-oui-registry.md`](docs/network-oui-registry.md) — official IEEE MA-L snapshot maintenance and provenance
- [`docs/network-intelligence-quality-gates.md`](docs/network-intelligence-quality-gates.md) — incremental structural typing ratchet
- [`docs/python-runtime.md`](docs/python-runtime.md) — supported interpreter series and runtime validation contract
- [`docs/release-readiness.md`](docs/release-readiness.md) — release workflow, immutable recovery and distribution contract
- [`docs/windows-installer.md`](docs/windows-installer.md) — installer, checksum, smoke and uninstall contract
- [`docs/usage.md`](docs/usage.md) — operation, cancellation, permissions and troubleshooting
- [`docs/security.md`](docs/security.md) — security controls, sensitive-data flows and supply-chain limits
- [`CHANGELOG.md`](CHANGELOG.md) — development history

---

## Disclaimer

PythonKni is an educational and personal productivity project provided as-is, without warranty.

Keep backups before destructive file/system operations. Use network, process, Event Viewer, startup, web-reconnaissance and WiFi-related features only where you have explicit authorization.

---

## License

MIT
