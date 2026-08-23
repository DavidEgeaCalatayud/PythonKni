# Usage

This guide describes how to run PythonKni and how the current first-party tools behave from a user's perspective. PythonKni is primarily designed and validated for Windows.

For architecture details, see [`architecture.md`](architecture.md). For authorization, privacy and destructive-operation notes, see [`security.md`](security.md).

## Run PythonKni

### Development mode

Create and activate a virtual environment, install the runtime dependencies, then start the application:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

The main window discovers valid `tools/*_tool.py` adapters dynamically and adds their `Tool` classes to the menu.

### Packaged application

Build the Windows bundle with the committed PyInstaller specification:

```powershell
pyinstaller --noconfirm --clean PythonKni.spec
```

The executable is expected at:

```text
dist\PythonKni\PythonKni.exe
```

The non-interactive packaging smoke test used by CI can be run with:

```powershell
dist\PythonKni\PythonKni.exe --smoke-test
```

That mode validates frozen tool discovery and required packaged assets without opening the normal Qt interface.

## Runtime data

PythonKni keeps user-specific runtime files outside the repository. On a normal Windows installation the base directory is:

```text
%LOCALAPPDATA%\PythonKni\
```

Important locations include:

```text
%LOCALAPPDATA%\PythonKni\config.json
%LOCALAPPDATA%\PythonKni\data\
%LOCALAPPDATA%\PythonKni\logs\
```

If `LOCALAPPDATA` is unavailable, PythonKni falls back to `APPDATA` and finally to a user-home directory fallback.

## Optional system dependencies

Some features require software outside the Python environment:

- **Tesseract OCR** for OCR-based PDF text extraction.
- **Poppler** for PDF/image workflows that depend on `pdf2image`.
- Standard Windows utilities such as `netsh`, `ping`, `arp` and Windows registry/event-log facilities for the corresponding system tools.

Features that depend on operating-system resources can also be limited by the current user's permissions.

---

# Tool guide

## Archive Manager

**Menu name:** `Gestor de Archivos (ZIP/7Z)`

Available actions:

- **Extract ZIP** — select a `.zip`; output is written to a sibling directory named `<archive>_extracted`.
- **Create ZIP** — select one or more files, then choose the destination archive.
- **Extract 7Z** — select a `.7z`; output uses the same `<archive>_extracted` convention.
- **Create 7Z** — select one or more files, then choose the destination archive.

Archive creation and extraction run in a background worker, expose progress and can be cancelled. New archives are created through a temporary output and published only after successful completion.

Extraction is deliberately stricter than a generic archive utility. The destination directory must not already exist, unsafe archive members are rejected, and extraction is staged before the completed directory is published. See `security.md` for the enforced archive limits and path rules.

## File Converter

**Menu name:** `Convertidor de Archivos`

Current conversions:

- Images (`PNG`, `JPG`, `JPEG`, `BMP`) -> PDF.
- PDF -> images in a selected output directory.
- TXT -> DOCX.
- DOCX -> TXT.
- DOCX -> PDF.
- TXT -> KML, for an individual file or a folder batch.
- KML -> TXT, for an individual file or a folder batch.

Only one conversion is run by the window at a time. Long conversions expose cancellation, and closing the window while work is active requests cancellation before closing.

Converter outputs are transactional where the service supports publication: failed or cancelled work is not presented as a completed output. The DOCX -> PDF converter is intentionally simplified and should not be expected to reproduce complex Microsoft Word layout exactly.

## PDF Toolkit

**Menu name:** `PDF Toolkit`

The tool is organized into tabs:

### Extract text

- Select a PDF.
- Optionally select specific pages such as `1,3,5-7`; an empty page field means all pages.
- Preview the first pages before exporting.
- Export extracted text as Markdown.
- Choose one output file or one file per page.
- Optionally include page headers.
- Enable OCR when required, with an option to OCR only pages that appear empty.

The UI also exposes a configurable threshold for considering a PDF probably scanned based on pages with no extracted text.

### Split

Two modes are available:

- one PDF per page;
- custom ranges, for example `1-3,5,8-10`.

Choose a source PDF and an output directory.

### Extract pages

Select a source PDF and a page specification to create a new PDF containing only those pages.

### Reorder

Load a PDF, change page order in the graphical list and save the reordered document as a new PDF.

### Merge

Add multiple PDFs, arrange them in the desired order and write the combined result to a new PDF.

PDF operations run in the background and expose cancellation. OCR additionally requires local Tesseract/Poppler support. The PDF backend currently still uses `PyPDF2`; migration to `pypdf` remains active roadmap work.

## Duplicate Finder

The duplicate workflow scans a selected directory recursively and identifies duplicate content in several stages:

1. file size;
2. quick edge hash;
3. SHA-256;
4. final byte-for-byte comparison.

Symbolic links are skipped. Multiple hardlinks to the same physical file are intentionally not treated as duplicate copies.

When duplicate copies are moved, PythonKni keeps the first verified file in place and moves additional verified copies into:

```text
<selected-folder>\DuplicadosEncontrados\
```

Before each move the candidate is rehashed and compared again against the retained original. A JSON restoration manifest is maintained in the duplicates directory, including completed, failed or cancelled moves. Cancellation can therefore leave a partial but documented set of completed moves rather than pretending the whole operation was atomic.

Review the duplicate groups before moving files and keep the restoration manifest until you are satisfied with the result.

## Network Explorer

The network tool works with IPv4 interfaces and TCP port probes.

Typical workflow:

1. inspect the active IPv4 interfaces;
2. use the detected local network or enter an authorized IPv4 CIDR manually;
3. start host discovery;
4. inspect responding addresses, reverse-DNS names and ARP MAC data where available;
5. select a host/domain and scan an explicit TCP port range when needed.

CIDR input is bounded to at most **4096 usable hosts per scan**. Port ranges must be between `1` and `65535` and use `start-end` syntax.

Host discovery uses local `ping`, reverse DNS and ARP information. A host that ignores ICMP can therefore appear absent even when it is reachable by other protocols. Port scanning reports TCP connection results only; it is not a vulnerability scanner.

Use network scanning only on networks and systems where you have explicit authorization.

## Process Manager

**Menu name:** `Gestor de Procesos`

The process table shows PID, process name, CPU usage and memory usage. CPU and memory thresholds can be used to reduce the list.

Available actions include:

- refresh the process list;
- inspect/analyze a process executable;
- terminate the selected process.

PythonKni refuses to terminate its own process. Termination always requires confirmation with the selected process identity. Processes classified conservatively as Windows/system processes receive a second warning because terminating them may cause instability, logoff or restart.

### VirusTotal process analysis

If `VIRUSTOTAL_API_KEY` is configured, PythonKni can:

1. read the selected executable locally;
2. calculate its SHA-256 locally;
3. query VirusTotal for an existing report for that hash.

The current implementation does **not upload the executable file** to VirusTotal. A hash query still discloses that hash to the external service, so review `security.md` before using it with sensitive software.

## Temporary Cleaner

The cleaner operates only on application-defined cleanup targets rather than accepting an arbitrary directory to erase.

Current target classes include:

- user temporary directories from `TEMP`/`TMP`;
- supported browser cache locations for Chrome, Edge and Firefox profiles;
- Windows Temp where available.

Use the preview before deleting data. The preview counts candidate items and estimates file bytes without intentionally following symbolic links or Windows reparse points.

The cleaner validates that a requested root is one of the exact known targets, rejects broad roots/containers, and revalidates directory identity while traversing. Files that cannot be removed because they are locked or inaccessible are reported as failures rather than forcing deletion.

Closing applications that actively use a cache/temp directory can reduce expected permission or sharing errors.

## WiFi Profiles

The WiFi tool reads profiles saved by Windows through `netsh` and can display the stored key material returned by Windows.

Because WiFi credentials are sensitive:

- use the tool only on a Windows account/device you are authorized to inspect;
- do not include captured passwords in bug reports, screenshots or logs you share publicly;
- close the tool when the credentials no longer need to be visible.

The implementation exports each requested profile with `key=clear` into an isolated temporary directory, parses only the matching XML and removes the temporary directory when the operation finishes. Windows permissions/policy can prevent some credentials from being returned.

## Disk Analyzer

**Menu name:** `Analizador de Disco`

Select a directory and start analysis to rank the files/directories consuming the most space. The scan runs outside the main UI flow and the results can be exported for later review.

Treat reported sizes as a point-in-time view: files may change while the system is running, and inaccessible paths may not be fully represented.

## Windows Startup Manager

**Menu name:** `Gestor de Inicio de Windows`

The startup manager collects supported entries from:

- current-user `Run` registry entries;
- machine `Run` registry entries;
- the user's Startup folder;
- the common Startup folder;
- entries previously disabled by PythonKni.

It displays whether an entry is active, its command/path, origin and a heuristic risk label. Risk labels are support hints, **not malware verdicts**.

Disabling supported entries is designed to be recoverable:

- registry entries are copied into PythonKni's disabled-startup backup area before removal from the active `Run` key;
- Startup-folder entries are moved into PythonKni-managed backup storage with metadata;
- disabled entries can later be re-enabled.

Machine-level registry entries or protected locations may require elevated privileges. Do not disable entries whose purpose you do not understand.

## Windows Event Viewer

**Menu name:** `Visor de eventos de Windows`

The viewer reads Windows event logs and presents a simplified support-oriented table.

Available controls include:

- `Application`, `System` and optional `Security` logs;
- periods such as 24 hours, 7 days, 30 days or no time filter;
- maximum event count;
- event-level and heuristic risk filters;
- free-text search by source, event ID, message or interpretation;
- event detail/copy actions;
- export/report actions provided by the window.

Reading the Security log can require administrator privileges. Risk classification and interpretation are heuristics intended to help triage events; they are not a replacement for Windows diagnostics expertise or incident-response analysis.

## System Report

**Menu name:** `Informe Técnico del Equipo`

Generate a point-in-time technical report containing supported system, disk, network, process and temporary-data information. The result can be reviewed in the UI and exported as:

- TXT;
- HTML;
- PDF.

Diagnostic reports can contain hostnames, addresses, process information and other environment details. Review an exported report before sharing it externally.

## Configuration

The configuration tool manages the settings currently implemented by PythonKni, including theme and language selection.

Configuration is normalized before saving and published atomically to `config.json`, so an interrupted write does not intentionally replace the previous valid configuration with a partial file.

Localization infrastructure exists, but not every user-visible string is fully translated yet.

---

## Cancellation and closing windows

Many long-running tools use managed background workers or domain-specific worker threads. Cancellation is cooperative: the service checks a cancellation signal at safe points and stops as soon as the underlying operation permits.

This means cancellation is not identical to forcibly killing a thread or subprocess. An already completed filesystem mutation may remain completed; tools that can partially mutate state are designed to report or record that state where practical.

## Troubleshooting

### A tool does not appear in the main menu

The loader only accepts modules that satisfy the plugin contract. Run:

```powershell
python -m pytest tests/test_tool_contract.py tests/test_architecture_boundaries.py
```

A discovery/import error is logged and invalid tools are skipped instead of silently being treated as valid.

### OCR returns no text

Confirm that Tesseract OCR and Poppler are installed and visible through the expected system `PATH`/configuration. Also confirm the appropriate Tesseract language data is installed for the document.

### A Windows system action fails with access denied

Process, startup, Event Viewer, WiFi and some temp-directory operations depend on Windows permissions. Retry only if elevation is appropriate for the system you are authorized to administer; do not use elevation as a way to bypass organizational policy.

### Network scan misses a device

ICMP/ping may be blocked, reverse DNS may not exist, ARP visibility is limited to relevant local-network information, and firewalls can reject or silently drop TCP probes. A missing result is not proof that a device/service is absent.

## Development validation

Run the same core checks used by CI:

```powershell
python -m compileall .
python -m pytest
python -m ruff check .
python -m ruff format --check .
pyinstaller --noconfirm --clean PythonKni.spec
.\dist\PythonKni\PythonKni.exe --smoke-test
```

The GitHub Actions `CI / validate` job performs these checks on Windows with Python 3.10.