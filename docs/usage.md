# Usage

This guide describes how to run PythonKni and how the current first-party tools behave from a user's perspective. PythonKni is primarily designed and validated for Windows.

For architecture details, see [`architecture.md`](architecture.md). For the canonical interpreter contract, see [`python-runtime.md`](python-runtime.md). For authorization, privacy and destructive-operation notes, see [`security.md`](security.md).

## Run PythonKni

### Supported environment

PythonKni supports the **Python 3.13 series** (`>=3.13,<3.14`). The canonical CI and release environment is **CPython 3.13.15 on Windows** using the normal GIL-enabled build.

### Development mode

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
python -m pip install --require-hashes -r requirements-dev.txt
python main.py
```

`requirements.in` and `requirements-dev.in` contain direct dependency policy. `requirements.txt` and `requirements-dev.txt` contain the exact transitive versions and approved distribution hashes used by CI/release. Do not hand-edit transitive pins or hashes.

The main window discovers valid `tools/*_tool.py` adapters dynamically and adds their `Tool` classes to the menu.

### Packaged application

```powershell
pyinstaller --noconfirm --clean PythonKni.spec
.\dist\PythonKni\PythonKni.exe --smoke-test
```

The smoke-test mode validates frozen tool discovery and required packaged assets without opening the normal Qt interface.

## Runtime data

PythonKni keeps user-specific runtime files outside the repository. On a normal Windows installation the base directory is `%LOCALAPPDATA%\PythonKni\`, with configuration, data and logs below that root. If `LOCALAPPDATA` is unavailable, PythonKni falls back to `APPDATA` and finally to a user-home fallback.

## Optional system dependencies

Some features require software outside the Python lock:

- **Tesseract OCR** for OCR-based PDF text extraction.
- **Poppler** for PDF/image workflows that depend on `pdf2image`.
- Standard Windows utilities such as `netsh`, `ping`, `arp` and Windows registry/event-log facilities for corresponding system tools.

These executables are not covered by Python package hashes or the generated Python SBOM. Features that depend on operating-system resources can also be limited by the current user's permissions.

---

# Tool guide

## Archive Manager

Archive creation/extraction runs in a background worker, exposes progress and cancellation, and publishes staged output only after successful completion. Extraction rejects unsafe archive members and enforces size/count/path/compression safety limits. See [`security.md`](security.md).

## File Converter

Current conversions include images -> PDF, PDF -> images, TXT <-> DOCX, DOCX -> PDF and TXT <-> KML including supported batch workflows. Only one conversion is run by the window at a time; long conversions support cooperative cancellation. Transactional publication is used where supported. DOCX -> PDF is intentionally simplified and cannot reproduce every Word layout exactly.

## PDF Toolkit

PDF reading/writing uses maintained `pypdf`; PyMuPDF, ReportLab and optional OCR tooling retain narrower roles. The toolkit supports text extraction, page selection/preview, split/extract/reorder/merge and OCR-assisted workflows. OCR requires local Tesseract/Poppler support.

## Duplicate Finder

Duplicate discovery is staged through file size, quick edge hashing, SHA-256 and final byte equality. Symlinks are skipped and hardlinks to the same physical file are not treated as reclaimable duplicate copies. Moves are revalidated and accompanied by restoration manifests.

## Network Explorer

Use the detected local network or enter an authorized IPv4 CIDR, run host discovery, inspect reverse-DNS/ARP evidence and optionally scan an explicit TCP range on a selected target. Network Explorer remains a diagnostic tool rather than a vulnerability scanner; use it only with explicit authorization.

## Camera Exposure Auditor

Camera Exposure Auditor accepts only bounded authorized local IPv4 scope, supports local ONVIF discovery plus HTTP/HTTPS/RTSP exposure evidence, and can export findings. It does **not** attempt usernames/passwords/default credentials or retrieve streams/images. Network Explorer can hand off one exact `/32` host only when the persisted Network Intelligence identity supports a Camera match.

## Network Intelligence

Network Intelligence composes bounded local discovery with persistent asset inventory, stable identity reconciliation, relationship/topology evidence, contextual Security Score, classification confidence, device-specific auditors and snapshot reporting.

Current historical/automation workflows include:

- offline comparison of saved JSON/ZIP snapshots;
- offline Security Score History;
- opt-in in-app scheduling and automatic JSON snapshots;
- deterministic local change notifications over consecutive automatic snapshots;
- History Center with per-scope time filters, native trend charts, previous/next navigation and comparison;
- configurable count/age retention restricted to validated scheduler-owned snapshots, always protecting the newest two valid snapshots per scope.

Scheduling changes when the existing authorized workflow runs; it does not broaden what can be scanned and does not install a Windows service/daemon. See [`network-intelligence.md`](network-intelligence.md), [`network-scheduled-monitoring.md`](network-scheduled-monitoring.md), [`network-change-notifications.md`](network-change-notifications.md) and [`network-history-center.md`](network-history-center.md).

## Process Manager

The process table supports refresh/filtering, optional VirusTotal hash-report lookup and selected-process termination. PythonKni refuses to terminate itself, requires confirmation, adds a second warning for conservatively classified system processes and revalidates PID liveness plus `create_time` immediately before termination.

Optional VirusTotal analysis hashes the selected executable locally and queries an existing report by SHA-256. It does not upload the executable, although the hash is disclosed to the external provider.

## Temporary Cleaner

The cleaner operates only on application-defined authorized cleanup targets. Preview and destructive traversal do not intentionally follow symbolic links/reparse points; exact allowed roots and directory identity are revalidated while deleting. Locked/inaccessible files are reported rather than forced.

## WiFi Profiles

The WiFi tool reads profiles saved by Windows through `netsh` and can display stored key material returned by Windows. Each requested profile is exported with `key=clear` into an isolated temporary directory, matched to the correct XML and removed after use. Treat displayed credentials as sensitive.

## Disk Analyzer

Select a directory to rank files/directories consuming the most space and optionally export CSV. Symlink entries are not followed; inaccessible entries are skipped rather than terminating the whole analysis.

## Windows Startup Manager

The startup manager collects supported Run registry/Startup folder entries plus entries previously disabled by PythonKni. Supported disable operations preserve recoverable metadata; re-enable logic refuses unsafe overwrites. Machine-level changes may require elevation.

## Windows Event Viewer

The viewer reads Windows event logs with log/time/count/risk/text filters, detail/copy actions and export/report workflows. Security log access may require administrator privileges. Risk classification is a support heuristic, not an incident-response verdict.

## System Report

Generate a point-in-time system/disk/network/process/temp report and export TXT/HTML/PDF. Reports can contain local environment data; review before sharing externally.

## Configuration

Theme/language configuration is normalized and atomically persisted. If saving fails, PythonKni does not apply the unsaved state. Localization infrastructure exists, but not every user-visible string is fully translated yet.

---

## Cancellation and closing windows

Many long-running tools use managed workers or specialized worker threads. Cancellation is cooperative; an already completed mutation can remain completed, and tools that can partially mutate state report/record that state where practical. Presentation regressions protect worker overlap, stale/current callbacks, cancellation state and deferred-close behavior where applicable.

## Structured technical errors

Technical failures use a common rule where appropriate: the primary text describes what failed/what to do next, while **Show Details** retains original exception/diagnostic information. Input validation, destructive confirmations and domain-specific warnings remain explicit tool dialogs. Review logs/details before sharing because they can contain local paths/environment data.

## Dependency and OUI maintenance

Direct Python dependency changes require updating the relevant `.in` policy, regenerating locks on Windows / CPython 3.13.15, preserving hashes and passing lock validation, `pip check` and both audit gates.

Network Intelligence OUI maintenance is separate from runtime lookup. `scripts/update_oui_registry.py` can fetch/parse the official IEEE MA-L source during explicit maintenance, while `validate` checks the committed CSV + provenance metadata offline. Normal application use never submits MAC addresses to IEEE.

## Troubleshooting

- **Tool missing from menu:** run `python -m pytest tests/test_tool_contract.py tests/test_architecture_boundaries.py` and inspect loader logs.
- **OCR returns no text:** verify Tesseract/Poppler availability and relevant language data.
- **Windows action gets access denied:** elevation may be required on an authorized system; do not use it to bypass policy.
- **Network scan misses a device:** ICMP, reverse DNS, ARP visibility and firewall policy can all affect observation; absence is not proof a host/service does not exist.
- **Hash-locked install fails:** do not bypass `--require-hashes`; regenerate locks only as part of an intentional dependency change.

---

## Development validation

The current behavior-driven suite contains **1,060 tests**, with **92.8% repository-wide branch coverage** and **93.5% aggregate service coverage** on Windows / CPython 3.13.15.

The normal CI-equivalent validation path is:

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
pyinstaller --noconfirm --clean PythonKni.spec
.\dist\PythonKni\PythonKni.exe --smoke-test
```

CI and Release additionally enforce the individual service/window coverage floors encoded in the workflows. Network Intelligence typing currently protects >=92.64% structural annotation coverage, >=668 annotated slots, >=263 fully annotated callables, >=303 tracked callables and <=39 explicit `Any` annotations, with 15 strict modules required to stay complete/no-`Any`.