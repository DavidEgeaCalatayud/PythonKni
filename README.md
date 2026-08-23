# PythonKni

![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB)
![PyQt5](https://img.shields.io/badge/UI-PyQt5-41CD52)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)
![Tests](https://img.shields.io/badge/tests-pytest-green)
![Lint](https://img.shields.io/badge/lint-Ruff%20F%20%2B%20I-purple)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

PythonKni is a **local-first Windows desktop utility suite** built with Python and PyQt5. It combines file and PDF operations, archive handling, duplicate detection, network diagnostics, process inspection, startup management, event analysis, system reporting and safe temporary-file cleanup in one application.

The project is both a practical support toolkit and a structured desktop-application codebase: user-facing domains are separated into models, services and PyQt windows, while the dynamic loader is kept compatible through thin `tools/*_tool.py` adapters.

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

PythonKni no longer keeps first-party business logic inside the loader-facing tool modules. Every user-facing domain follows the same dependency direction:

```text
models.py  <-  service.py  <-  window.py  <-  tools/*_tool.py adapter
```

At application level:

```text
main.py
  │
  ├─ discovers and validates tools/*_tool.py
  │
  ▼
tools/*_tool.py
  │  thin loader / legacy compatibility adapters
  ▼
pythonkni/<domain>/window.py
  │  PyQt presentation + background-task orchestration
  ▼
pythonkni/<domain>/service.py
  │  domain rules, OS integration, parsing, persistence, transformations
  ▼
pythonkni/<domain>/models.py
     framework-independent value objects
```

The architecture is **CI-enforced**, not just a convention. `tests/test_architecture_boundaries.py` verifies that every domain has the expected layers and prevents services/models from depending back on PyQt windows or inappropriate `tools` infrastructure.

Long-running services use framework-independent cooperative cancellation from `pythonkni/core/tasks.py`; Qt worker/thread lifecycle concerns stay in the presentation/infrastructure layers.

For the full dependency rules and compatibility model, see [`docs/architecture.md`](docs/architecture.md).

---

## Project Structure

```text
PythonKni/
├─ .github/workflows/
│  └─ ci.yml                    Windows CI: tests, Ruff, PyInstaller, smoke test
├─ assets/                      Runtime UI assets packaged with the application
├─ docs/
│  ├─ architecture.md           Layering and dependency boundaries
│  ├─ security.md               Security and secret-handling notes
│  └─ usage.md                  Runtime/build usage notes
├─ pythonkni/
│  ├─ core/
│  │  └─ tasks.py               Framework-independent cancellation primitives
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
├─ tests/                       Unit, integration, Qt and architecture tests
├─ tools/
│  ├─ *_tool.py                 Thin loader/legacy adapters
│  ├─ base_tool.py              Shared tool-window lifecycle contract
│  ├─ worker.py                 Reusable Qt worker adapter
│  ├─ app_paths.py              User/runtime filesystem paths
│  ├─ csv_utils.py              Spreadsheet-safe CSV helpers
│  └─ shared theme/language/logging infrastructure
├─ main.py                      Application entry point and dynamic discovery
├─ PythonKni.spec               PyInstaller Windows bundle specification
├─ pyproject.toml               Project metadata, pytest and Ruff configuration
├─ requirements.txt             Runtime dependencies
├─ CHANGELOG.md
└─ LICENSE
```

---

## Technical Highlights

### Layered first-party domains

All current user-facing domains use the same `models -> service -> window -> adapter` boundary. Domain logic can therefore be exercised without constructing a `QApplication`, and the legacy dynamic-loader contract remains stable.

### Managed background work

Long-running and blocking operations have progressively moved away from the GUI thread. The project includes reusable worker/lifecycle infrastructure, cooperative cancellation and explicit cleanup for threads/subprocesses where applicable.

### Safer destructive operations

Several workflows include explicit safety guarantees rather than relying on generic recursive filesystem calls:

- archive extraction validates member destinations and traversal boundaries;
- duplicate handling uses staged identity checks and restoration manifests;
- converter outputs are published transactionally;
- startup changes preserve recoverable state;
- CSV exports neutralize spreadsheet-formula injection;
- temporary cleanup only accepts authorized roots, uses `lstat`, rejects symlink/reparse path chains and revalidates directory identity around destructive operations.

### Dynamic plugin contract

`main.py` discovers modules ending in `tools/*_tool.py`. A loader-compatible module must expose a valid `Tool` class inheriting `BaseTool`, implement `setup_ui()` and define non-empty `name`, `description` and `category` metadata.

First-party tools additionally use the layered `pythonkni/<domain>/` structure; the `tools/*_tool.py` files are retained as adapters so loader behavior and legacy imports remain compatible.

### Local runtime data

Configuration, history and logs are stored under the user profile rather than in the repository:

```text
%LOCALAPPDATA%\PythonKni\
```

### Windows packaging validated in CI

The PyInstaller specification is built on `windows-latest`. CI then launches the frozen executable with `--smoke-test`, which validates dynamic tool discovery and required packaged assets without entering the normal Qt event loop.

---

## Requirements

### Python

Project metadata currently declares:

```text
Python >= 3.8
```

The GitHub Actions workflow currently validates the project with **Python 3.10 on Windows**. A broader Python-version support matrix is not yet part of CI, so the declared lower bound should not be interpreted as equivalent CI coverage for every supported minor version.

### Python dependencies

Runtime dependencies are defined in `requirements.txt` and `pyproject.toml`, including:

```text
PyQt5
PyPDF2
PyMuPDF
ReportLab
Pillow
python-docx
psutil
requests
py7zr
pytesseract
pdf2image
```

Install them with:

```bash
pip install -r requirements.txt
```

### Optional OCR dependencies

OCR-based PDF extraction additionally requires system installations of:

- **Tesseract OCR**
- **Poppler**

They must be available to the application through the expected system paths/`PATH` configuration.

---

## Installation and Development

Clone the repository:

```bash
git clone https://github.com/DavidEgeaCalatayud/PythonKni.git
cd PythonKni
```

Create and activate a Windows virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install runtime dependencies:

```powershell
pip install -r requirements.txt
```

For development/CI-equivalent tooling:

```powershell
pip install pytest pytest-qt ruff pyinstaller
```

Run the application:

```powershell
python main.py
```

---

## Configuration and Privacy

PythonKni is designed to perform its normal file/system operations locally. No application account or backend service is required.

Runtime configuration and local data are kept outside the repository under `%LOCALAPPDATA%\PythonKni\`.

If VirusTotal integration is used, configure the API key through the environment rather than source code:

```powershell
$env:VIRUSTOTAL_API_KEY="your_api_key_here"
```

Never commit real API keys, personal logs, scan histories or private diagnostic reports. Optional external integrations can transmit data to their provider; review the relevant workflow before using sensitive material.

See [`docs/security.md`](docs/security.md) for the repository's security notes.

---

## Testing and Quality Gates

Run the same core validation commands used by CI:

```powershell
python -m compileall .
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Ruff currently enforces:

```toml
select = ["F", "I"]
```

That means the repository now checks full **Pyflakes** diagnostics plus **import ordering**, rather than only the previous minimal set of critical syntax/name errors.

The test suite covers substantially more than isolated service helpers. Current coverage includes, among other areas:

- architecture boundaries and plugin contracts;
- configuration/runtime persistence;
- background worker lifecycle and cancellation;
- archive creation/extraction and security regressions;
- converter service behavior and transactional outputs;
- duplicate detection/movement behavior;
- network discovery, validation, port scanning and cancellation;
- process-manager protection and worker lifecycle;
- PDF page operations;
- startup-manager transactions;
- Event Viewer services;
- Disk Analyzer/System Report Qt behavior;
- Temp Cleaner symlink, junction/reparse and path-race regressions;
- WiFi command behavior;
- packaged-application discovery smoke tests.

### CI pipeline

Every `push` and `pull_request` runs on Windows and executes:

```text
compileall
   ↓
pytest
   ↓
Ruff check (F + I)
   ↓
Ruff format --check
   ↓
PyInstaller build
   ↓
frozen PythonKni.exe --smoke-test
```

A green source-level test suite is therefore not enough on its own: CI also verifies that the Windows bundle can actually be produced and that its dynamic tool discovery still works after freezing.

---

## Packaging

Build the Windows bundle with the committed specification:

```powershell
pyinstaller --noconfirm --clean PythonKni.spec
```

The executable is expected at:

```text
dist\PythonKni\PythonKni.exe
```

You can run the non-interactive packaging validation directly with:

```powershell
dist\PythonKni\PythonKni.exe --smoke-test
```

The normal CI currently **builds and validates** this bundle but does not publish it as a release artifact. Automated tagged releases/signing remain future release-engineering work.

Generated `build/` and `dist/` directories should not be committed.

---

## Adding a Tool

The loader contract is deliberately small and is validated by tests. A discovered module is accepted only when:

1. it is under `tools/` and ends in `_tool.py`;
2. it exposes a class named `Tool`;
3. `Tool` inherits from `tools.base_tool.BaseTool`;
4. `Tool` overrides `setup_ui()`;
5. `Tool.name`, `Tool.description` and `Tool.category` are non-empty strings.

A minimal loader-compatible tool looks like this:

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

For a **first-party PythonKni domain**, follow the repository architecture rather than placing business logic in that adapter: implement the domain under `pythonkni/<domain>/models.py`, `service.py` and `window.py`, and keep the `tools/*_tool.py` module thin.

Validate the contract with:

```powershell
python -m pytest tests/test_tool_contract.py tests/test_architecture_boundaries.py
```

---

## Security Model

PythonKni interacts with local files, archives, processes, temporary directories, Windows startup configuration, event logs, network devices and saved WiFi information. Those surfaces are intentionally subject to operating-system permissions and application-level validation.

The application does not attempt to bypass authentication, encryption, DRM, access controls or operating-system authorization boundaries.

Some operations are inherently destructive or privileged. Back up important data before cleanup, archive extraction, PDF modification, duplicate movement or startup changes, and use network/process tools only where you have authorization.

---

## Current Limitations

- The application is primarily designed and tested for **Windows** workflows.
- CI currently validates one Python runtime (**3.10**) rather than a full version matrix.
- Some capabilities depend on optional external executables such as Tesseract OCR and Poppler.
- OCR accuracy depends on document quality, language data and local OCR configuration.
- DOCX -> PDF conversion is intentionally simplified and does not preserve all Word layout, images, tables, headers/footers or advanced formatting.
- Network discovery results depend on firewall rules, host behavior, permissions and local topology.
- Windows Event Viewer, process, startup and WiFi operations can be limited by the current user's privileges.
- The PDF stack still includes the deprecated `PyPDF2` package and should migrate to `pypdf`.
- Dependency installation currently uses version lower bounds rather than a fully reproducible lock/constraints workflow.
- CI builds the Windows executable but does not yet publish signed/tagged releases.
- Localization infrastructure exists, but user-visible strings are not yet comprehensively extracted/translated across every domain.

---

## Roadmap

The previous roadmap contained several items that are now complete: layered service/UI separation, the plugin contract, substantial archive tests, managed background work/cancellation, progress feedback and CI executable builds are no longer listed as future work.

The active roadmap is intentionally limited to work that remains open:

### Code and reliability

- [ ] Migrate the PDF backend from `PyPDF2` to `pypdf`.
- [ ] Expand PDF regression coverage, especially cancellation, rollback and encrypted/error cases.
- [ ] Decide and enforce the Python-version support contract in CI.
- [ ] Add reproducible dependency constraints/locking and dependency-security checks.
- [ ] Continue improving structured UI error reporting where operations still return raw exception text.

### Product quality

- [ ] Improve DOCX -> PDF formatting fidelity.
- [ ] Complete localization of user-visible strings across domains.
- [ ] Audit remaining long-running operations for consistent progress/cancellation behavior.

### Documentation and releases

- [ ] Expand per-tool instructions in `docs/usage.md`.
- [ ] Expand `docs/security.md` with guarantees and risks for destructive/sensitive tools.
- [ ] Update `CHANGELOG.md` for the recent architecture, safety and CI work.
- [ ] Add screenshots/demo media for the main application and key tools.
- [ ] Add tagged GitHub release automation and publish validated build artifacts.
- [ ] Add Windows executable signing/installer work when a release process is established.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — dependency rules, domains and compatibility adapters
- [`docs/usage.md`](docs/usage.md) — current execution/build notes
- [`docs/security.md`](docs/security.md) — authorization and secret-handling notes
- [`CHANGELOG.md`](CHANGELOG.md) — project change history

---

## Disclaimer

PythonKni is an educational and personal productivity project provided as-is, without warranty.

Always keep backups before running destructive file or system operations. Use network, process, Event Viewer, startup and WiFi-related tools only on systems and networks where you have explicit authorization.

---

## License

MIT
