# Usage

This guide describes how to run PythonKni and how the current first-party tools behave from a user's perspective. PythonKni is primarily designed and validated for Windows.

For architecture details, see [`architecture.md`](architecture.md). For authorization, privacy and destructive-operation notes, see [`security.md`](security.md).

## Run PythonKni

### Supported environment

PythonKni requires **Python 3.10 or newer**. The canonical CI and release environment is **CPython 3.10.11 on Windows**.

### Development mode

Create and activate a Python 3.10 virtual environment, then install the committed SHA-256-locked dependency graphs:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python -m pip install --require-hashes -r requirements-dev.txt
python main.py
```

`requirements.in` and `requirements-dev.in` contain direct dependency policy. `requirements.txt` and `requirements-dev.txt` contain the exact transitive versions and approved distribution hashes used by CI/release. Do not hand-edit transitive pins or hashes.

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

Run the same non-interactive packaging smoke test used by CI:

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

Some features require software outside the Python lock:

- **Tesseract OCR** for OCR-based PDF text extraction.
- **Poppler** for PDF/image workflows that depend on `pdf2image`.
- Standard Windows utilities such as `netsh`, `ping`, `arp` and Windows registry/event-log facilities for the corresponding system tools.

These external executables are not covered by Python package hashes or the generated Python SBOM. Features that depend on operating-system resources can also be limited by the current user's permissions.

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

Technical archive failures use structured feedback: the main dialog explains that the operation could not be completed, while the underlying exception remains available through expandable details for troubleshooting.

## File Converter

**Menu name:** `Convertidor de Archivos`

Current conversions:

- Images (`PNG`, `JPG`, `JPEG`, `BMP`) -> PDF.
- PDF -> images in a selected output directory.
- TXT -> DOCX.
- DOCX -> TXT.
- DOCX -> PDF.
- TXT -> KML, for an individual file or folder batch.
- KML -> TXT, for an individual file or folder batch.

Only one conversion is run by the window at a time. Long conversions expose cancellation, and closing the window while work is active requests cancellation before closing.

Converter outputs are transactional where the service supports publication: failed or cancelled work is not presented as a completed output. DOCX -> PDF is intentionally simplified and should not be expected to reproduce complex Microsoft Word layout exactly.

## PDF Toolkit

**Menu name:** `PDF Toolkit`

The PDF backend uses maintained **`pypdf`** for PDF reading/writing. PyMuPDF, ReportLab and optional OCR tooling are used where their narrower capabilities are required.

### Extract text

- Select a PDF.
- Optionally select pages such as `1,3,5-7`; an empty page field means all pages.
- Preview the first pages before exporting.
- Export extracted text as Markdown.
- Choose one output file or one file per page.
- Optionally include page headers.
- Enable OCR when required, with an option to OCR only pages that appear empty.

### Split

Two modes are available:

- one PDF per page;
- custom ranges such as `1-3,5,8-10`.

### Extract pages

Select a source PDF and page specification to create a new PDF containing only those pages.

### Reorder

Load a PDF, change page order in the graphical list and save the reordered document as a new PDF.

### Merge

Add multiple PDFs, arrange them in the desired order and write the combined result to a new PDF.

PDF operations run in the background and expose cancellation. OCR additionally requires local Tesseract/Poppler support.

## Duplicate Finder

The duplicate workflow scans a selected directory recursively and identifies duplicate content in stages:

1. file size;
2. quick edge hash;
3. SHA-256;
4. final byte-for-byte comparison.

Symbolic links are skipped. Multiple hardlinks to the same physical file are intentionally not treated as duplicate copies.

When duplicate copies are moved, PythonKni keeps the first verified file in place and moves additional verified copies into:

```text
<selected-folder>\DuplicadosEncontrados\
```

Before each move the candidate is rehashed and compared again against the retained original. A JSON restoration manifest records completed, failed or cancelled moves. Cancellation can therefore leave a partial but documented result rather than pretending the whole operation was atomic.

Review duplicate groups before moving files and keep the restoration manifest until you are satisfied with the result.

## Network Explorer

The network tool works with IPv4 interfaces and TCP port probes.

Typical workflow:

1. inspect active IPv4 interfaces;
2. use the detected local network or enter an authorized IPv4 CIDR manually;
3. start host discovery;
4. inspect responding addresses, reverse-DNS names and ARP MAC data where available;
5. select a host/domain and scan an explicit TCP port range when needed.

CIDR input is bounded to at most **4096 usable hosts per scan**. Port ranges must be between `1` and `65535` and use `start-end` syntax.

Host discovery uses local `ping`, reverse DNS and ARP information. A host that ignores ICMP can therefore appear absent even when reachable by another protocol. Port scanning reports TCP connection results only; it is not a vulnerability scanner.

Use network scanning only on networks and systems where you have explicit authorization.

## Process Manager

**Menu name:** `Gestor de Procesos`

The process table shows PID, process name, CPU usage and memory usage. CPU and memory thresholds can reduce the list.

Available actions include:

- refresh the process list;
- inspect/analyze a process executable;
- terminate the selected process.

PythonKni refuses to terminate its own process. Termination requires confirmation with the selected process identity. Processes classified conservatively as Windows/system processes receive a second warning because terminating them may cause instability, logoff or restart.

Immediately before termination, the service revalidates process liveness and `create_time`, protecting against PID reuse between selection/confirmation and the destructive call.

### VirusTotal process analysis

If `VIRUSTOTAL_API_KEY` is configured, PythonKni can:

1. read the selected executable locally;
2. calculate its SHA-256 locally;
3. query VirusTotal for an existing report for that hash.

The current implementation does **not upload the executable file**. A hash query still discloses the hash to the external service, so review `security.md` before using it with sensitive software.

## Temporary Cleaner

The cleaner operates only on application-defined cleanup targets rather than accepting an arbitrary directory to erase.

Current target classes include:

- user temporary directories from `TEMP`/`TMP`;
- supported browser cache locations for Chrome, Edge and Firefox profiles;
- Windows Temp where available.

Use preview before deleting data. Preview counts candidate items and estimates bytes without intentionally following symbolic links or Windows reparse points.

The cleaner validates that a requested root is one of the exact known targets, rejects broad roots/containers and revalidates directory identity while traversing. Locked/inaccessible files are reported as failures rather than forcing deletion.

## WiFi Profiles

The WiFi tool reads profiles saved by Windows through `netsh` and can display stored key material returned by Windows.

Because WiFi credentials are sensitive:

- use the tool only on an account/device you are authorized to inspect;
- do not include captured passwords in public bug reports or screenshots;
- close the tool when credentials no longer need to be visible.

Each requested profile is exported with `key=clear` into an isolated temporary directory, matched to the correct XML profile and removed when the operation finishes. Windows permissions/policy can prevent credentials from being returned.

## Disk Analyzer

**Menu name:** `Analizador de Disco`

Select a directory and start analysis to rank files/directories consuming the most space. The scan runs outside the main UI flow and results can be exported for later review.

Symlink entries are not followed by the service, and individual inaccessible entries are skipped rather than terminating the whole analysis. Reported sizes remain a point-in-time view because files can change while the system is running.

## Windows Startup Manager

**Menu name:** `Gestor de Inicio de Windows`

The startup manager collects supported entries from:

- current-user `Run` registry entries;
- machine `Run` registry entries;
- the user's Startup folder;
- the common Startup folder;
- entries previously disabled by PythonKni.

It displays active state, command/path, origin and a heuristic risk label. Risk labels are support hints, **not malware verdicts**.

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
- export/report actions.

Reading the Security log can require administrator privileges. Risk classification and interpretation are heuristics intended to help triage events; they are not a replacement for Windows diagnostics expertise or incident-response analysis.

## System Report

**Menu name:** `Informe Técnico del Equipo`

Generate a point-in-time technical report containing supported system, disk, network, process and temporary-data information. The result can be reviewed in the UI and exported as TXT, HTML or PDF.

Diagnostic reports can contain hostnames, addresses, process information and other environment details. Review an exported report before sharing it externally.

## Configuration

The configuration tool manages implemented settings including theme and language selection.

Configuration is normalized before saving and published atomically to `config.json`, so an interrupted write does not intentionally replace a previous valid configuration with a partial file. If persistence fails, PythonKni does not apply unsaved theme/language state.

Localization infrastructure exists, but not every user-visible string is fully translated yet.

---

## Cancellation and closing windows

Many long-running tools use managed workers or domain-specific worker threads. Cancellation is cooperative: services check a cancellation signal at safe points and stop as soon as the underlying operation permits.

Cancellation is not equivalent to forcibly killing a thread/subprocess. An already completed filesystem mutation can remain completed; tools that can partially mutate state report or record that state where practical.

## Structured technical errors

Technical failures across the current first-party toolset use a common presentation rule where appropriate:

- the primary dialog/result text describes **what failed and what the user can do next**;
- **Show Details** retains the original exception type/message or diagnostic text for troubleshooting;
- raw exceptions are not deliberately embedded into normal user-facing summaries.

This applies to loader/configuration failures and technical paths in Archive, Process Manager, Converter, PDF, Network, System Report, Disk Analyzer, Startup Manager, Temp Cleaner, WiFi, Event Viewer and Duplicate Finder.

Input-validation messages, destructive confirmations and domain-specific warnings intentionally remain explicit tool dialogs. Structured technical feedback is not a replacement for business semantics.

When reporting a reproducible bug, expandable details plus the relevant `%LOCALAPPDATA%\PythonKni\logs\` entry are more useful than a screenshot containing only the generic summary. Review diagnostics before sharing them externally because they may include local paths/environment data.

## Dependency maintenance

When a direct Python dependency must change:

1. change its allowed range in `requirements.in` or `requirements-dev.in`;
2. regenerate the lock with `pip-tools` on Windows / CPython 3.10.11;
3. keep `--generate-hashes --allow-unsafe --strip-extras --no-header`;
4. run the lock validator, `pip check` and both `pip-audit` gates;
5. review version/hash changes before committing.

Dependabot checks Python dependencies and GitHub Actions weekly, but proposed updates still require the same CI validation as application changes.

## Troubleshooting

### A tool does not appear in the main menu

The loader only accepts modules that satisfy the plugin contract. Run:

```powershell
python -m pytest tests/test_tool_contract.py tests/test_architecture_boundaries.py
```

A discovery/import error is logged and invalid tools are skipped rather than silently treated as valid.

### OCR returns no text

Confirm that Tesseract OCR and Poppler are installed and visible through the expected system `PATH`/configuration. Also confirm the appropriate Tesseract language data is installed for the document.

### A Windows system action fails with access denied

Process, startup, Event Viewer, WiFi and some temp-directory operations depend on Windows permissions. Retry with elevation only when appropriate for a system you are authorized to administer; do not use elevation to bypass organizational policy.

### Network scan misses a device

ICMP/ping may be blocked, reverse DNS may not exist, ARP visibility is limited to relevant local-network information, and firewalls can reject/drop TCP probes. A missing result is not proof that a device/service is absent.

### A dependency install fails with a hash mismatch

Do not bypass `--require-hashes`. A mismatch means the artifact is not one of the distributions recorded in the lock. Regenerate locks only as part of an intentional dependency update and review the resulting diff.

---

## Development validation

The current suite contains **578 tests**, with **86.4% repository-wide branch coverage** and **93.2% aggregate service coverage** on the canonical Windows CI environment.

Run the core validation path with:

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
.\dist\PythonKni\PythonKni.exe --smoke-test
```

CI/release also enforce individual non-regression gates for the strongest and recently hardened services/windows. Current new service floors include Disk Analyzer `>=94.5%`, Duplicate `>=90.0%`, Process Manager `>=99.0%` and WiFi `>=95.5%`.
