# Changelog

All notable changes to PythonKni are documented in this file.

The project has not published a tagged release for the work below yet, so the current development cycle remains under **Unreleased**.

## Unreleased

### Added

- Added a reusable background `Worker` with progress, result, error and cooperative-cancellation signals, and moved long PDF, converter, process/VirusTotal and other blocking operations away from the GUI thread. (PR #5)
- Added a common `BaseTool` contract for all GUI tools, including validated `name`, `description`, `category` metadata and a required `setup_ui()` implementation. (PR #6)
- Added broad `pytest-qt` coverage for real Qt windows, loader behavior, worker cancellation, configuration, archives, Event Viewer, Disk Analyzer and System Report. (PR #7)
- Added real IPv4 interface/netmask discovery, manual CIDR overrides, bounded network/port scanning concurrency and service-name reporting. (PR #8)
- Added a staged duplicate-detection pipeline using file size, BLAKE2b sampling, SHA-256 and final byte-for-byte verification. (PR #10)
- Added atomic JSON restoration manifests for moved duplicate files, including original/destination paths, retained original, hash, size and operation status. (PR #10)
- Added the `pythonkni/` domain package and framework-independent cooperative task primitives in `pythonkni/core/tasks.py`. (PR #12)
- Added a packaged-application `--smoke-test` mode that validates dynamic plugin discovery, tool contracts and required bundled assets without starting the normal Qt event loop. (PR #13)
- Added explicit managed-worker registration through `BaseTool.manage_worker()` / `start_managed_worker()` while retaining compatibility with legacy QThread attributes. (PR #14)
- Added shared spreadsheet-safe CSV helpers used by Disk Analyzer, Network history, Startup Manager and Event Viewer exports. (PR #20)
- Added complete architecture-boundary tests covering every first-party domain and enforcing the `models <- service <- window <- adapter` dependency direction. (PR #24)
- Added regression coverage for legacy adapter exports and monkeypatch forwarding after the layered architecture migration and stricter Ruff cleanup. (PR #27)
- Added framework-independent shared infrastructure under `pythonkni/infrastructure/`, initially owning application paths plus ZIP/7Z validation, extraction safety, staging and publication primitives. (PR #34)
- Added `pytest-cov` branch-coverage reporting and CI coverage ratchets based on measured repository/service baselines. (PR #34)
- Added exact SHA-256-locked runtime/development dependency graphs, dependency-lock validation, strict audits, CycloneDX SBOM generation and weekly Dependabot checks. (PR #36)
- Added structured technical feedback that separates actionable primary text from expandable diagnostics. (PRs #39, #40)
- Added Camera Exposure Auditor for authorized local IPv4 scopes with bounded ONVIF/HTTP(S)/RTSP evidence and no credentials/media retrieval. (PR #43)
- Added Network Intelligence as a persistent local asset/exposure intelligence domain. (PR #44)
- Added persistent SQLite Asset Inventory, stable identity, timeline, Security Score and device-specific auditors. (PR #45)
- Added interactive logical Network Topology plus persisted relationship evidence and administrative physical-link import. (PRs #46-#49)
- Added conservative Network Explorer -> Camera Auditor `/32` handoff. (PR #50)
- Added deterministic Network Intelligence JSON/ZIP snapshot reporting. (PR #51)
- Added offline MAC OUI/vendor enrichment and retained classification/OUI benchmark smoke. (PR #52)
- Added deterministic Device Classification Confidence with persisted explainability signals and confidence-aware UI/report schema v2. (PR #53)
- Added offline comparison of previously exported Network Intelligence JSON/ZIP snapshots without reading live inventory or rescanning. (PR #55)
- Added bounded contextual Network Security Score prioritization for elevated-risk Router/NAS, confirmed default-gateway and confirmed physical-link context. (PR #57)
- Added offline Network Security Score History across validated saved snapshots. (PR #58)
- Added opt-in in-app scheduled Network Intelligence checks plus atomic automatic snapshots. (PR #59)
- Added a deterministic local Change Notification Engine and bounded read/unread inbox over consecutive automatic snapshots. (PR #60)
- Added History Center with per-scope/time filters, native Qt Security Score/high-risk trends, navigation/comparison and configurable safe retention. (PR #61)
- Added deterministic build/maintenance-time generation of the bundled OUI registry from the official IEEE MA-L source, provenance metadata and monthly/manual PR maintenance. (PR #62)
- Added an incremental AST-based Network Intelligence structural typing ratchet enforced by CI and Release. (PR #64)
- Added opt-in Nerva-backed TCP service fingerprinting for already-discovered open ports, with normalized first-party fingerprints, explicit Network Intelligence persistence/history integration and a dedicated fingerprint inventory UI. (PR #71)

### Changed

- Persisted configuration is loaded before application UI creation and saved atomically outside the repository.
- Network scanning uses deterministic interface selection, bounded pending work and explicit timeouts. (PR #9)
- Duplicate Finder excludes quarantine, skips symlinks/hardlinks and revalidates candidates before movement. (PRs #10, #17)
- Archive, converter, PDF, process, WiFi and other blocking workflows were moved to managed/background execution with cooperative cancellation where applicable. (PRs #17-#19)
- The first-party application was migrated to the layered `models.py <- service.py <- window.py <- tools adapter` structure. (PRs #12, #24)
- Ruff enforcement expanded to Pyflakes (`F`) plus import sorting (`I`). (PR #27)
- Runtime/history/log paths moved under the user profile; VirusTotal configuration uses `VIRUSTOTAL_API_KEY`.
- PDF reading/writing migrated from deprecated `PyPDF2` to maintained `pypdf`. (PR #36)
- CI/release install committed dependency graphs with `pip --require-hashes`, audit both graphs and publish dependency evidence. (PR #36)
- GitHub Actions are pinned to immutable commit SHAs. (PR #36)
- CI/release repository branch-coverage ratchet reached **92.5%** while aggregate service floor remains **93.0%**, with stronger per-module presentation/service floors. (PR #42)
- Network Intelligence snapshot reports use schema version 2 with confidence signals. (PR #53)
- Existing Network Intelligence inventories migrate in place while active provisional IP identities can reconcile transactionally to canonical MAC identities; ambiguous DHCP reuse remains separate. (PR #54)
- The bundled OUI dataset moved from a small curated snapshot to a reproducibly generated official IEEE MA-L snapshot containing 40,046 unique assignments and provenance/hash metadata; runtime lookup remains fully offline. (PR #62)
- The canonical supported runtime moved from CPython 3.10.11 / Python >=3.10 to **CPython 3.13.15** with source/runtime range `>=3.13,<3.14`, Ruff `py313` and aligned OUI maintenance. (PR #63)
- CI and installer packaging now stage the exact pinned Nerva Windows engine, verify its SHA-256/provenance contract, bundle its Apache-2.0 notice and validate the packaged engine before distribution; coverage ratchet command groups also fail fast on native-command errors. (PR #71)

### Fixed

- Startup Manager registry/startup-folder operations are transactional and refuse unsafe overwrites. (PR #2)
- Process termination requires confirmation, protects PythonKni itself/system processes and revalidates PID identity immediately before mutation. (PRs #4, #34)
- Closing tools with active work no longer destroys running QThreads; managed-worker lifecycle/deferred-close behavior is centralized. (PR #14)
- Event Viewer drains/reaps `wevtutil` consistently on success, cancellation and timeout. (PR #15)
- Duplicate scans/moves reject unsafe concurrency and record partial cancellation state. (PR #16)
- Fatal tool-discovery/configuration persistence errors are surfaced without silently applying invalid state. (PRs #21, #22)
- Removed vulnerable `setuptools 80.10.2` after the audit gate detected `PYSEC-2026-3447`; the lock resolves to patched `setuptools 84.0.0`. (PR #36)
- Network Intelligence identity reconciliation prevents false active IP/MAC duplicates while preserving DHCP-safe ambiguity. (PR #54)

### Security

- ZIP/7Z extraction validates members against traversal, unsafe Windows paths, links/special files and decompression/path limits before publishing staged output. (PR #11)
- Duplicate identity requires final byte equality and revalidation; hardlinks are not treated as reclaimable duplicates. (PRs #10, #17)
- CSV exports neutralize spreadsheet formula-injection prefixes. (PR #20)
- Temp Cleaner restricts destructive traversal to exact authorized roots, rejects links/reparse points/broad roots and revalidates directory identity around deletion. (PRs #21, #26)
- Process/startup destructive system changes use explicit protection/transaction controls. (PRs #2, #4)
- VirusTotal hashes executables locally and queries by SHA-256 rather than uploading executable contents. (PR #5)
- Runtime/development dependency graphs are exact-version/SHA-256 locked and audited; validated artifacts include CycloneDX SBOM evidence. (PR #36)
- Camera Auditor and Network Intelligence preserve authorized local/private scope boundaries with no credential/default-password attempts, no camera-content retrieval and no internet-wide discovery. (PRs #43-#64)
- Runtime OUI lookup remains fully offline; only explicit build/maintenance activity can contact the official IEEE source. (PR #62)
- Service fingerprinting remains an explicit post-discovery action over known-open TCP ports; the first milestone does not enable Nerva misconfiguration probes, credential behavior, UDP or SCTP scanning, and the runtime performs no third-party binary download. (PR #71)

### Testing and CI

- Qt tests run offscreen and cover real loader/window/worker behavior. (PR #7)
- Added focused network, duplicate, archive, worker, Temp Cleaner, process and architecture safety regressions across the hardening work. (PRs #8-#42)
- Packaged-application validation builds the real PyInstaller bundle and runs `PythonKni.exe --smoke-test`. (PR #13)
- CI validates compileall, the full pytest suite, Ruff, dependency integrity/audits, PyInstaller and frozen smoke before packaging.
- Branch coverage progressed from 58.85% / 289 tests to a presentation-hardened **92.9% / 686 tests**, then expanded through Network Intelligence while preserving a >=92.5% global ratchet. (PRs #34-#42)
- Network Intelligence/OUI work expanded the suite to 885 tests while aggregate service coverage reached 93.5%. (PRs #43-#52)
- OUI registry correctness/provenance validation is an offline CI/release gate and the benchmark JSON is retained with CI evidence. (PR #62)
- CPython 3.13.15 compatibility is regression-tested across CI, Release, maintenance workflow, project metadata and Ruff target. (PR #63)
- Network Intelligence typing regressions and the enforced structural ratchet bring the current suite to **1,060 tests**, **92.8% repository branch coverage** and **93.5% aggregate service coverage**. (PR #64)
- Nerva fingerprinting and distribution regressions expand the suite to **1,131 tests**, **93.0% repository branch coverage** and **93.5% aggregate service coverage**; CI validates the pinned engine before and after PyInstaller packaging and through the installed-app lifecycle smoke. (PR #71)

### Documentation

- Documented the plugin contract, layered architecture, runtime/usage/security boundaries and coverage-ratchet strategy through the application hardening work. (PRs #23-#42)
- Added and evolved `docs/network-intelligence.md` around inventory, identity, topology, reporting, confidence and contextual risk. (PRs #44-#57)
- Added dedicated documentation for snapshot comparison, Security Score History, scheduled monitoring, change notifications and History Center/retention. (PRs #55, #58-#61)
- Added official IEEE OUI source/provenance/maintenance documentation. (PR #62)
- Added the CPython 3.13 runtime support/migration contract. (PR #63)
- Added Network Intelligence structural typing metric/policy documentation. (PR #64)
- Synchronized README, architecture, usage, Network Intelligence, changelog and first-release readiness around the completed #55-#64 platform milestone.
- Added `docs/network-service-fingerprinting.md` and synchronized README/release readiness around the Nerva supply-chain, packaging, persistence and operational contract. (PR #71)

### Development cycle covered

This Unreleased section consolidates the major merged hardening/refactoring and Network Intelligence work from **PR #2 through PR #71** across the August-September 2026 development cycle. PR #1 was intentionally not merged and was superseded by later Temp Cleaner work; PR #56 was closed without merge and is not included in the release contents.
