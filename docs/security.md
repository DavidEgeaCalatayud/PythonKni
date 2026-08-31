# Security

PythonKni is a local Windows desktop utility with access to files, archives, processes, startup configuration, event logs, saved WiFi credentials and local-network targets. It is **not a sandbox**: it runs with the permissions of the Windows user that launches it and relies on Windows access-control boundaries.

> Use PythonKni only on systems, files and networks you own or are explicitly authorized to administer.

## Security model

The project reduces accidental damage and common unsafe input patterns through:

- narrow and validated destructive-operation targets;
- staged/transactional publication where practical;
- explicit confirmation for high-impact process actions;
- recoverable Startup Manager changes;
- archive traversal/resource limits;
- symlink/reparse-point handling;
- cooperative cancellation and managed worker lifecycle;
- environment-based secret configuration;
- spreadsheet-safe CSV serialization;
- exact SHA-256-hashed Python dependency locks;
- runtime/development vulnerability auditing in CI and releases;
- immutable commit-SHA pins for third-party GitHub Actions.

These controls reduce risk; they do not make malicious files or privileged operations risk-free.

## Authorization boundaries

PythonKni does **not** attempt to bypass Windows authentication, ACLs, registry permissions, Event Log permissions, encrypted-content protections, network authentication, DRM or other access controls. Operations can fail with access-denied or sharing errors. Elevate only when appropriate for a system you are authorized to administer.

---

## Data flow and privacy

### Local by default

Normal file conversion, archive, duplicate, PDF, cleanup, startup, event, disk and reporting operations execute locally. Runtime data are stored under the user profile, normally:

```text
%LOCALAPPDATA%\PythonKni\
├─ config.json
├─ logs\
├─ data\
└─ DisabledStartup\
```

The path helper can fall back to `APPDATA` or the user's home directory if `LOCALAPPDATA` is unavailable.

### VirusTotal

Process analysis calculates SHA-256 locally and queries VirusTotal for an existing report for that hash. The implementation does **not upload the executable file**. The hash itself is still disclosed to an external provider and can identify a known binary.

Configure the integration with:

```text
VIRUSTOTAL_API_KEY
```

Never hard-code or commit real API keys. If a credential is exposed, revoke/rotate it and remove it from Git history when appropriate.

### WiFi credentials

The WiFi tool invokes `netsh wlan export profile ... key=clear` to read saved profile keys. Each requested profile is exported into an isolated temporary directory, only matching XML is parsed, and that temporary directory is removed when its context closes.

The credential can still exist in cleartext temporarily and can be displayed in the UI. Treat screenshots, clipboard contents and access to the active desktop session accordingly.

---

# File and document operations

## Archive extraction

ZIP/7Z extraction validates members before publication. Default policy currently limits an archive to:

| Limit | Value |
|---|---:|
| Entries/files | 10,000 |
| Total uncompressed data | 2 GiB |
| Single file | 512 MiB |
| Compression ratio | 250:1 |
| Path depth | 32 components |
| Path length | 512 characters |

Validation rejects traversal/absolute paths, Windows device or ambiguous names, ADS-like names, duplicate/case-ambiguous destinations, symbolic links, non-regular special files and declared resource usage beyond policy. Actual extracted data are checked again before the staging tree is published. ZIP encryption is rejected by the current extraction path.

A valid archive can still contain malicious executable/document content. Archive validation is not antivirus scanning.

## Converter outputs

Supported conversion workflows stage output and publish transactionally. Failed/cancelled work should not be presented as a successful final output. Parser/rendering libraries and optional local executables are still part of the trust boundary; transactional publication is not a document sandbox.

## PDF processing and OCR

The first-party PDF backend uses **`pypdf`**, with current locked runtime version `6.16.2`. The former `PyPDF2` dependency has been removed from production code, tests and the PyInstaller collection configuration.

PDF operations process untrusted structured documents through `pypdf`, PyMuPDF and optional OCR/image tooling. OCR can invoke local Tesseract/Poppler-based processing. PythonKni does not intentionally send PDF/OCR contents to a remote service.

The PDF toolkit does not provide a hardened document sandbox or antivirus verdict. Corrupt or adversarial documents can still cause dependency-specific failures or high resource use.

## Duplicate management

Duplicate detection uses size, quick hashing, SHA-256 and a final byte-for-byte comparison. Symbolic links are skipped, hardlinks to the same physical file are not treated as independent reclaimable duplicates, and candidates are revalidated immediately before moving.

Moved copies go to `DuplicadosEncontrados` rather than being deleted. A JSON restoration manifest records completed, failed and cancelled moves.

## Temporary Cleaner

Temporary cleanup is allowlist-based. The service does not accept an arbitrary recursive deletion root. It validates exact known cleanup targets, rejects broad roots/containers, does not traverse symbolic links or Windows reparse points and revalidates directory identity around destructive steps.

Python path-based APIs cannot mathematically eliminate every possible Windows filesystem TOCTOU race. Treat cleanup as destructive: review the preview and keep important data outside temp/cache targets.

---

# System operations

## Process termination

The Process Manager refuses to terminate PythonKni itself, obtains a process identity snapshot, requires confirmation, adds an extra warning for likely system processes and revalidates PID liveness plus `create_time` immediately before termination. Heuristic system classification is a guardrail, not proof that another process is safe to terminate.

## Startup Manager

Supported registry and Startup-folder changes preserve recoverable state before removing/disabling active entries. Rollback paths exist for transactional failures, including explicit handling where both an operation and its rollback fail.

Permissions can block machine-level changes, and the UI's `Normal/Medio/Alto` labels are support heuristics rather than malware classifications.

## Windows Event Viewer and system reports

Event logs and generated reports can contain usernames, hostnames, local paths, process names, addresses and application-specific messages. Security-log access can require elevation. Review/redact exported CSV/HTML/PDF/TXT material before sharing it externally.

Risk labels and interpretations are triage aids, not an incident-response determination.

---

# Network operations

Network Explorer performs active local probes including ICMP/ping discovery, reverse DNS, ARP inspection and TCP connection attempts. CIDR discovery is bounded to at most 4096 usable IPv4 addresses and ports are restricted to `1..65535`.

These limits are not authorization controls. Firewalls, ICMP filtering, NAT and DNS can also produce incomplete or misleading observations.

---

# WiFi Auditor

WiFi Auditor is a defensive configuration/inventory boundary separate from the stored-profile viewer. Its live path asks Windows for visible BSSID metadata and analyzes only the information exposed by that operating-system command. It does not obtain or validate credentials.

The current feature deliberately excludes monitor mode, frame injection, active WPS probing, authentication-material capture, password-list generation, password cracking and deceptive/clone access points. An inconsistent SSID/security observation is surfaced as a manual-review indicator and is not treated as proof that a BSSID is malicious.

Exported evidence contains local wireless metadata such as SSID/BSSID, channel, signal and security configuration. Treat those reports as environment-sensitive diagnostic data before sharing them.

Each report contains a SHA-256 integrity digest calculated over canonical JSON. Verification can detect changed content but does not authenticate the person or machine that created the report. The digest is not a digital signature and does not by itself establish forensic chain of custody.

Report publication is transactional through same-directory temporary output plus `fsync` and `os.replace`. The Docker image under `docker/wifi-auditor/` performs offline report verification only and receives the report directory read-only in the documented invocation; it does not perform live wireless scanning.

---

# CSV exports

Shared CSV serialization neutralizes values that common spreadsheet software could interpret as formulas, including dangerous prefixes after leading whitespace/tab characters. New export paths should reuse the shared helper rather than implement independent CSV escaping.

---

# Dependency and supply-chain security

Python dependencies use a two-layer model:

```text
requirements.in      / requirements-dev.in   # direct dependency policy
requirements.txt     / requirements-dev.txt  # exact transitive pins + SHA-256 hashes
```

The committed locks are generated for the canonical Windows / **CPython 3.10.11** environment with `pip-tools --generate-hashes`. CI and release install them with:

```powershell
python -m pip install --require-hashes -r requirements.txt
python -m pip install --require-hashes -r requirements-dev.txt
```

`scripts/check_dependency_locks.py` additionally verifies that every lock entry is an exact `==` pin with one or more valid SHA-256 hashes, direct dependencies exist and satisfy their declared range, and shared runtime/development packages do not resolve to conflicting versions. `pip check` then validates the installed graph.

Both runtime and development locks are audited with `pip-audit`. A known vulnerability is a failing CI/release gate rather than an informational warning. This hardening already caught `PYSEC-2026-3447` in `setuptools 80.10.2`; the development policy was raised to a fixed branch and regenerated rather than suppressing the advisory.

CI also emits a CycloneDX JSON SBOM for the runtime dependency graph. The Windows bundle artifacts retain the SBOM and both dependency locks; tagged releases publish them alongside the ZIP/checksum.

Third-party GitHub Actions in CI/release are pinned by immutable commit SHA. Dependabot checks Python dependencies and GitHub Actions weekly.

### Supply-chain limits

These controls materially improve reproducibility and integrity, but do not provide a proof of package safety:

- hashes ensure an artifact matches the reviewed lock, not that the publisher's artifact is non-malicious;
- vulnerability databases only contain known/published advisories;
- `pip-audit` cannot guarantee absence of undisclosed vulnerabilities;
- Tesseract, Poppler, Windows utilities and other external executables are outside the Python lock and Python SBOM;
- the canonical dependency/build contract is Windows + CPython 3.10.11; other environments are not currently claimed by CI.

Dependency changes should modify `.in` policy first, regenerate locks with `pip-tools`, review the diff, pass both audits and pass the complete build/smoke pipeline before merge.

---

## Packaged executable

CI builds PythonKni with PyInstaller and executes the frozen `PythonKni.exe --smoke-test` to validate packaged tool discovery and required assets. This confirms packaging viability; it is not code signing or antivirus certification.

Windows executable signing and installer generation remain future release-engineering work. Verify the origin/checksum of executables obtained outside the repository's validated release path.

## Reporting sensitive problems

When reporting a bug, provide only the minimum reproduction data necessary and redact API keys, WiFi passwords, private documents, local identifiers, logs and diagnostic exports where possible.
