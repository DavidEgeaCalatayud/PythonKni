# PythonKni

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![PyQt5](https://img.shields.io/badge/UI-PyQt5-41CD52)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)
![Tests](https://img.shields.io/badge/tests-578%20pytest-green)
![Coverage](https://img.shields.io/badge/branch%20coverage-86.4%25-green)
![Services](https://img.shields.io/badge/service%20coverage-93.2%25-green)
![Dependencies](https://img.shields.io/badge/dependencies-SHA--256%20locked-blueviolet)
![Audit](https://img.shields.io/badge/security-pip--audit-success)
![Lint](https://img.shields.io/badge/lint-Ruff%20F%20%2B%20I-purple)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

PythonKni is a **local-first Windows desktop utility suite** built with Python and PyQt5. It combines file and PDF operations, archive handling, duplicate detection, network diagnostics, process inspection, startup management, Windows event analysis, system reporting, WiFi diagnostics and safe temporary-file cleanup in one application.

The repository is maintained as an application rather than a collection of scripts. First-party domains follow an enforced layered architecture, long-running work is moved away from the GUI thread, destructive operations have explicit safeguards, dependencies are reproducibly locked and audited, and every push is validated through the real Windows packaging path.

> Use system, network, process and WiFi capabilities only on systems and networks you own or are explicitly authorized to administer.

---

## Toolset

| Tool | Main capabilities |
|---|---|
| **Archive Manager** | Create/extract ZIP and 7Z archives with hardened validation, staging, progress and cancellation |
| **File Converter** | Convert images, PDF, DOCX, TXT and KML, including batch TXT/KML workflows |
| **PDF Toolkit** | Merge, split, extract, reorder and read PDFs through `pypdf`; optional OCR for scanned documents |
| **Duplicate Finder** | Detect duplicates through staged hashing plus byte verification and move copies with restoration manifests |
| **Network Explorer** | Discover IPv4 interfaces/hosts, resolve names, inspect ARP data and scan bounded TCP port ranges |
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

The enforced dependency direction is:

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

Current layered domains:

```text
archive          config           converter
 disk_analyzer   duplicate        event_viewer
 network          pdf              process_manager
 startup          system_report    temp_cleaner
 wifi
```

Shared framework-independent infrastructure lives under `pythonkni/core` and `pythonkni/infrastructure`. Loader-facing modules under `tools/*_tool.py` remain thin compatibility adapters so the dynamic plugin contract can coexist with the layered codebase.

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

Raw exception text is kept out of normal user-facing copy while the original diagnostic remains available through **Show Details**. Loader/configuration failures and the Archive, Process Manager, Converter, PDF, Network, System Report, Disk Analyzer, Startup, Temp Cleaner, WiFi, Event Viewer and Duplicate Finder technical paths have been migrated.

Input validation, destructive-operation confirmations and business/domain warnings intentionally remain explicit domain dialogs rather than being forced through a generic error abstraction.

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

The canonical resolver/build environment is Windows with **CPython 3.10.11**. CI and release jobs:

1. install both locks with `pip --require-hashes`;
2. validate lock structure;
3. run `pip check`;
4. audit runtime and development graphs with `pip-audit`;
5. generate a CycloneDX JSON SBOM;
6. continue only if the graph is valid and no known vulnerability is reported.

GitHub Actions are pinned by immutable commit SHA and Dependabot checks Python dependencies and Actions weekly.

### Real distributable validation

A source-test pass is not considered sufficient. CI builds the actual PyInstaller Windows bundle and runs:

```powershell
dist\PythonKni\PythonKni.exe --smoke-test
```

before producing the validated ZIP/checksum artifact.

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
├─ docs/
│  ├─ architecture.md
│  ├─ security.md
│  └─ usage.md
├─ pythonkni/
│  ├─ core/
│  ├─ infrastructure/
│  └─ <domain>/
│     ├─ models.py
│     ├─ service.py
│     └─ window.py
├─ scripts/
│  ├─ check_dependency_locks.py
│  └─ package_windows_bundle.ps1
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

## Requirements

### Python

```text
Python >= 3.10
```

The canonical Windows CI/release environment is **CPython 3.10.11**.

### Python dependencies

Runtime dependencies include PyQt5, `pypdf`, PyMuPDF, ReportLab, Pillow, python-docx, psutil, requests, py7zr, pytesseract and pdf2image. Direct policy ranges live in `requirements.in`/`pyproject.toml`; exact transitive distributions and SHA-256 hashes live in `requirements.txt`.

### Optional external dependencies

OCR/document workflows can additionally require:

- Tesseract OCR;
- Poppler.

These executables are outside the Python dependency lock and Python SBOM.

---

## Installation

```powershell
git clone https://github.com/DavidEgeaCalatayud/PythonKni.git
cd PythonKni
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python main.py
```

For development/CI tooling:

```powershell
python -m pip install --require-hashes -r requirements-dev.txt
```

### Updating dependencies

Do not hand-edit generated transitive pins or hashes. Change the relevant `.in` policy and regenerate the lock from the canonical Windows / CPython 3.10.11 environment:

```powershell
python -m piptools compile requirements.in --generate-hashes --allow-unsafe --strip-extras --no-header --output-file requirements.txt
python -m piptools compile requirements-dev.in --generate-hashes --allow-unsafe --strip-extras --no-header --output-file requirements-dev.txt
python scripts/check_dependency_locks.py
python -m pip check
python -m pip_audit -r requirements.txt --no-deps --strict --progress-spinner=off
python -m pip_audit -r requirements-dev.txt --no-deps --strict --progress-spinner=off
```

---

## Configuration and privacy

Runtime data is stored outside the source tree under the user profile:

```text
%LOCALAPPDATA%\PythonKni\
```

PythonKni does not require an application account or backend service.

Optional VirusTotal integration reads its key from:

```powershell
$env:VIRUSTOTAL_API_KEY="your_api_key_here"
```

The current integration hashes the selected executable locally and queries VirusTotal by SHA-256; it does not upload the executable itself. The hash is still disclosed to the external provider.

Never commit or publicly share real API keys, WiFi credentials, private logs, scan histories or diagnostic reports.

See [`docs/security.md`](docs/security.md).

---

## Testing and coverage

The current behavior-driven suite contains **578 tests**.

Measured branch coverage on the canonical Windows CI environment:

```text
Repository-wide                 86.4%
All service.py modules          93.2%
```

Key service coverage:

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

The latest service-hardening pass deliberately targeted the weakest real services without changing their production implementation:

```text
Disk Analyzer       81.7% → 95.0%
Duplicate Finder    83.6% → 90.5%
Process Manager     84.0% → 99.3%
WiFi                82.8% → 96.0%
```

The added regressions cover behavior such as unreadable/symlink disk entries, malformed WiFi XML and cancellation, disappearing/reused processes and VirusTotal response paths, duplicate hash/comparison failures, collision grouping and restoration-manifest failure state.

### Coverage ratchets

CI/release protect the achieved baseline rather than lowering thresholds when a regression appears:

```text
repository-wide branch coverage                   >= 86.0%
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
Startup window coverage                            >= 95.0%
Event Viewer window coverage                       >= 98.0%
PDF window coverage                                >= 93.0%
process/config/infrastructure aggregate             >= 88.5%
```

Coverage work remains behavior-driven. A test is useful when it protects a contract, failure mode, safety property or orchestration path—not simply because it turns a line green.

### CI-equivalent validation

```powershell
python scripts/check_dependency_locks.py
python -m pip check
python -m pip_audit -r requirements.txt --no-deps --strict --progress-spinner=off
python -m pip_audit -r requirements-dev.txt --no-deps --strict --progress-spinner=off
python -m compileall .
python -m pytest --cov=pythonkni --cov=tools --cov-branch --cov-report=term-missing --cov-report=xml
python -m coverage report --fail-under=86.0
python -m coverage report --include="pythonkni/*/service.py" --fail-under=93.0
python -m ruff check .
python -m ruff format --check .
pyinstaller --noconfirm --clean PythonKni.spec
dist\PythonKni\PythonKni.exe --smoke-test
```

The workflow also applies the individual ratchets listed above and retains `coverage.xml`, the CycloneDX SBOM and dependency locks with the validated artifact.

---

## Packaging and releases

Local Windows build:

```powershell
pyinstaller --noconfirm --clean PythonKni.spec
dist\PythonKni\PythonKni.exe --smoke-test
```

Tags matching exact `vX.Y.Z` format trigger `.github/workflows/release.yml`. Release validation repeats dependency integrity/audit gates, tests, coverage ratchets, lint/format, PyInstaller build and frozen smoke testing before publishing the ZIP, checksum, SBOM and dependency locks.

Windows executable signing and installer generation are not yet implemented.

---

## Adding a first-party tool

A loader-compatible module under `tools/` must:

1. end in `_tool.py`;
2. expose `Tool`;
3. inherit `tools.base_tool.BaseTool`;
4. override `setup_ui()`;
5. define non-empty `name`, `description` and `category` metadata.

For a real first-party domain, keep the adapter thin and use:

```text
pythonkni/<domain>/models.py
pythonkni/<domain>/service.py
pythonkni/<domain>/window.py
tools/<domain>_tool.py
```

Business/OS logic belongs in `service.py`; Qt orchestration belongs in `window.py`.

---

## Current limitations

- Windows is the only platform currently packaged and enforced by CI.
- The canonical reproducible environment is Windows / CPython 3.10.11; a broader Python/platform matrix is not currently claimed.
- OCR depends on local Tesseract/Poppler installation and document quality.
- DOCX → PDF conversion is intentionally simplified and cannot reproduce every Microsoft Word layout feature.
- Network/system capabilities depend on Windows permissions, topology, firewall policy and available OS utilities.
- Service coverage is now consistently strong, but several presentation modules remain materially lower than the best-covered Qt windows; Converter and Network are the clearest next UI-testing targets.
- Localization infrastructure exists, but not every user-visible string is extracted/translated.
- Windows code signing and installer generation remain release-engineering work.

---

## Roadmap

### Reliability and code quality

- [ ] Continue behavior-driven coverage for lower-coverage **presentation** modules, especially Converter, Network, Archive, System Report, Process Manager and Duplicate Finder.
- [ ] Audit remaining long-running operations for consistent progress/cancellation semantics.
- [ ] Migrate deprecated PyMuPDF `fitz` imports to the current `pymupdf` API where applicable and review avoidable PyInstaller collection warnings.
- [ ] Expand static analysis beyond the current Ruff `F + I` baseline when the repository is ready for a stricter rule set/type-checking gate.

### Product evolution

- [ ] Build a **PC Health / System Intelligence dashboard** that composes existing services instead of duplicating their domain logic.
- [ ] Add a unified operation/history and recovery center for reversible maintenance actions.
- [ ] Evolve Network Explorer toward an authorized local-device inventory with persisted snapshots.
- [ ] Improve DOCX → PDF formatting fidelity.
- [ ] Complete localization of user-visible strings.

### Distribution and documentation

- [ ] Add screenshots/demo media for the main application and representative tools.
- [ ] Add Windows executable signing and installer generation.
- [ ] Define the versioning milestone for moving beyond the current pre-1.0 package version.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — dependency boundaries, infrastructure and coverage ratchets
- [`docs/usage.md`](docs/usage.md) — per-tool operation, cancellation, permissions and troubleshooting
- [`docs/security.md`](docs/security.md) — security controls, sensitive-data flows, destructive operations and supply-chain limits
- [`CHANGELOG.md`](CHANGELOG.md) — development history

---

## Disclaimer

PythonKni is an educational and personal productivity project provided as-is, without warranty.

Keep backups before destructive file/system operations. Use network, process, Event Viewer, startup and WiFi-related features only where you have explicit authorization.

---

## License

MIT
