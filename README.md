# PythonKni

![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB)
![PyQt5](https://img.shields.io/badge/UI-PyQt5-41CD52)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)
![Tests](https://img.shields.io/badge/tests-pytest-green)
![Coverage](https://img.shields.io/badge/coverage-ratcheted-green)
![Lint](https://img.shields.io/badge/lint-Ruff%20F%20%2B%20I-purple)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

PythonKni is a **local-first Windows desktop utility suite** built with Python and PyQt5. It combines file and PDF operations, archive handling, duplicate detection, network diagnostics, process inspection, startup management, event analysis, system reporting and safe temporary-file cleanup in one application.

The codebase is organized as a maintainable desktop application rather than a collection of scripts: user-facing domains are separated into models, services and PyQt windows, framework-independent shared code lives under `pythonkni/infrastructure`, and the dynamic loader remains compatible through thin `tools/*_tool.py` adapters.

> Use system, network, process and WiFi features only on systems and networks you own or are explicitly authorized to manage.

---

## Toolset

| Tool | Main capabilities |
|---|---|
| **Archive Manager** | Create and extract ZIP/7Z archives with hardened extraction checks and background execution |
| **File Converter** | Convert images, PDF, DOCX, TXT and KML files, including batch TXT/KML workflows |
| **PDF Toolkit** | Merge, split, extract, reorder and read PDFs; optional OCR for scanned documents |
| **Duplicate Finder** | Detect duplicates through staged hashing and byte verification, then move duplicate copies safely |
| **Network Explorer** | Detect IPv4 interfaces, scan authorized networks, resolve hosts, inspect ARP data and scan port ranges |
| **Process Manager** | Inspect running processes, filter resource usage, terminate selected processes and query optional VirusTotal analysis |
| **Temporary Cleaner** | Preview and clean explicitly authorized temporary/cache targets without following symlinks or Windows reparse points |
| **WiFi Profiles** | Read locally saved WiFi profile information for support and diagnostics |
| **Disk Analyzer** | Analyze a directory, rank large files/folders and export results |
| **Windows Startup Manager** | Inspect startup entries and enable/disable supported registry/folder entries with recoverable changes |
| **Windows Event Viewer** | Read Windows event logs, filter and classify events, inspect details and export snapshots/reports |
| **System Report** | Collect system, disk, network, process and temporary-data diagnostics and export TXT/HTML/PDF reports |
| **Configuration** | Persist application settings such as theme/language configuration outside the repository |

---

## Architecture

The main dependency direction is:

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

The architecture is **CI-enforced**, not just a convention. `tests/test_architecture_boundaries.py` verifies domain layers, framework independence of models/infrastructure, the Archive infrastructure boundary and the Process Manager rule that OS process integration must not leak back into its window.

### Process Manager boundary

The Process Manager UI no longer creates or terminates `psutil.Process` objects. `process_manager.service` owns process inspection and termination. The window obtains a validated `ProcessDetails` snapshot, asks the user for confirmation and delegates the mutation back to the service.

Immediately before `terminate()`, the service revalidates process liveness and `create_time`, preventing PID reuse between confirmation and execution from targeting a different process.

### Shared infrastructure

Framework-independent technical code lives under:

```text
pythonkni/infrastructure/
├─ archives.py   # path validation, extraction limits, safe staging/publication
└─ paths.py      # application runtime/data paths
```

Legacy paths such as `tools.app_paths` and `tools.zip_7zip_utils` remain as compatibility facades so existing imports and regression monkeypatches continue to work while first-party code depends on `pythonkni.infrastructure` directly.

### Configuration boundary

Configuration persistence and runtime UI application are separate:

```text
config/models.py
      ↑
config/service.py      # normalization + atomic persistence; no PyQt/tools
      ↑
config/runtime.py      # ThemeManager / LanguageManager integration
      ↑
config/window.py
```

See [`docs/architecture.md`](docs/architecture.md) for the detailed rules.

---

## Project Structure

```text
PythonKni/
├─ .github/workflows/
│  ├─ ci.yml                    Windows CI: tests, coverage, Ruff, build, smoke test
│  └─ release.yml               Tag-driven validated GitHub Releases
├─ assets/
├─ docs/
│  ├─ architecture.md
│  ├─ security.md
│  └─ usage.md
├─ pythonkni/
│  ├─ core/
│  │  └─ tasks.py
│  ├─ infrastructure/
│  │  ├─ archives.py
│  │  └─ paths.py
│  ├─ archive/
│  ├─ config/
│  ├─ converter/
│  ├─ disk_analyzer/
│  ├─ duplicate/
│  ├─ event_viewer/
│  ├─ network/
│  ├─ pdf/
│  ├─ process_manager/
│  ├─ startup/
│  ├─ system_report/
│  ├─ temp_cleaner/
│  └─ wifi/
│     └─ each domain: models.py, service.py, window.py
├─ tests/
├─ tools/
│  ├─ *_tool.py                 Thin loader/legacy adapters
│  ├─ base_tool.py
│  ├─ worker.py
│  ├─ app_paths.py              Compatibility alias to infrastructure.paths
│  ├─ zip_7zip_utils.py         Legacy archive/UI facade
│  └─ shared Qt/runtime helpers
├─ main.py
├─ PythonKni.spec
├─ pyproject.toml
├─ requirements.txt
├─ CHANGELOG.md
└─ LICENSE
```

---

## Technical Highlights

### Managed background work

Long-running operations use reusable worker/lifecycle infrastructure and cooperative cancellation. `BaseTool` keeps worker lifetimes tied to windows so a running `QThread` is not destroyed during close.

### Safer destructive operations

Several workflows implement explicit safety properties:

- archive extraction validates destination paths, member types, sizes and compression ratios before publication;
- duplicate detection uses staged hashing plus final byte comparison and restoration manifests;
- converter/PDF outputs use staging or transactional publication where applicable;
- startup changes preserve recoverable state;
- CSV exports neutralize spreadsheet-formula injection;
- temporary cleanup rejects symlink/reparse chains and revalidates directory identity around destructive operations;
- process termination revalidates PID identity immediately before mutation.

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

Project metadata declares:

```text
Python >= 3.8
```

The main Windows validation job runs on **Python 3.10**. CI also includes a targeted **Python 3.8 + py7zr 0.22.0** Archive compatibility job. This targeted job protects the declared legacy archive-loading contract but is not yet a complete minor-version matrix for every feature.

### Runtime dependencies

Runtime dependencies are defined in `requirements.txt` and `pyproject.toml`, including PyQt5, PyPDF2, PyMuPDF, ReportLab, Pillow, python-docx, psutil, requests, py7zr, pytesseract and pdf2image.

```powershell
pip install -r requirements.txt
```

OCR additionally requires local Tesseract OCR and Poppler installations.

---

## Installation and Development

```powershell
git clone https://github.com/DavidEgeaCalatayud/PythonKni.git
cd PythonKni
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pytest pytest-qt "pytest-cov>=5.0,<6.0" ruff pyinstaller
python main.py
```

---

## Configuration and Privacy

PythonKni performs its normal file/system operations locally and does not require an application account or backend service.

If VirusTotal integration is used, configure the API key through the environment:

```powershell
$env:VIRUSTOTAL_API_KEY="your_api_key_here"
```

Never commit real API keys, personal logs, scan histories or private diagnostic reports. Optional external integrations can transmit data to their provider.

See [`docs/security.md`](docs/security.md).

---

## Testing and Coverage

Run the CI-equivalent quality checks with:

```powershell
python -m compileall .
python -m pytest --cov=pythonkni --cov=tools --cov-branch --cov-report=term-missing --cov-report=xml
python -m coverage report --fail-under=58
python -m coverage report --include="pythonkni/*/service.py" --fail-under=64
python -m coverage report --include="pythonkni/process_manager/service.py,pythonkni/config/service.py,pythonkni/infrastructure/*.py" --fail-under=80
python -m ruff check .
python -m ruff format --check .
```

### Coverage ratchet

The first repository-wide branch-coverage measurement established a real baseline of **58.85%** with **289/289 tests passing**. The service layer is currently around the mid-60% range because several Windows-heavy domains still contain historical untested branches.

CI therefore uses a **ratchet**, not an artificial green badge:

```text
repository-wide branch coverage                   >= 58%
all pythonkni/*/service.py coverage                >= 64%
refactored process/config/infrastructure coverage  >= 80%
```

The long-term targets are **80% repository-wide** and **85% for services**. Ratchet floors should only be increased as tests are added; they should not be lowered to make a regression pass.

Ruff currently enforces full Pyflakes diagnostics plus import ordering:

```toml
select = ["F", "I"]
```

The suite covers architecture boundaries, configuration persistence/runtime behavior, worker lifecycle/cancellation, archive security, converter transactions, duplicate handling, network validation/scanning, process protection and PID identity, PDF regressions, startup transactions, Event Viewer behavior, Temp Cleaner safety, WiFi behavior and packaged application discovery.

### CI pipeline

Every push and pull request runs:

```text
compileall
   ↓
289+ pytest tests + branch coverage
   ↓
coverage ratchets
   ↓
Ruff check + format check
   ↓
PyInstaller Windows build
   ↓
frozen PythonKni.exe --smoke-test
   ↓
ZIP + SHA-256 + coverage.xml artifact
```

The dedicated Python 3.8 Archive compatibility job runs alongside the main validation job.

---

## Packaging and Releases

Build locally with:

```powershell
pyinstaller --noconfirm --clean PythonKni.spec
dist\PythonKni\PythonKni.exe --smoke-test
```

Successful CI runs retain the validated Windows ZIP, SHA-256 checksum and coverage XML as workflow artifacts.

Tags matching exact `vX.Y.Z` format trigger `.github/workflows/release.yml`. The release workflow repeats tests, coverage ratchets, linting, build and frozen smoke validation before publishing the ZIP and checksum to a GitHub Release.

Windows executable signing and installer generation remain future release-engineering work.

---

## Adding a Tool

A discovered module is accepted only when:

1. it is under `tools/` and ends in `_tool.py`;
2. it exposes a class named `Tool`;
3. `Tool` inherits from `tools.base_tool.BaseTool`;
4. `Tool` overrides `setup_ui()`;
5. `Tool.name`, `Tool.description` and `Tool.category` are non-empty strings.

For a first-party domain, put business/OS logic under `pythonkni/<domain>/service.py`, data objects under `models.py`, presentation under `window.py`, and keep the loader adapter thin. Cross-domain framework-independent technical code belongs under `pythonkni/infrastructure`.

```powershell
python -m pytest tests/test_tool_contract.py tests/test_architecture_boundaries.py
```

---

## Current Limitations

- The application is primarily designed and tested for Windows workflows.
- Full CI validation centers on Python 3.10, with targeted Python 3.8 Archive compatibility rather than a complete version matrix.
- OCR depends on external Tesseract/Poppler installations and document quality.
- DOCX -> PDF conversion is intentionally simplified and does not preserve every Word feature.
- Network/system capabilities depend on firewall rules, topology and operating-system privileges.
- The PDF stack still uses deprecated `PyPDF2` and should migrate to `pypdf`.
- Dependency installation uses version lower bounds rather than a fully reproducible lock/constraints workflow.
- Repository-wide branch coverage is still below the long-term 80% target, especially in Windows-heavy UI/OS paths.
- GitHub Releases are automated, but executable signing and installer generation are not yet implemented.
- Localization infrastructure exists, but not every user-visible string is extracted/translated.

---

## Roadmap

### Code and reliability

- [ ] Raise the coverage ratchet progressively toward 80% overall / 85% services.
- [ ] Migrate the PDF backend from `PyPDF2` to `pypdf`.
- [ ] Expand tests in low-coverage Windows-heavy services, especially Startup, System Report and Event Viewer.
- [ ] Decide and enforce the full Python-version support matrix in CI.
- [ ] Add reproducible dependency constraints/locking and dependency-security checks.
- [ ] Continue improving structured UI error reporting.

### Product quality

- [ ] Improve DOCX -> PDF formatting fidelity.
- [ ] Complete localization of user-visible strings across domains.
- [ ] Audit remaining long-running operations for consistent progress/cancellation behavior.

### Documentation and releases

- [ ] Add screenshots/demo media for the main application and key tools.
- [ ] Add Windows executable signing and installer work.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — dependency rules, domains, infrastructure, compatibility and coverage ratchet
- [`docs/usage.md`](docs/usage.md) — per-tool operation, permissions, cancellation and troubleshooting
- [`docs/security.md`](docs/security.md) — security controls, sensitive data flows, destructive operations and limits
- [`CHANGELOG.md`](CHANGELOG.md) — project change history

---

## Disclaimer

PythonKni is an educational and personal productivity project provided as-is, without warranty.

Always keep backups before running destructive file or system operations. Use network, process, Event Viewer, startup and WiFi-related tools only on systems and networks where you have explicit authorization.

---

## License

MIT
