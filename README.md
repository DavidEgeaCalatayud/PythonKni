# PythonKni

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![PyQt5](https://img.shields.io/badge/UI-PyQt5-41CD52)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)
![Tests](https://img.shields.io/badge/tests-pytest-green)
![Coverage](https://img.shields.io/badge/coverage-ratcheted-green)
![Dependencies](https://img.shields.io/badge/dependencies-SHA--256%20locked-blueviolet)
![Audit](https://img.shields.io/badge/security-pip--audit-success)
![Lint](https://img.shields.io/badge/lint-Ruff%20F%20%2B%20I-purple)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

PythonKni is a **local-first Windows desktop utility suite** built with Python and PyQt5. It combines file/PDF operations, archive handling, duplicate detection, network diagnostics, process inspection, startup management, Windows event analysis, system reporting and safe temporary-file cleanup in one application.

The codebase is organized as a maintainable desktop application rather than a collection of scripts: first-party domains are separated into models, services and PyQt windows, framework-independent shared code lives under `pythonkni/infrastructure`, and the dynamic loader remains compatible through thin `tools/*_tool.py` adapters.

> Use system, network, process and WiFi features only on systems and networks you own or are explicitly authorized to manage.

---

## Toolset

| Tool | Main capabilities |
|---|---|
| **Archive Manager** | Create and extract ZIP/7Z archives with hardened extraction checks and background execution |
| **File Converter** | Convert images, PDF, DOCX, TXT and KML files, including batch TXT/KML workflows |
| **PDF Toolkit** | Merge, split, extract, reorder and read PDFs through `pypdf`; optional OCR for scanned documents |
| **Duplicate Finder** | Detect duplicates through staged hashing and byte verification, then move duplicate copies safely |
| **Network Explorer** | Detect IPv4 interfaces, scan authorized networks, resolve hosts, inspect ARP data and scan port ranges |
| **Process Manager** | Inspect running processes, filter resource usage, terminate selected processes and query optional VirusTotal analysis |
| **Temporary Cleaner** | Preview and clean explicitly authorized temporary/cache targets without following symlinks or Windows reparse points |
| **WiFi Profiles** | Read locally saved WiFi profile information for support and diagnostics |
| **Disk Analyzer** | Analyze a directory, rank large files/folders and export results |
| **Windows Startup Manager** | Inspect startup entries and enable/disable supported registry/folder entries with recoverable changes |
| **Windows Event Viewer** | Read Windows event logs, filter/classify events, inspect details and export snapshots/reports |
| **System Report** | Collect system, disk, network, process and temporary-data diagnostics and export TXT/HTML/PDF reports |
| **Configuration** | Persist application settings such as theme/language configuration outside the repository |

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

At application level:

```text
main.py
  │
  ├─ discovers and validates tools/*_tool.py
  ▼
tools/*_tool.py
  │  thin loader / legacy compatibility adapters
  ▼
pythonkni/<domain>/window.py
  │  PyQt presentation, confirmations and background-task orchestration
  ▼
pythonkni/<domain>/service.py
  │  domain rules, OS integration, parsing, persistence and transformations
  ▼
pythonkni/<domain>/models.py
     framework-independent value objects

services ─────► pythonkni/core + pythonkni/infrastructure
```

`tests/test_architecture_boundaries.py` turns these rules into CI checks. Models and infrastructure stay framework-independent, services do not import presentation code, and operating-system mutations remain in their owning service rather than leaking into Qt windows.

### Process Manager boundary

The Process Manager window does not create or terminate `psutil.Process` objects. `process_manager.service` owns process inspection and termination. Immediately before `terminate()`, the service revalidates process liveness and `create_time`, protecting against PID reuse between confirmation and execution.

### Shared infrastructure

```text
pythonkni/infrastructure/
├─ archives.py   # path validation, extraction limits, staging/publication
└─ paths.py      # application runtime/data paths
```

Legacy paths such as `tools.app_paths` and `tools.zip_7zip_utils` remain compatibility facades while first-party code depends on `pythonkni.infrastructure` directly.

See [`docs/architecture.md`](docs/architecture.md) for the detailed dependency rules.

---

## Project Structure

```text
PythonKni/
├─ .github/
│  ├─ dependabot.yml            Weekly Python + GitHub Actions dependency updates
│  └─ workflows/
│     ├─ ci.yml                 Windows validation, audit, build and smoke test
│     └─ release.yml            Tag-driven validated GitHub Releases
├─ assets/
├─ docs/
│  ├─ architecture.md
│  ├─ security.md
│  └─ usage.md
├─ pythonkni/
│  ├─ core/
│  ├─ infrastructure/
│  └─ <domain>/                 models.py + service.py + window.py
├─ scripts/
│  ├─ check_dependency_locks.py
│  └─ package_windows_bundle.ps1
├─ tests/
├─ tools/                       Thin adapters + shared Qt/runtime helpers
├─ main.py
├─ PythonKni.spec
├─ pyproject.toml
├─ requirements.in              Direct runtime dependency policy
├─ requirements.txt             Exact transitive runtime lock + SHA-256 hashes
├─ requirements-dev.in          Direct development/CI dependency policy
├─ requirements-dev.txt         Exact transitive development lock + SHA-256 hashes
├─ CHANGELOG.md
└─ LICENSE
```

---

## Technical Highlights

### Managed background work

Long-running operations use reusable worker/lifecycle infrastructure and cooperative cancellation. `BaseTool` keeps worker lifetimes tied to windows so an active `QThread` is not destroyed during close.

### Structured UI feedback

Technical failures can now use `tools/ui_feedback.py` to separate the **actionable user summary** from optional **expandable technical details**. The primary dialog avoids dumping raw exceptions into normal UI copy while retaining the exception type/message for troubleshooting.

The first migration tranche covers tool-loader discovery failures, configuration persistence failures, Archive background-operation failures and Process Manager refresh/VirusTotal worker failures. Business warnings, destructive-operation confirmations and other domain-specific dialogs retain their existing behavior. Remaining technical error paths can migrate incrementally without changing service contracts.

### Safer destructive operations

Several workflows implement explicit safety properties:

- archive extraction validates paths, member types, sizes and compression ratios before publication;
- duplicate detection uses staged hashing plus final byte comparison and restoration manifests;
- converter/PDF outputs use staging or transactional publication where applicable;
- startup changes preserve recoverable state;
- CSV exports neutralize spreadsheet-formula injection;
- temporary cleanup rejects symlink/reparse chains and revalidates directory identity around destructive operations;
- process termination revalidates PID identity immediately before mutation.

### Reproducible dependency and supply-chain controls

PythonKni separates dependency **policy** from the exact build graph:

```text
requirements.in      ──pip-tools──► requirements.txt
requirements-dev.in  ──pip-tools──► requirements-dev.txt
       ranges                            exact pins + SHA-256 hashes
```

The committed locks are generated for the canonical Windows / CPython 3.10.11 toolchain. CI and release jobs install them with `pip --require-hashes`, validate their structure, run `pip check`, audit runtime and development dependencies with `pip-audit`, and generate a CycloneDX JSON SBOM. GitHub Actions used by the workflows are pinned by immutable commit SHA, and Dependabot checks Python dependencies and Actions weekly.

These controls improve reproducibility and supply-chain integrity; they do not prove that a legitimately published package is trustworthy, and they do not cover external executables such as Tesseract or Poppler.

### Dynamic plugin contract

`main.py` discovers modules ending in `tools/*_tool.py`. A loader-compatible module must expose a valid `Tool` class inheriting `BaseTool`, implement `setup_ui()` and define non-empty `name`, `description` and `category` metadata.

### Local runtime data

Configuration, history and logs are stored under the user profile rather than in the repository:

```text
%LOCALAPPDATA%\PythonKni\
```

---

## Requirements

### Python

Project metadata requires:

```text
Python >= 3.10
```

The canonical Windows CI and release environment is **CPython 3.10.11**. The minimum was aligned with the supported versions of the current dependency stack rather than preserving a misleading Python 3.8 declaration.

### Runtime dependencies

The runtime stack includes PyQt5, `pypdf`, PyMuPDF, ReportLab, Pillow, python-docx, psutil, requests, py7zr, pytesseract and pdf2image. Direct ranges live in `requirements.in`/`pyproject.toml`; the exact transitive build graph lives in the SHA-256-hashed `requirements.txt`.

OCR additionally requires local Tesseract OCR and Poppler installations.

---

## Installation

Create a Python 3.10 environment and install the exact verified runtime graph:

```powershell
git clone https://github.com/DavidEgeaCalatayud/PythonKni.git
cd PythonKni
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python main.py
```

For development/CI tooling, install the second lock too:

```powershell
python -m pip install --require-hashes -r requirements-dev.txt
```

### Updating dependencies

Do not hand-edit transitive pins or hashes. Change the appropriate `.in` policy file and regenerate both locks from the canonical Windows / CPython 3.10.11 environment:

```powershell
python -m piptools compile requirements.in --generate-hashes --allow-unsafe --strip-extras --no-header --output-file requirements.txt
python -m piptools compile requirements-dev.in --generate-hashes --allow-unsafe --strip-extras --no-header --output-file requirements-dev.txt
python scripts/check_dependency_locks.py
python -m pip check
python -m pip_audit -r requirements.txt --no-deps --strict --progress-spinner=off
python -m pip_audit -r requirements-dev.txt --no-deps --strict --progress-spinner=off
```

Review the resulting diff and the audit result before committing a dependency update.

---

## Configuration and Privacy

PythonKni performs normal file/system operations locally and does not require an application account or backend service.

If VirusTotal integration is used, configure the API key through the environment:

```powershell
$env:VIRUSTOTAL_API_KEY="your_api_key_here"
```

Never commit real API keys, WiFi credentials, personal logs, scan histories or private diagnostic reports. Optional external integrations can transmit data to their provider.

See [`docs/security.md`](docs/security.md).

---

## Testing and Coverage

Core CI-equivalent validation includes:

```powershell
python scripts/check_dependency_locks.py
python -m pip check
python -m pip_audit -r requirements.txt --no-deps --strict --progress-spinner=off
python -m pip_audit -r requirements-dev.txt --no-deps --strict --progress-spinner=off
python -m compileall .
python -m pytest --cov=pythonkni --cov=tools --cov-branch --cov-report=term-missing --cov-report=xml
python -m coverage report --fail-under=84.0
python -m coverage report --include="pythonkni/*/service.py" --fail-under=91.0
python -m coverage report --include="pythonkni/archive/service.py" --fail-under=95.0
python -m coverage report --include="pythonkni/converter/service.py" --fail-under=94.0
python -m coverage report --include="pythonkni/network/service.py" --fail-under=96.0
python -m coverage report --include="pythonkni/pdf/service.py" --fail-under=95.0
python -m coverage report --include="pythonkni/startup/service.py" --fail-under=87.5
python -m coverage report --include="pythonkni/event_viewer/service.py" --fail-under=95.0
python -m coverage report --include="pythonkni/system_report/service.py" --fail-under=97.0
python -m coverage report --include="pythonkni/temp_cleaner/service.py" --fail-under=86.0
python -m coverage report --include="pythonkni/startup/window.py" --fail-under=95.0
python -m coverage report --include="pythonkni/event_viewer/window.py" --fail-under=98.0
python -m coverage report --include="pythonkni/pdf/window.py" --fail-under=93.0
python -m coverage report --include="pythonkni/process_manager/service.py,pythonkni/config/service.py,pythonkni/infrastructure/*.py" --fail-under=84.0
python -m ruff check .
python -m ruff format --check .
```

### Coverage ratchet

The first full measurement established **58.85% repository-wide branch coverage** with 289 tests and **64.7% aggregated service coverage**. Behavior-driven hardening subsequently raised the project to **84.7% repository-wide** and **91.5% across all `pythonkni/*/service.py` modules**. The current suite contains **545 tests** after the first structured-feedback tranche.

Key measured service coverage remains:

```text
Archive service        95.7%
Converter service      94.5%
Network service        96.7%
PDF service            95.3%
Startup service        87.7%
Event Viewer service   95.4%
System Report service  97.2%
Temp Cleaner service   86.4%
```

Priority Qt windows:

```text
Startup window         95.8%
Event Viewer window    98.9%
PDF window             93.4%
```

Additional measured presentation coverage from this tranche:

```text
Archive window         70.2%
Config window          85.0%
Process Manager window 74.6%
UI feedback helper     80.0%
```

CI uses a ratchet rather than lowering thresholds to make regressions pass:

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

Future coverage work should stay behavior-driven, especially in lower-coverage presentation modules, rather than adding assertions solely to increase percentages.

### CI pipeline

Every push and pull request validates the real Windows build path:

```text
CPython 3.10.11
   ↓
SHA-256 hash-locked runtime + development install
   ↓
lock validation + pip check
   ↓
pip-audit runtime + development + CycloneDX SBOM
   ↓
compileall
   ↓
545 pytest tests + branch coverage
   ↓
repository/service/priority coverage ratchets
   ↓
Ruff check + format check
   ↓
PyInstaller Windows build
   ↓
frozen PythonKni.exe --smoke-test
   ↓
ZIP + SHA-256 + coverage.xml + SBOM + dependency locks
```

---

## Packaging and Releases

Build locally with the same locked environment:

```powershell
pyinstaller --noconfirm --clean PythonKni.spec
dist\PythonKni\PythonKni.exe --smoke-test
```

Tags matching exact `vX.Y.Z` format trigger `.github/workflows/release.yml`. The release workflow repeats the dependency integrity/audit gates, tests, coverage ratchets, linting, build and frozen smoke validation before publishing the Windows ZIP, checksum, runtime/development locks and CycloneDX SBOM to the GitHub Release.

Windows executable signing and installer generation remain future release-engineering work.

---

## Adding a Tool

A discovered module is accepted only when:

1. it is under `tools/` and ends in `_tool.py`;
2. it exposes a class named `Tool`;
3. `Tool` inherits from `tools.base_tool.BaseTool`;
4. `Tool` overrides `setup_ui()`;
5. `Tool.name`, `Tool.description` and `Tool.category` are non-empty strings.

A minimal loader-compatible adapter:

```python
from PyQt5.QtWidgets import QLabel

from tools.base_tool import BaseTool


class Tool(BaseTool):
    name = "My New Tool"
    description = "Example PythonKni tool."
    category = "Examples"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setCentralWidget(QLabel("Hello from my new tool"))
```

For a first-party domain, place business/OS logic under `pythonkni/<domain>/service.py`, data objects under `models.py`, presentation under `window.py`, and keep the loader adapter thin.

---

## Current Limitations

- The application is primarily designed, packaged and validated for Windows.
- The canonical reproducible environment is Windows with CPython 3.10.11; broader Python-minor/platform support is not currently claimed by CI.
- OCR depends on external Tesseract/Poppler installations and document quality; those executables are outside the Python lock/SBOM.
- DOCX -> PDF conversion is intentionally simplified and does not preserve every Word feature.
- Network/system capabilities depend on firewall rules, topology and operating-system privileges.
- Coverage is above the original repository/service targets, but several presentation modules remain materially lower than the strongest Qt windows.
- Structured technical feedback is only partially migrated; several windows still use legacy error dialogs.
- GitHub Releases are automated, but Windows executable signing and installer generation are not yet implemented.
- Localization infrastructure exists, but not every user-visible string is extracted/translated.

---

## Roadmap

### Code and reliability

- [ ] Continue behavior-driven coverage work in lower-coverage UI modules, especially Converter, Temp Cleaner, Network and System Report.
- [ ] Continue migrating technical error paths to structured UI feedback, especially Converter, PDF, Network and System Report.
- [ ] Reassess broader Python-minor support only when there is a concrete compatibility requirement and a full CI matrix can enforce it.

### Product quality

- [ ] Improve DOCX -> PDF formatting fidelity.
- [ ] Complete localization of user-visible strings across domains.
- [ ] Audit remaining long-running operations for consistent progress/cancellation behavior.

### Documentation and releases

- [ ] Add screenshots/demo media for the main application and key tools.
- [ ] Add Windows executable signing and installer work.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — dependency rules, domains, infrastructure and coverage ratchet
- [`docs/usage.md`](docs/usage.md) — per-tool operation, permissions, cancellation and troubleshooting
- [`docs/security.md`](docs/security.md) — security controls, sensitive data flows, destructive operations and supply-chain limits
- [`CHANGELOG.md`](CHANGELOG.md) — project change history

---

## Disclaimer

PythonKni is an educational and personal productivity project provided as-is, without warranty.

Always keep backups before running destructive file or system operations. Use network, process, Event Viewer, startup and WiFi-related tools only on systems and networks where you have explicit authorization.

---

## License

MIT