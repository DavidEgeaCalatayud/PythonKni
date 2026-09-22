# Release readiness

This document records PythonKni's Windows release-engineering contract after the verified `v0.1.0` release, the first-class installer milestone, pinned Nerva integration, Web Recon, Secure Transfer/Tailcat, Service Intelligence v2, the passive Network Traffic Monitor integration and the Trippy-backed Network Path Analyzer.

## Released baseline

`pyproject.toml` currently declares:

```text
0.1.0
```

`v0.1.0` is published as the first public release. Its tag remains an immutable reference to the exact released source revision. The release contains the validated portable Windows ZIP/checksum plus the CycloneDX SBOM, OUI provenance metadata and both dependency locks.

Installer generation and the later native Nerva/Tailcat/Trippy packaging contracts were added **after** `v0.1.0`, so the historical `v0.1.0` release intentionally remains unchanged. Future releases built from current source add the versioned setup executable/checksum and embed the verified native components supported by that exact source revision.

## Current candidate contract

Current Windows / **CPython 3.13.15** candidates are accepted by enforced gates rather than by a copied test-count snapshot. The exact candidate commit must pass:

- the full behavior-driven pytest suite;
- **>=92.5%** repository branch coverage;
- **>=93.0%** aggregate `service.py` coverage;
- all stronger repository/service/window/refactored-code ratchets encoded in CI;
- exact SHA-256-locked runtime/development dependency graphs;
- `pip check` plus strict runtime/development `pip-audit`;
- CycloneDX runtime SBOM generation;
- offline validation of the bundled IEEE MA-L registry and provenance metadata;
- Network Intelligence benchmark smoke;
- the Network Intelligence structural typing ratchet;
- Ruff check and format validation;
- pinned Nerva staging and capability verification;
- pinned Tailcat staging and real CLI contract verification when Secure Transfer support is present;
- pinned Trippy staging, executable-hash revalidation and consumed-CLI contract verification when Network Path Analyzer support is present;
- PyInstaller packaging;
- packaged Nerva/Tailcat/Trippy verification for source that includes those native components;
- frozen application smoke;
- ZIP/checksum generation, including common native-runtime contract verification;
- Inno Setup generation;
- installed-application lifecycle smoke; and
- validated artifact upload.

A source-test pass is not sufficient on its own. Grouped CI coverage ratchets fail immediately on native-command errors, preventing an individual floor failure from being masked by a later successful PowerShell command.

A release must repeat the Release workflow against the exact immutable release commit; a previous CI artifact is supporting evidence, not a substitute for the release run.

## Functional milestone completed

The current platform includes persistent Network Intelligence inventory/identity reconciliation, classification confidence, relationships/topology/physical evidence, contextual Security Score, deterministic snapshot reporting, offline snapshot comparison, Security Score History, opt-in scheduled checks, automatic snapshots, local change notifications, History Center/trends/configurable retention and a reproducible build-time IEEE OUI registry updater.

Service Intelligence v2 extends the pinned Nerva integration with intentionally separated capabilities:

- normal TCP service identification remains explicit and operates on known-open ports;
- bounded explicit UDP probing preserves UDP uncertainty instead of interpreting silence as closed;
- Nerva `--misconfigs` is available only through a separate explicit **Check insecure configurations** action;
- SCTP is modeled as an advanced capability, but Nerva v1.69.4 restricts SCTP to Linux, so the validated Windows application truthfully disables/refuses that mode;
- normalized security findings retain id/severity/title/description/impact/recommendation/CVSS/evidence;
- UDP/SCTP observations are transport-qualified and cannot collide with the legacy TCP port inventory;
- findings and service observations produce explicit timeline evidence without automatically rewriting asset classification or `RiskLevel`;
- persisted findings can affect the Network Security Score only through deterministic bounded rules: critical `-12`, high `-8`, medium `-4`, low `-1`, info/unknown `0`, capped at **20 points per asset**.

Network Intelligence also persists a configurable fingerprint policy: Disabled, Manual only, Automatic after discovery, or Only assets with known changes. Automatic policies run between successful discovery persistence and snapshot publication, but are deliberately constrained to known TCP ports with maximum 32 assets, 16 ports per asset, 8 Nerva workers, 2 host connections and a 1500 ms probe timeout. Scheduled execution never enables `--misconfigs`, UDP or SCTP.

Web Recon adds a first-party explicit-target HTTP/HTTPS/DNS reconnaissance domain. It starts from one URL or hostname, does not accept CIDR/range scope and keeps DNS/TLS/HTTP/discovery behavior behind bounded first-party components instead of turning a web audit into internet-wide discovery.

Secure Transfer adds a replaceable Tailcat-backed transport boundary for text/file/folder transfer, temporary secure tunnels and localhost-only port forwarding. Tailcat is pinned and verified at build time; PythonKni does not implement its unstable wire format, does not modify routing/DNS, does not save transport keys and does not expose PythonKni-created `0.0.0.0` forwards. File/folder send requires the Windows OpenSSH `scp.exe` capability. See [`secure-transfer.md`](secure-transfer.md).

Network Traffic Monitor adds passive local Windows temporal telemetry while deliberately remaining separate from Network Intelligence persistence:

- exact interface RX/TX rates are derived from interface counters;
- TCP/UDP socket ownership is attributed to PID/process where Windows exposes it;
- process rows are socket activity, not fabricated per-process byte counters;
- reverse DNS is bounded and RIPEstat ASN/prefix enrichment is opt-in;
- deterministic temporal observations are published into the canonical Network Intelligence notification/history pipeline;
- known-asset joins are read-only and cannot synthesize assets or rewrite classification/`RiskLevel`;
- packet capture is a separate explicit local `pktmon` action with ETL -> PCAPNG conversion;
- no packet injection, credential/default-password attempts, exploitation, payload decryption or internet-wide discovery are introduced.

See [`network-traffic-monitor.md`](network-traffic-monitor.md) and [`network-monitor-intelligence-integration.md`](network-monitor-intelligence-integration.md).

Network Path Analyzer adds explicit-target path diagnostics through a pinned Trippy backend while keeping PythonKni's analysis semantics first-party:

- one hostname/IP target only; CIDR/range/list/URL inputs are rejected;
- ICMP, UDP and TCP path tracing with bounded interval and max TTL;
- IPv4/IPv6-aware execution through the system resolver;
- rolling per-hop response/RTT/jitter statistics and destination RTT history;
- conservative stable-route comparison with repeated confirmation before route-change events;
- destination-only `packet_loss` semantics so an intermediate router that rate-limits diagnostic replies is not mislabeled as forwarding loss;
- repeated destination misses before `destination_unreachable`;
- rolling-baseline `latency_spike` detection plus a separately explainable first sustained RTT-step indicator;
- canonical temporal publication for `route_changed`, `latency_spike`, `packet_loss`, `hop_added`, `hop_removed` and `destination_unreachable`;
- no synthetic Network Intelligence asset creation or silent risk/classification rewrite.

The Windows implementation reports Trippy's Administrator/raw-socket requirement explicitly. See [`network-path-analyzer.md`](network-path-analyzer.md).

The quality/toolchain milestone also includes the CPython 3.13.15 runtime contract, incremental Network Intelligence structural typing ratchet, first-class per-user Windows installer pipeline and reproducible native-component staging/packaging contracts.

## Network temporal integration gate

A temporal network candidate is not complete merely because its focused tests pass. Network Traffic Monitor and Network Path Analyzer must coexist with the **current** application tree, including Web Recon, Secure Transfer and the Nerva/Tailcat/Trippy packaging and installer paths.

Before merge, the candidate must therefore pass the entire CI contract described above on the reconciled PR head. Path Analyzer additionally must prove transient silent intermediate hops do not create false destination-loss/route-removal events and that Trippy's exact consumed CLI surface still matches the pinned backend. After merge, the resulting `main` commit must pass repository CI again.

## Release workflow contract

`.github/workflows/release.yml` supports three controlled entry points that resolve to the same immutable `vX.Y.Z` release identity:

1. a direct tag matching exact `vX.Y.Z` syntax;
2. a bootstrap branch matching exact `release/vX.Y.Z` syntax; or
3. a recovery branch matching exact `release-retry/vX.Y.Z` syntax for retrying publication of an already-existing immutable tag.

Every path requires the resolved release commit to be contained in `main`, and the checked-out release source must declare the same version in `pyproject.toml` as the resolved tag.

The bootstrap branch path is deliberately stricter:

- it must point to the **current tip of `main`** when the Release workflow starts;
- its tag name must match the current `project.version` **before any tag is created**;
- if the tag does not yet exist, the workflow creates it at that exact SHA using the repository-scoped GitHub token;
- if the tag already exists at the same SHA, the workflow is idempotent and continues;
- if the tag already exists at a different SHA, the workflow fails and **never moves or rewrites the existing tag**.

The recovery branch path is also deliberately constrained:

- it must point to the **current tip of `main`**, so recovery logic always comes from reviewed current workflow code;
- the requested `vX.Y.Z` tag must already exist;
- the existing tag must resolve to a commit contained in `main`;
- the workflow then checks out that **exact tagged commit in detached HEAD state** and verifies its `project.version` before installing, testing, building or publishing anything;
- recovery therefore repairs publication without moving the immutable tag or silently rebuilding a different source revision.

Historical recovery has compatibility rules for later distribution milestones. If an immutable old tag predates installer, Nerva, Tailcat or Trippy support, recovery republishes only the assets and runtime contents supported by that tagged source. It never injects current installer/native-component code or binaries into old immutable source. New direct/bootstrap releases require the corresponding support files to be present.

After resolving and checking out the release source, the same workflow must:

1. install both committed dependency locks with `--require-hashes`;
2. validate locks, `pip check`, runtime/dev audits and CycloneDX SBOM;
3. compile source and validate the bundled OUI registry offline;
4. run the full test suite and coverage ratchets;
5. enforce the Network Intelligence structural typing ratchet;
6. run Ruff check/format;
7. stage/verify the exact pinned native Nerva/Tailcat/Trippy components supported by that source;
8. build with PyInstaller, verify packaged native components and run the frozen smoke test;
9. package the versioned Windows ZIP + SHA-256 checksum, refusing a declared native runtime that is missing or fails its packaged contract;
10. for installer-enabled source, build the version-bound Inno Setup installer and run the installed-app lifecycle smoke;
11. upload retained workflow artifacts; and
12. publish/update the GitHub Release with the validated files.

The publication probe is intentionally compatible with the Windows PowerShell runner: a missing GitHub Release is treated as the expected create path rather than as a terminating native-command error. Existing releases use an idempotent asset upload with `--clobber`; missing releases are created with `--verify-tag`.

The release is complete only after the Release workflow conclusion is `success`, the immutable tag resolves to the intended `main` commit and the GitHub Release assets are present for that exact tag.

## Expected release assets

For current installer/native-component-enabled source, future releases publish:

```text
PythonKni-vX.Y.Z-windows-x64.zip
PythonKni-vX.Y.Z-windows-x64.sha256
PythonKni-vX.Y.Z-windows-x64-setup.exe
PythonKni-vX.Y.Z-windows-x64-setup.sha256
dependency-sbom.cdx.json
network_oui_prefixes.meta.json
requirements.txt
requirements-dev.txt
```

Nerva, Tailcat and Trippy are embedded inside the validated Windows application bundle rather than published as independent PythonKni release assets. Retained workflow evidence includes `coverage.xml`, benchmark JSON and the exact native lock/provenance files supported by that source. The historical `v0.1.0` release predates installer/Nerva/Tailcat/Trippy support and therefore correctly retains only the assets produced by that historical source.

## Nerva distribution and capability contract

`third_party/nerva.lock.json` pins Nerva `v1.69.4` for Windows amd64 and SHA-256:

```text
59e59eb54c8c5c581031387a0aa23c98983db94301e811f3c9b1802a05fc97f7
```

`scripts/fetch_nerva.ps1` downloads only that exact upstream archive during explicit build/CI/release preparation, verifies the digest before extraction and requires the upstream Apache-2.0 license. Normal application runtime does not download or update Nerva.

PyInstaller packages the staged engine, license and provenance. CI/release execute the packaged `nerva.exe --capabilities` before accepting the Windows bundle.

The application does not assume every Nerva capability is portable across operating systems. The validated Windows Nerva binary is used for TCP, UDP and explicit misconfiguration checks. SCTP is capability-gated because the pinned upstream release restricts it to Linux. Scheduled Network Intelligence fingerprinting is intentionally narrower than the engine: TCP-only known ports and no misconfiguration probes.

See [`network-service-fingerprinting.md`](network-service-fingerprinting.md).

## Tailcat distribution and capability contract

`third_party/tailcat.lock.json` pins Tailcat **v0.5.0** for Windows amd64 and the official release archive SHA-256:

```text
47c2a22eff596dc184642779b8ba9988ca554b0f177ee1188bc4913253b18430
```

`scripts/fetch_tailcat.ps1` stages only that locked release, verifies the official archive digest, records/verifies the staged executable digest and runs `scripts/check_tailcat_contract.ps1` against the real CLI before the transport is accepted. The contract smoke verifies the expected version and the embedded upstream command surface required by PythonKni.

Secure Transfer also checks the supported Tailcat runtime version before operations. This exact pin is intentional because Tailcat does not promise CLI/API/wire-format stability. See [`secure-transfer.md`](secure-transfer.md).

## Trippy distribution and capability contract

`third_party/trippy.lock.json` pins Trippy **0.13.0** for `x86_64-pc-windows-msvc` and the official release archive SHA-256:

```text
74a184434d96eec6c7f8e4b467147c40fa8841fa3722a3ddf51267208fcbbbe6
```

`scripts/fetch_trippy.ps1` downloads only the official `fujiapple852/trippy` GitHub Release archive, verifies the archive digest before extraction, requires `trip.exe` plus the upstream license and records the extracted executable SHA-256 in staged provenance metadata. Reuse of an already-staged backend requires both the executable digest and `scripts/check_trippy_contract.ps1` to pass again.

The CLI contract verifies exact version `0.13.0` and every option PythonKni consumes for deterministic reporting: JSON mode/report cycles, ICMP/UDP/TCP protocol choice, address family, system DNS method, max TTL, target port, multipath strategy and round-duration controls. PythonKni never feeds arbitrary user-supplied Trippy arguments and does not parse/embed the TUI.

PyInstaller packages the verified runtime and the common Windows bundle packager re-runs the packaged contract before ZIP creation. See [`network-path-analyzer.md`](network-path-analyzer.md).

## Installer contract

The installer is built with Inno Setup as a **per-user** package with `PrivilegesRequired=lowest`. Its default program directory is `%LOCALAPPDATA%\Programs\PythonKni`, it creates a Start Menu entry and uses the standard Inno Setup uninstaller.

The build script reads the application version from `pyproject.toml`; Release builds additionally require that version to match the resolved immutable release tag. CI never downloads Chocolatey packages, installer compilers or third-party Actions to construct the setup executable: it uses the Inno Setup compiler already present on the Windows runner and fails if that compiler is unavailable.

The installed-app smoke uses an isolated temporary target, verifies Start Menu and per-user uninstall registration, executes the **installed** `PythonKni.exe --smoke-test`, uninstalls silently and verifies cleanup. The smoke refuses to run if PythonKni is already registered as installed for the current user so local validation cannot silently replace a real installation.

See [`windows-installer.md`](windows-installer.md) for the installation, checksum and uninstall contract.

## Known distribution limitations

These do not block the current technical distribution model, but remain explicit:

- Windows is the only packaged/validated platform;
- SCTP service fingerprinting is not available in that Windows package because Nerva v1.69.4 exposes SCTP only on Linux;
- Tailcat is an upstream experimental transport with no stability promise for its CLI/API/wire format; public DERP relays are fallback infrastructure with rate limits/no PythonKni SLA;
- Secure Transfer file/folder sending depends on Windows OpenSSH `scp.exe` being available;
- Network Traffic Monitor visibility depends on Windows permissions, socket lifetime, adapter counters and OS telemetry; lack of an observation is not proof that traffic did not exist;
- Network Path Analyzer requires Administrator privileges on Windows for Trippy's raw-socket tracing modes; an intermediate hop that does not answer diagnostic probes is not evidence by itself of forwarding loss, and a destination may filter one chosen trace protocol while remaining otherwise reachable;
- the executable and installer are not yet Authenticode/code signed, so Windows SmartScreen/reputation warnings remain possible;
- Python 3.14+, free-threaded CPython and non-Windows packaging are not claimed;
- optional OCR workflows still depend on local Tesseract/Poppler;
- localization is incomplete.

## Post-v0.1.0 distribution roadmap

1. add representative screenshots/demo media;
2. define certificate ownership, identity and secret handling for Authenticode signing;
3. sign the executable/installer once that policy is established;
4. keep dependency/OUI/runtime/typing/installer/Nerva/Tailcat/Trippy/Web Recon/Network Monitor/Network Path gates non-regressive while product features evolve.
