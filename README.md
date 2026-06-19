# PythonKni

![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB)
![PyQt5](https://img.shields.io/badge/UI-PyQt5-41CD52)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Build](https://img.shields.io/badge/build-PyInstaller-orange)
![Tests](https://img.shields.io/badge/tests-pytest-green)
![Lint](https://img.shields.io/badge/lint-ruff-purple)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

PythonKni is a desktop utility suite developed in **Python** and **PyQt5**. It brings together file conversion, PDF processing, archive management, duplicate detection, network diagnostics, process inspection, temporary-file cleanup and local WiFi profile listing in a single graphical application.

The project is designed as a practical “Swiss army knife” for local maintenance tasks, technical support workflows and everyday file operations on Windows.

> Use the tools only on your own systems or on systems where you have explicit authorization.

---

## Features

### Archive Management

- Create ZIP files.
- Extract ZIP files.
- Create 7Z files.
- Extract 7Z files.

### File Conversion

- Convert images to PDF.
- Convert PDF pages to images.
- Convert TXT files to DOCX.
- Convert DOCX files to TXT.
- Convert DOCX files to PDF.
- Convert TXT coordinate files to KML.
- Convert KML files to TXT.
- Batch conversion support for TXT/KML folders.

### PDF Toolkit

- Merge multiple PDF files.
- Split PDF files into individual pages.
- Split PDF files by custom page ranges.
- Extract selected pages into a new PDF.
- Reorder PDF pages using a graphical interface.
- Extract text from PDF files.
- Export extracted text as Markdown.
- Detect probably scanned PDFs based on empty text pages.
- Optional OCR support for scanned documents.

### Duplicate File Finder

- Scan folders recursively.
- Detect duplicate files using file hashes.
- Display duplicate groups.
- Move duplicate files to a dedicated `DuplicadosEncontrados` folder while keeping one original.

### Network Tools

- Scan the local network.
- Detect reachable devices in the current subnet.
- Resolve hostnames when available.
- Attempt MAC address lookup through ARP.
- Scan a custom port range for a selected IP address or domain.
- Store scan history.
- Import and export scan history as TXT, JSON or CSV.

### Process Management

- Inspect local running processes.
- Support maintenance-oriented process workflows through the graphical interface.

### Temporary File Cleanup

- Clean temporary files from local system/user folders.
- Support safe maintenance operations from the desktop interface.

### WiFi Profile Tools

- List locally saved WiFi profiles.
- Assist with local network support and diagnostics.

### Configuration and Logs

- Stores user-specific configuration outside the repository.
- Stores logs and runtime data in the user profile.
- Supports application-level configuration through local files and environment variables.

---

## Technical Highlights

- Desktop application built with PyQt5.
- Dynamic tool loader based on `tools/*_tool.py` modules.
- Modular tool-oriented structure.
- Background threads for long-running operations such as duplicate scans and network scans.
- Local-only execution for file, network and maintenance tasks.
- User data stored outside the repository in `%LOCALAPPDATA%`.
- PyInstaller specification included for reproducible Windows builds.
- CI workflow with compile checks, tests, Ruff linting and Ruff format validation.
- Testable service logic separated from part of the UI logic.
- External OCR support through Tesseract OCR and Poppler.

---

## Why this project exists

Many maintenance tasks require jumping between different applications: archive tools, PDF utilities, image converters, network scanners, process managers and cleanup scripts.

PythonKni centralizes these common operations into a single desktop interface. The goal is not to replace specialized professional tools, but to provide a practical, extensible and local-first toolkit for technical support, file handling and system maintenance.

The project also serves as a technical exercise in:

- PyQt5 desktop application development;
- modular application architecture;
- file processing;
- PDF manipulation;
- local system automation;
- network diagnostics;
- packaging Python applications for Windows;
- safe handling of local configuration, logs and API keys.

---

## Architecture Overview

```text
main.py
  │
  │ loads tools dynamically
  ▼
tools/*_tool.py
  │
  ├── archive_tool.py
  ├── converter_tool.py
  ├── duplicate_tool.py
  ├── network_tool.py
  ├── pdf_merge_tool.py
  ├── process_manager_tool.py
  ├── temp_cleaner_tool.py
  ├── wifi_tool.py
  └── config_window_tool.py
        │
        ▼
PyQt5 windows and widgets
        │
        ▼
Local file system, network, process and PDF operations
```

The current design uses a dynamic loader: each module ending in `_tool.py` exposes a `Tool` class with a visible name and its own PyQt interface.

This makes it easy to add new tools without modifying the main application menu.

---

## Project Structure

```text
.github/workflows/       CI workflow for validation
assets/                  Static UI assets
docs/                    Additional architecture, usage and security documentation
scripts/                 Helper scripts
tests/                   Automated tests
tools/                   Application tools and shared services
.env.example             Example environment configuration
CHANGELOG.md             Project changelog
LICENSE                  MIT license
PythonKni.spec           PyInstaller build specification
main.py                  Application entry point
pyproject.toml           Project metadata and tool configuration
requirements.txt         Runtime dependencies
```

---

## Main Tools

| Tool | Description |
|---|---|
| Archive Manager | Create and extract ZIP/7Z files |
| File Converter | Convert images, PDF, DOCX, TXT and KML files |
| PDF Toolkit | Merge, split, reorder, extract pages and extract text from PDFs |
| Duplicate Finder | Detect duplicate files and move repeated copies |
| Network Explorer | Scan local network devices and port ranges |
| Process Manager | Inspect and manage local processes |
| Temporary Cleaner | Clean temporary files |
| WiFi Tool | List saved local WiFi profiles |
| Configuration | Manage local application settings |

---

## Requirements

### Python

PythonKni requires:

```text
Python 3.8+
```

Recommended version:

```text
Python 3.10+
```

### Python dependencies

Main dependencies include:

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

---

## Installation

Clone the repository:

```bash
git clone https://github.com/DavidEgeaCalatayud/PythonKni.git
cd PythonKni
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate the virtual environment on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python main.py
```

---

## Configuration

PythonKni stores configuration, history and logs outside the repository in a user-specific local folder:

```text
%LOCALAPPDATA%\PythonKni\
```

This avoids committing personal configuration, scan history, logs or runtime data to the repository.

---

## VirusTotal Configuration

If VirusTotal analysis is enabled in your local setup, configure the API key through an environment variable.

PowerShell example:

```powershell
$env:VIRUSTOTAL_API_KEY="your_api_key_here"
```

Never commit real API keys to the repository.

Do not upload:

```text
.env
.env.local
real API keys
personal logs
scan history
private reports
```

If a key was ever committed accidentally:

1. Revoke it from the provider dashboard.
2. Generate a new key.
3. Configure the new key through an environment variable.
4. Remove the old key from Git history if necessary.

---

## OCR Setup

Some PDF text extraction features can use OCR when the PDF is scanned or does not contain selectable text.

OCR requires external system dependencies in addition to Python packages:

- Tesseract OCR;
- Poppler.

Both executables must be installed and available in the system `PATH`.

If OCR is not available, PythonKni can still perform normal PDF text extraction, but scanned documents may return little or no text.

---

## Build

PythonKni includes a PyInstaller specification file:

```bash
pyinstaller PythonKni.spec
```

The `PythonKni.spec` file is versioned to document the build process.

Generated build artifacts should not be committed:

```text
build/
dist/
*.spec temporary changes
```

The final executable will normally be generated under:

```text
dist/
```

---

## Development

Create and activate a virtual environment:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install runtime dependencies:

```bash
pip install -r requirements.txt
```

Install development dependencies:

```bash
pip install pytest ruff
```

Run the application:

```bash
python main.py
```

---

## Quality Checks

Compile all Python files:

```bash
python -m compileall .
```

Run tests:

```bash
python -m pytest
```

Run Ruff linting:

```bash
python -m ruff check .
```

Check formatting:

```bash
python -m ruff format --check .
```

The CI workflow runs these checks on each `push` and `pull_request`.

---

## Testing

The test suite focuses on logic that can be validated independently from the graphical interface.

Covered areas include:

- configuration handling;
- file conversion service logic;
- duplicate detection;
- network input validation;
- PDF page parsing;
- temporary-file cleanup behavior.

Run all tests with:

```bash
python -m pytest
```

---

## Adding a New Tool

PythonKni uses a dynamic tool-loading approach.

To add a new tool:

1. Create a new file inside `tools/`.
2. Name it using the `_tool.py` suffix.
3. Expose a class named `Tool`.
4. Add a readable `name` attribute.
5. Implement the PyQt window or widget logic.

Example:

```python
from PyQt5.QtWidgets import QMainWindow, QLabel


class Tool(QMainWindow):
    name = "My New Tool"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setCentralWidget(QLabel("Hello from my new tool"))
```

After restarting the application, the tool will be loaded into the main menu automatically.

---

## Security Notes

PythonKni includes tools that interact with:

- local files;
- compressed archives;
- PDF documents;
- running processes;
- temporary folders;
- local network devices;
- port ranges;
- saved WiFi profiles;
- optional external analysis services.

Use these features only on systems you own or have permission to manage.

This project does not attempt to bypass operating system permissions, authentication, encryption, DRM, paywalls or access controls.

---

## Privacy

PythonKni is designed as a local desktop application.

By default:

- files are processed locally;
- logs are stored locally;
- configuration is stored locally;
- scan history is stored locally;
- no user account is required;
- no backend server is required.

If optional integrations such as VirusTotal are used, the selected files or hashes may be sent to the external provider depending on the implementation. Review the integration before using it with private or sensitive files.

---

## Limitations

- The application is currently focused on Windows workflows.
- Some features depend on external executables such as Tesseract OCR and Poppler.
- OCR quality depends on image quality, language configuration and installed OCR data.
- DOCX to PDF conversion is simplified and may not preserve complex formatting.
- Network scanning depends on local firewall rules, permissions and network configuration.
- Process and WiFi tools may require elevated permissions depending on the system.
- The current architecture still mixes some UI and business logic in tool modules.
- Future refactoring could move the core logic into a dedicated `src/pythonkni/` package.

---

## Roadmap

Possible future improvements:

- [ ] Move source code to `src/pythonkni/`.
- [ ] Split each tool into service logic and UI windows.
- [ ] Add more tests for PDF operations.
- [ ] Add more tests for archive operations.
- [ ] Add screenshots of each tool.
- [ ] Add a demo GIF of the main menu.
- [ ] Add release builds through GitHub Actions.
- [ ] Publish signed Windows executable releases.
- [ ] Improve DOCX to PDF conversion fidelity.
- [ ] Add progress bars for long-running operations.
- [ ] Add cancellation support to more tools.
- [ ] Improve error reporting in the UI.
- [ ] Add multilingual UI support.
- [ ] Add a plugin-style tool registry.
- [ ] Add user documentation for each tool in `docs/usage.md`.

---

## Suggested Screenshots

Recommended screenshots for the repository:

```text
docs/assets/main-menu.png
docs/assets/pdf-toolkit.png
docs/assets/network-scanner.png
docs/assets/converter-tool.png
docs/assets/duplicate-finder.png
```

You can then include them in this README:

```md
![PythonKni main menu](docs/assets/main-menu.png)
```

---

## Disclaimer

PythonKni is an educational and personal productivity project.

It is provided as-is, without warranty. Always make backups before running file operations, cleanup tools, archive extraction, PDF modification or duplicate-file movement on important data.

Use network, process and WiFi-related tools only on systems and networks where you have explicit authorization.

---

## License

MIT
