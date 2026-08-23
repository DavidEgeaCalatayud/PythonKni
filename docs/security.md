# Security

PythonKni is a local desktop utility with access to files, archives, processes, Windows startup configuration, event logs, saved WiFi credentials and local-network targets. This document describes the controls the project currently implements, the sensitive data it can expose, and the limits of those controls.

> Use PythonKni only on systems, files and networks you own or are explicitly authorized to administer.

## Security model

PythonKni does not provide a security sandbox. It runs with the permissions of the Windows user that starts it and relies on the operating system to enforce access-control boundaries.

The project aims to reduce accidental damage and common unsafe input patterns through:

- narrow, validated destructive-operation targets;
- staged/transactional publication where practical;
- confirmation before high-impact process actions;
- recoverable startup-management changes;
- archive traversal/resource limits;
- symlink/reparse-point handling;
- cancellation and worker lifecycle management;
- local secret configuration rather than hard-coded credentials;
- spreadsheet-safe CSV serialization for exported untrusted text.

These controls reduce risk; they do not turn untrusted files or privileged system operations into risk-free actions.

## Authorization boundaries

PythonKni does **not** attempt to bypass:

- Windows authentication or access control;
- filesystem ACLs;
- registry permissions;
- Event Log permissions;
- encrypted content protections;
- network authentication;
- DRM or other access controls.

Some operations can fail with `AccessDenied`, sharing violations or other permission errors. Elevate only when that is appropriate for a system you are authorized to administer.

---

## Data flow and privacy

### Local by default

Normal file conversion, archive, duplicate, PDF, cleanup, startup, event, disk and reporting operations are executed locally. PythonKni does not require an application account or backend server.

Runtime configuration/data are stored under the user profile, normally:

```text
%LOCALAPPDATA%\PythonKni\
```

Important paths include:

```text
config.json
logs\
data\
DisabledStartup\
```

The exact fallback base can use `APPDATA` or the user's home directory if `LOCALAPPDATA` is unavailable.

### VirusTotal

Process analysis is the current external network integration documented by the project.

PythonKni:

1. reads the selected executable locally;
2. calculates SHA-256 locally;
3. sends a request containing that hash to the VirusTotal API;
4. reads an existing analysis result when available.

The current implementation **does not upload the executable file** to VirusTotal. However, the file hash is still data disclosed to an external provider and can identify a known binary. Do not use the integration if disclosing that hash is prohibited by your environment or policy.

### WiFi credentials

The WiFi tool handles genuinely sensitive credential material. On Windows it invokes `netsh wlan export profile ... key=clear` in order to read saved profile keys.

To reduce persistence of that cleartext material, each profile is exported into an isolated temporary directory, only XML whose profile name matches the requested profile is parsed, and the temporary directory is removed when its context closes.

This is **not** equivalent to saying the password never appears in cleartext: the credential can be present in the temporary XML while the operation is running and can be displayed in the PythonKni UI. Treat screenshots, clipboard contents and anyone with access to the desktop session accordingly.

---

## Secrets

Do not hard-code API keys in source code or commit them to the repository.

VirusTotal integration reads:

```text
VIRUSTOTAL_API_KEY
```

PowerShell example:

```powershell
$env:VIRUSTOTAL_API_KEY="your_api_key_here"
```

Never commit:

- `.env` files containing real secrets;
- API keys or tokens;
- WiFi passwords;
- private diagnostic exports;
- personal logs or scan histories that should not be public.

If a key was committed or shared accidentally:

1. revoke it at the provider;
2. create a replacement;
3. update the local environment;
4. remove the exposed secret from Git history when appropriate.

---

# File and document operations

## Archive extraction

ZIP/7Z extraction validates archive members before publication.

Default extraction policy currently limits an archive to:

| Limit | Value |
|---|---:|
| Entries/files | 10,000 |
| Total uncompressed data | 2 GiB |
| Single file | 512 MiB |
| Compression ratio | 250:1 |
| Path depth | 32 components |
| Path length | 512 characters |

Archive member validation rejects, among other cases:

- absolute paths and drive-qualified paths;
- empty components, `.` and `..` traversal components;
- Windows-reserved device names;
- ambiguous Windows names ending in spaces/dots or containing `:`;
- duplicate/case-ambiguous output paths;
- symbolic links;
- non-regular special files;
- declared sizes or compression ratios beyond policy.

During extraction, PythonKni also checks actual bytes written against declared/permitted sizes and verifies the extracted tree before publication. ZIP encryption is rejected by the current ZIP extraction path.

Extraction takes place in a sibling staging directory. The final destination must not already exist, and the staged directory is renamed into place only after validation succeeds. On failure/cancellation, the staging directory is removed where possible.

### What this does not guarantee

Archive validation is a defense against common traversal, link and decompression-bomb patterns. It is not a malware scanner. A perfectly valid extracted executable/document can still be malicious when opened later.

## Converter outputs

Conversion services use staged/transactional output publication for supported workflows. Failed or cancelled conversions should not be presented as successfully completed partial outputs.

This protects publication consistency; it does not make parsers/renderers a sandbox. PDF, image, DOCX, KML and OCR processing relies on Python libraries and optional local executables. Treat deliberately malicious input as untrusted content and keep dependencies patched.

## PDF processing and OCR

PDF operations manipulate untrusted structured documents through the configured PDF/image/OCR dependencies. PythonKni currently uses `PyPDF2` in part of the PDF stack; migration to `pypdf` remains roadmap work.

OCR can invoke Tesseract/Poppler-based processing locally. PythonKni does not intentionally send OCR content to a remote service, but temporary/intermediate data and memory use remain local-machine concerns.

The PDF tool does not provide a hardened document sandbox or antivirus verdict. Highly complex/corrupted inputs can still trigger high resource use or dependency-specific failures.

## Duplicate management

Duplicate detection does not rely on a single hash comparison. Candidates are narrowed by size and a quick hash, then checked with SHA-256 and a final byte-for-byte comparison.

Additional safeguards include:

- symbolic links are skipped during scanning/moving;
- paths that are hardlinks to the same physical file are not treated as independent duplicates;
- a candidate is rehashed and byte-compared immediately before moving;
- the first verified file is retained;
- moved copies are placed in `DuplicadosEncontrados` rather than deleted;
- a JSON restoration manifest is updated atomically as moves are planned/completed/failed/cancelled.

Cancellation is cooperative. Files already moved before cancellation remain moved and are recorded in the manifest. Review the manifest before deleting the duplicates directory permanently.

## Temporary Cleaner

Temporary cleanup is intentionally allowlist-based.

The service does not accept an arbitrary directory and recursively erase it. A root must resolve to one of the exact cleanup targets generated by PythonKni (supported user temp/cache/Windows Temp locations) and must be inside an expected container. Broad roots such as the user home, drive root, `LOCALAPPDATA`, Windows root or temp-parent containers are forbidden as direct cleanup roots.

Before and during traversal, the cleaner uses `lstat`-style inspection and rejects/fails closed around symbolic links and Windows reparse points. It revalidates directory identity (`st_dev`/`st_ino` where exposed) before destructive steps and uses non-recursive `rmdir()` after child processing so newly arrived content causes failure instead of an unexpected recursive deletion.

When a child itself is a symlink/reparse point, PythonKni attempts to remove the link/junction object, not traverse into its target.

### TOCTOU limitation

These checks materially reduce path-substitution/race risk, but Python's ordinary path-based standard-library APIs cannot provide a mathematical guarantee that no final time-of-check/time-of-use race can ever exist on Windows. A stronger design would require native handle-relative Windows filesystem operations throughout the destructive path.

Therefore, cleanup should still be treated as a destructive operation: review the preview, close applications actively writing to those locations, and keep important data out of temp/cache targets.

---

# System operations

## Process termination

The Process Manager:

- refuses to terminate the running PythonKni process itself;
- re-reads process identity before termination;
- shows PID/name/path in a confirmation dialog;
- classifies likely Windows/system processes conservatively;
- requires an additional warning/confirmation for likely system processes.

These are guardrails, not proof that a non-flagged process is safe to terminate. Process names, users and locations can be ambiguous, and terminating the wrong process can cause data loss or instability.

## Startup Manager

The Startup Manager supports recoverable changes rather than simply deleting every startup entry.

For supported registry entries, PythonKni creates backup metadata under its disabled-startup registry area before removing the active value. For Startup-folder entries, it stores the disabled item/metadata under PythonKni-managed local backup storage. Re-enable operations restore the saved state.

The service contains rollback paths for transactional failures and raises a dedicated transaction error when both an operation and its rollback fail.

Limits:

- permissions can prevent reading/writing machine-level entries;
- heuristic `Normal/Medio/Alto` labels are **not malware classifications**;
- restoring an entry can fail if its original environment/path has changed;
- registry/startup changes can affect login behavior, so inspect entries before modifying them.

## Windows Event Viewer

Application/System/Security event data can contain usernames, hostnames, file paths, process names, account identifiers, IP addresses and application-specific messages.

The Security log may require elevated permissions. Exported CSV/HTML/PDF or copied event details should be reviewed before external sharing.

PythonKni's risk labels and interpretations are triage heuristics, not an incident-response determination and not a substitute for validating the original Windows event/context.

## System reports

System reports intentionally aggregate diagnostic information. Depending on what the current machine exposes, an export can contain operating-system, hardware, disk, network and process details.

Treat exported TXT/HTML/PDF reports as potentially sensitive support artifacts. Review and redact them before posting publicly or attaching them to third-party tickets.

---

# Network operations

The Network Explorer performs active local probes:

- ICMP/ping-based host discovery;
- reverse DNS lookups;
- local ARP inspection;
- TCP connection attempts across a selected port range.

The CIDR parser restricts one host-discovery operation to at most 4096 usable IPv4 addresses, and port input is validated to `1..65535`.

These limits bound accidental scan size; they are **not authorization controls**. PythonKni cannot know whether you are permitted to scan a target. The user is responsible for limiting scans to systems/networks they own or are explicitly authorized to assess.

Network results are observational rather than authoritative: firewalls, ICMP filtering, NAT, DNS and host policy can produce false negatives or incomplete metadata.

---

# CSV and spreadsheet exports

Shared CSV export helpers neutralize values that could otherwise be interpreted as spreadsheet formulas when opened by common spreadsheet software. This reduces CSV formula-injection risk for exported event/network/disk data containing attacker-controlled text.

This protection applies to the project's shared CSV serialization path; it should not be assumed for arbitrary third-party/manual export code added in the future unless it uses the same helper and tests.

---

# Logging and diagnostics

Logs are written to the user's PythonKni runtime area rather than the repository. Logging is useful for diagnosis but should not be treated as a secure secret vault.

Before sharing logs or GitHub issue attachments, check for:

- local paths/usernames;
- hostnames/IP addresses;
- process/application names;
- document names;
- event-log content;
- API/service error payloads.

Do not intentionally log WiFi passwords or API keys.

---

## Dependency and supply-chain limits

PythonKni depends on third-party Python packages and system executables. Security therefore also depends on the versions installed on the machine.

Current dependency metadata primarily uses minimum-version constraints rather than a fully locked, reproducible dependency graph. Automated dependency-security scanning/locking is roadmap work.

Keep Python, Windows, Tesseract/Poppler and Python dependencies updated from trusted sources.

## Packaged executable

CI builds PythonKni with PyInstaller on Windows and runs a frozen `--smoke-test` that validates tool discovery and required assets. That smoke test confirms packaging viability; it is not a code-signing, antivirus or security certification.

Current CI does not publish a signed Windows release. Verify the origin of any executable you receive outside the repository/build process.

## Reporting sensitive problems

When reporting a bug:

- provide the minimum reproduction data necessary;
- redact secrets and personal/system identifiers;
- do not upload real WiFi passwords or API keys;
- do not attach private documents merely to demonstrate a parser issue if a synthetic sample can reproduce it.

If reproducing a security issue requires sensitive material, avoid placing that material in a public GitHub issue.