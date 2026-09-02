# PythonKni

![Python](https://img.shields.io/badge/Python-3.13-3776AB)
![PyQt5](https://img.shields.io/badge/UI-PyQt5-41CD52)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)
![Tests](https://img.shields.io/badge/tests-1131%20pytest-green)
![Coverage](https://img.shields.io/badge/branch%20coverage-93.0%25-green)
![Services](https://img.shields.io/badge/service%20coverage-93.5%25-green)
![Dependencies](https://img.shields.io/badge/dependencies-SHA--256%20locked-blueviolet)
![Audit](https://img.shields.io/badge/security-pip--audit-success)
![Lint](https://img.shields.io/badge/lint-Ruff%20F%20%2B%20I-purple)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

PythonKni is a **local-first Windows desktop utility suite** built with Python and PyQt5. It combines file/PDF/archive operations, duplicate detection, network diagnostics and Network Intelligence, process inspection, startup management, Windows event analysis, system reporting, WiFi diagnostics and safe temporary-file cleanup in one application.

The repository is maintained as an application rather than a collection of scripts. First-party domains follow enforced dependency boundaries, long-running work is moved away from the GUI thread, destructive operations have explicit safeguards, dependencies are reproducibly locked and audited, and every push is validated through the real Windows packaging path.

> Use system, network, process and WiFi capabilities only on systems and networks you own or are explicitly authorized to administer.

---

## Toolset

| Tool | Main capabilities |
|---|---|
| **Archive Manager** | Create/extract ZIP and 7Z archives with hardened validation, staging, progress and cancellation |
| **File Converter** | Convert images, PDF, DOCX, TXT and KML, including batch TXT/KML workflows |
| **PDF Toolkit** | Merge, split, extract, reorder and read PDFs through `pypdf`; optional OCR for scanned documents |
| **Duplicate Finder** | Detect duplicates through staged hashing plus byte verification and move copies with restoration manifests |
| **Network Explorer** | Discover IPv4 interfaces/hosts, scan bounded TCP port ranges and explicitly fingerprint known-open services through the pinned Nerva engine |
| **Camera Exposure Auditor** | Audit authorized local camera exposure through bounded ONVIF/HTTP(S)/RTSP evidence without credentials or media retrieval |
| **Network Intelligence** | Persist local assets/relationships, accept explicit service-fingerprint enrichment, score exposure, compare/history snapshots, schedule checks, detect meaningful changes and manage bounded retention |
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

`tests/test_architecture_boundaries.py` makes these rules executable. Models and infrastructure cannot depend on Qt/tool presentation code, services cannot import windows, and OS mutations remain in the owning service instead of leaking into widgets.

Network Intelligence is a larger composed domain under `pythonkni/network_intelligence/`; its pure persistence/scoring/history/notification components remain separated from Qt composition and are covered by domain-specific regressions and an incremental structural typing ratchet.

See [`docs/architecture.md`](docs/architecture.md) for the detailed dependency rules and quality gates.

---

## Engineering highlights

### Managed background work

Long-running operations use reusable worker/lifecycle infrastructure and cooperative cancellation. `BaseTool` owns worker lifetime so active `QThread` instances are not destroyed when a window closes.

### Structured technical feedback

Technical failures across the current first-party windows use the shared `tools/ui_feedback.py` presentation contract where appropriate:

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

The optional service-fingerprinting engine is similarly reproducible: `third_party/nerva.lock.json` pins **Nerva v1.69.4** for Windows amd64 and SHA-256 `59e59eb54c8c5c581031387a0aa23c98983db94301e811f3c9b1802a05fc97f7`. Build/release staging verifies that digest before extraction and requires the upstream Apache-2.0 license; PythonKni never downloads Nerva at application runtime.

GitHub Actions are pinned by immutable commit SHA and Dependabot checks Python dependencies and Actions weekly. See [`docs/python-runtime.md`](docs/python-runtime.md) and [`docs/network-service-fingerprinting.md`](docs/network-service-fingerprinting.md).

### Network Intelligence quality controls

Network Intelligence keeps normal runtime OUI lookup fully offline while a build/maintenance-time updater can regenerate the bundled registry from the official IEEE MA-L CSV. The checked-in snapshot currently contains **40,046 unique OUI-24 assignments** plus provenance/hash metadata; normal runtime operation performs no IEEE lookup.

CI/release also enforce an incremental structural typing ratchet for `pythonkni/network_intelligence`. The current protected package baseline is **683/736 annotation slots (92.8%)**, **269 fully annotated / 308 tracked callables**, and at most **39 explicit `Any` annotations**. Fifteen strict modules must stay completely annotated with zero explicit `Any`. This is an AST annotation guardrail, not a substitute for semantic checking by `mypy`/`pyright`.

See [`docs/network-intelligence-quality-gates.md`](docs/network-intelligence-quality-gates.md) and [`docs/network-oui-registry.md`](docs/network-oui-registry.md).

### Real distributable validation

A source-test pass is not considered sufficient. CI first stages the exact pinned Nerva engine and its license/provenance, then builds the actual PyInstaller Windows bundle and verifies the packaged engine with:

```powershell
dist\PythonKni\_internal\third_party\nerva\nerva.exe --capabilities
dist\PythonKni\PythonKni.exe --smoke-test
```

The validated bundle is then packaged as ZIP/checksum, compiled into a per-user Inno Setup installer and exercised through a second real lifecycle smoke: silent install, execution of the **installed** EXE, silent uninstall and cleanup verification. See [`docs/network-service-fingerprinting.md`](docs/network-service-fingerprinting.md) and [`docs/windows-installer.md`](docs/windows-installer.md).

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
│  └─ network_intelligence/
├─ scripts/
│  ├─ benchmark_network_intelligence.py
│  ├─ build_windows_installer.ps1
│  ├─ check_dependency_locks.py
│  ├─ check_network_intelligence_typing.py
│  ├─ fetch_nerva.ps1
│  ├─ package_windows_bundle.ps1
│  ├─ smoke_test_windows_installer.ps1
│  └─ update_oui_registry.py
├─ third_party/
│  ├─ NOTICE.md
│  └─ nerva.lock.json
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

Optional OCR/document workflows can additionally require Tesseract OCR and Poppler. These executables are outside the Python dependency lock and Python SBOM.

---

## Configuration and privacy

Runtime data is stored outside the source tree under:

```text
%LOCALAPPDATA%\PythonKni\
```

PythonKni does not require an application account or backend service. Optional VirusTotal process analysis reads `VIRUSTOTAL_API_KEY`, hashes the selected executable locally and queries by SHA-256; it does not upload the executable itself, although the hash is disclosed to the provider.

Never commit or publicly share real API keys, WiFi credentials, private logs, scan histories or diagnostic reports. See [`docs/security.md`](docs/security.md).

---

## Testing and quality gates

The current behavior-driven suite contains **1,131 tests** on Windows / CPython 3.13.15.

```text
Repository-wide branch coverage                 93.0%
All pythonkni/*/service.py coverage              93.5%
Network Explorer base window coverage            93.4%
Nerva fingerprint adapter coverage               99.2%
```

Coverage ratchets remain at **>=92.5% repository-wide** and **>=93.0% across services**, with stronger per-service/per-window floors for already-hardened areas. Network Intelligence additionally has its own structural typing ratchet described above. CI's grouped PowerShell coverage gates explicitly fail on any native subcommand error so an individual ratchet cannot be masked by a later successful command.

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
pyinstaller --noconfirm --clean PythonKni.spec
dist\PythonKni\_internal\third_party\nerva\nerva.exe --capabilities
dist\PythonKni\PythonKni.exe --smoke-test
.\scripts\package_windows_bundle.ps1 -OutputPrefix "PythonKni-windows-x64"
.\scripts\build_windows_installer.ps1 -OutputPrefix "PythonKni-windows-x64-setup"
.\scripts\smoke_test_windows_installer.ps1 -InstallerPath ".\dist\PythonKni-windows-x64-setup.exe"
```

The workflow also applies individual coverage ratchets and retains the Windows ZIP/checksum, installer/checksum, `coverage.xml`, Network Intelligence benchmark JSON, CycloneDX SBOM, OUI provenance metadata, the exact Nerva lock and both dependency locks with the validated artifact.

---

## Packaging and releases

Local Windows build:

```powershell
.\scripts\fetch_nerva.ps1
pyinstaller --noconfirm --clean PythonKni.spec
dist\PythonKni\_internal\third_party\nerva\nerva.exe --capabilities
dist\PythonKni\PythonKni.exe --smoke-test
.\scripts\package_windows_bundle.ps1 -OutputPrefix "PythonKni-windows-x64"
.\scripts\build_windows_installer.ps1 -OutputPrefix "PythonKni-windows-x64-setup"
.\scripts\smoke_test_windows_installer.ps1 -InstallerPath ".\dist\PythonKni-windows-x64-setup.exe"
```

Tags matching exact `vX.Y.Z` trigger `.github/workflows/release.yml`. Release validation repeats dependency integrity/audit gates, OUI validation, tests, coverage and Network Intelligence typing ratchets, lint/format, pinned Nerva staging/packaged capability verification, PyInstaller build and frozen smoke testing. Installer-enabled release source additionally builds and smoke-tests the version-bound Inno Setup installer before publication.

`v0.1.0` is the first published public release and intentionally retains its original immutable source and six validated assets. Installer and Nerva packaging were added afterward; future enabled releases publish the versioned ZIP/checksum, setup EXE/checksum, SBOM, OUI metadata and dependency locks with Nerva embedded in the application bundle. Historical recovery never injects current installer or Nerva code/binaries into old immutable tags. See [`docs/release-readiness.md`](docs/release-readiness.md), [`docs/network-service-fingerprinting.md`](docs/network-service-fingerprinting.md) and [`docs/windows-installer.md`](docs/windows-installer.md).

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

For a conventional first-party domain, keep the adapter thin and put business/OS behavior in `service.py` and Qt orchestration in `window.py`. The loader/plugin contract is regression-tested by `tests/test_tool_contract.py`.

---

## Current limitations

- Windows is the only platform currently packaged and enforced by CI.
- Compatibility is currently claimed only for the Python 3.13 series and the normal GIL-enabled interpreter, not Python 3.14+, free-threaded builds or a broader platform matrix.
- OCR depends on local Tesseract/Poppler installation and document quality.
- DOCX -> PDF conversion is intentionally simplified and cannot reproduce every Microsoft Word layout feature.
- Network/system capabilities depend on Windows permissions, topology, firewall policy and available OS utilities.
- Nerva integration currently fingerprints TCP services on ports already confirmed open; UDP/SCTP and Nerva misconfiguration checks remain deliberately out of scope for this milestone.
- Localization infrastructure exists, but not every user-visible string is extracted/translated.
- Windows executable/installer Authenticode signing remains release-engineering work.

---

## Roadmap

### Release engineering

- [x] Publish and verify the first tagged GitHub Release (`v0.1.0`) from a fully green `main` commit.
- [x] Add per-user Windows installer generation and installed-app smoke validation.
- [ ] Add screenshots/demo media for the main application and representative tools.
- [ ] Add Windows Authenticode signing after certificate/identity and secret-handling policy is defined.

### Reliability and code quality

- [ ] Continue behavior-driven coverage where uncovered branches represent real failure, cancellation or OS-integration contracts; avoid percentage-only tests.
- [ ] Expand the Network Intelligence structural typing ratchet by removing legacy explicit `Any` and promoting additional modules to the strict set; evaluate a semantic `mypy`/`pyright` gate as a separate migration.
- [ ] Audit remaining long-running operations for consistent progress/cancellation semantics.
- [ ] Migrate deprecated PyMuPDF `fitz` imports to the current `pymupdf` API where applicable and review avoidable PyInstaller collection warnings.

### Product evolution

- [x] Add pinned Nerva-backed application-layer service fingerprinting and explicit Network Intelligence enrichment for known-open TCP ports.
- [ ] Build a **PC Health / System Intelligence dashboard** that composes existing services instead of duplicating their domain logic.
- [ ] Add a unified operation/history and recovery center for reversible maintenance actions.
- [ ] Add further defensive device-role context only when backed by explicit persisted evidence.
- [ ] Improve DOCX -> PDF formatting fidelity.
- [ ] Complete localization of user-visible strings.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — dependency boundaries, quality and packaging gates
- [`docs/network-intelligence.md`](docs/network-intelligence.md) — Network Intelligence architecture, features and safety boundaries
- [`docs/network-service-fingerprinting.md`](docs/network-service-fingerprinting.md) — pinned Nerva trust model, safe fingerprinting scope and explicit inventory enrichment
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

Keep backups before destructive file/system operations. Use network, process, Event Viewer, startup and WiFi-related features only where you have explicit authorization.

---

## License

MIT
