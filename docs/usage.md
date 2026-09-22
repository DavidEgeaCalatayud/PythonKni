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
- **Windows OpenSSH Client (`scp.exe`)** when Secure Transfer sends files or folders through the pinned Tailcat transport.
- Standard Windows utilities such as `netsh`, `ping`, `arp`, `pktmon` and Windows registry/event-log facilities for corresponding system tools.

These executables are not covered by Python package hashes or the generated Python SBOM. Features that depend on operating-system resources can also be limited by the current user's permissions. Nerva, Tailcat and Trippy are separate pinned native components staged and verified by PythonKni's build/release pipeline rather than ordinary system dependencies.

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

Use the detected local network or enter an authorized IPv4 CIDR, run host discovery, inspect reverse-DNS/ARP evidence and optionally scan an explicit TCP range on a selected target. Network Explorer remains a diagnostic tool rather than an unrestricted vulnerability scanner; use it only with explicit authorization.

## Camera Exposure Auditor

Camera Exposure Auditor accepts only bounded authorized local IPv4 scope, supports local ONVIF discovery plus HTTP/HTTPS/RTSP exposure evidence, and can export findings. It does **not** attempt usernames/passwords/default credentials or retrieve streams/images. Network Explorer can hand off one exact `/32` host only when the persisted Network Intelligence identity supports a Camera match.

## Web Recon Auditor

Web Recon Auditor starts from one explicit HTTP/HTTPS URL or DNS hostname and audits DNS, TLS, HTTP security posture and bounded web-surface evidence. It does not accept CIDR/range input and does not turn one web target into internet-wide discovery. Active checks remain explicit and bounded, while external discovery/enrichment is kept separate from the target's local HTTP/TLS evidence.

See [`web-recon-auditor.md`](web-recon-auditor.md) for its target, redirect, discovery and safety boundaries.

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

## Network Traffic Monitor

Network Traffic Monitor provides passive, local Windows network observability without fabricating packet-level information that the operating system has not supplied.

- Select a local adapter and inspect exact interface RX/TX rates from Windows counters.
- Inspect current TCP/UDP socket activity with PID/process attribution where Windows exposes it.
- Review per-process and per-host aggregation, LAN/public endpoint classification and conservative common-protocol inference.
- Reverse DNS is bounded; public ASN/prefix enrichment through RIPEstat is **opt-in** and is the monitor's only external metadata lookup.
- The **Connections / Processes / Hosts / History / Alerts** views separate live observations from persisted temporal history.
- Process rows describe observed socket activity; they are **not** fabricated per-process byte counters.
- Deterministic events such as new external connections, remote hosts, listening ports, process network activity, traffic spikes, known-asset connections and unusual destinations are published into the canonical Network Intelligence notification/history pipeline.
- Network Intelligence joins are read-only: monitor observations do not create synthetic assets, silently change device classifications or rewrite persisted `RiskLevel`.
- Packet capture is a separate explicit local action using Windows `pktmon`, with ETL -> PCAPNG conversion when the platform supports it.

The monitor performs no packet injection, credential/default-password attempts, exploitation, payload decryption or internet-wide discovery. See [`network-traffic-monitor.md`](network-traffic-monitor.md) and [`network-monitor-intelligence-integration.md`](network-monitor-intelligence-integration.md).

## Network Path Analyzer

Network Path Analyzer answers a different question from Network Explorer and Network Traffic Monitor: **where along the current route does latency or path degradation begin?**

- Enter one explicit hostname or IP; CIDRs, ranges, lists and URLs are rejected.
- Select **ICMP**, **UDP** or **TCP** tracing plus Auto/IPv4/IPv6 address family.
- Configure a bounded interval and max TTL; UDP defaults to port 33434 and TCP to 443 unless explicitly changed.
- Inspect per-hop responding host/IP sets, sent/received observations, response loss, last/average/min/max RTT and jitter.
- Review a destination RTT timeline plus bounded History and Alerts views.
- Stable route changes can emit `route_changed`, `hop_added` and `hop_removed` only after repeated confirmation.
- Sustained destination degradation can emit `latency_spike`, `packet_loss` and `destination_unreachable`.
- Discrete path events are published to the same canonical Change Notification / History Center pipeline used by other temporal network tools, with source `Network Path Analyzer`.

A key interpretation rule is deliberate: **a missing reply from an intermediate router is not proof that it is dropping forwarded traffic**. Routers commonly rate-limit or ignore TTL-expired diagnostic responses. PythonKni therefore calculates `packet_loss` from destination observations and does not emit `hop_removed` from a single transient silent hop.

The first plausible accumulated RTT step is highlighted when evidence supports it, but that is diagnostic evidence rather than proof that the router at that TTL is itself faulty; return-path asymmetry and ICMP scheduling can influence hop RTTs.

The probe backend is the exact pinned **Trippy 0.13.0** Windows runtime, isolated behind PythonKni's own backend adapter. PythonKni does not embed Trippy's TUI and does not download it at application runtime. On Windows, Trippy tracing requires **Administrator privileges** for its raw-socket probe modes; if PythonKni is not elevated, the analyzer reports that explicitly instead of silently substituting a different measurement.

See [`network-path-analyzer.md`](network-path-analyzer.md) for route-diff semantics, thresholds, supply-chain verification and limitations.

## Secure Transfer

Secure Transfer isolates the experimental Tailcat transport behind PythonKni's own service/backend boundary. The validated transport is pinned to the supported Tailcat release and uses ephemeral keys for PythonKni-managed operations.

- Send text directly through the supported transport flow.
- Send files or folders when Windows OpenSSH Client (`scp.exe`) is available.
- Expose an explicit local service through a temporary secure tunnel.
- Forward a remote Tailcat service to a **127.0.0.1-only** local bind.
- Receive directories only when the user explicitly enables that mode.

PythonKni does not implement or decode Tailcat's unstable wire format, does not modify the Windows routing table/DNS, does not save Tailcat keys, does not enable exit-node/auth-free-SSH/read-write-share behavior and does not create `0.0.0.0` forwarding binds. Tailcat's public DERP relays are an availability fallback, not a PythonKni-operated service or SLA, and the upstream project remains experimental for mutually untrusted parties.

See [`secure-transfer.md`](secure-transfer.md) for the exact transport, trust and packaging contract.

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

Pinned native transports/engines are also build-time concerns. Nerva, Tailcat and Trippy are staged only through their checked-in lock/verification scripts; the application does not silently self-update those binaries at runtime.

## Troubleshooting

- **Tool missing from menu:** run `python -m pytest tests/test_tool_contract.py tests/test_architecture_boundaries.py` and inspect loader logs.
- **OCR returns no text:** verify Tesseract/Poppler availability and relevant language data.
- **Secure Transfer file/folder send is unavailable:** verify Windows OpenSSH Client and `scp.exe` are present on `PATH`.
- **Network Path Analyzer says Administrator privileges are required:** close PythonKni and reopen it with **Run as administrator** only when you are authorized to probe the target/network. This requirement comes from Trippy's Windows raw-socket tracing model.
- **A middle hop shows 100% response loss but later hops/destination answer:** do not interpret that as forwarding loss by itself; intermediate routers can rate-limit diagnostic replies. Use destination loss and subsequent-hop behavior.
- **Windows action gets access denied:** elevation may be required on an authorized system; do not use it to bypass policy.
- **Network scan/monitor misses a device or flow:** ICMP, reverse DNS, ARP visibility, socket lifetime, permissions and firewall policy can affect observation; absence is not proof a host/service/flow does not exist.
- **Hash-locked install fails:** do not bypass `--require-hashes`; regenerate locks only as part of an intentional dependency change.

---

## Development validation

The canonical Windows CI validates the **entire** behavior-driven suite on the candidate commit; documentation intentionally records enforced floors instead of a test-count snapshot that becomes stale as new domains land.

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
.\scripts\fetch_nerva.ps1
.\scripts\fetch_tailcat.ps1
.\scripts\fetch_trippy.ps1
pyinstaller --noconfirm --clean PythonKni.spec
.\dist\PythonKni\PythonKni.exe --smoke-test
.\scripts\package_windows_bundle.ps1 -OutputPrefix "PythonKni-windows-x64"
.\scripts\build_windows_installer.ps1 -OutputPrefix "PythonKni-windows-x64-setup"
.\scripts\smoke_test_windows_installer.ps1 -InstallerPath ".\dist\PythonKni-windows-x64-setup.exe"
```

CI and Release additionally enforce the individual service/window/refactored-code coverage floors encoded in the workflows, validate the pinned Nerva/Tailcat/Trippy distribution contracts and verify the real packaged application. Network Intelligence keeps its structural typing ratchet, while repository-wide branch coverage must remain **>=92.5%** and aggregate `service.py` coverage **>=93.0%**.
