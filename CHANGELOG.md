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
- Added `pytest-cov` branch-coverage reporting and CI coverage ratchets based on the measured repository/service baselines, with an 80% floor for the critical code refactored in PR #34. (PR #34)
- Added focused service regressions for Startup Manager registry/folder behavior, Event Viewer parsing/diagnostics/export and System Report collection/fallback paths. (PR #35)
- Added broad behavior-driven coverage for Archive, Converter, Network, PDF and Temp Cleaner services, including transactional output, cancellation, extraction limits, network fallbacks, PDF edge cases and safe cleanup branches. (PR #35)
- Added high-coverage Qt orchestration regressions for Startup Manager, Event Viewer and PDF Toolkit, covering workers, cancellation, validation, filters, dialogs, exports, selection state and error paths. (PR #35)
- Added separate direct-dependency policy files (`requirements.in`, `requirements-dev.in`) and exact transitive runtime/development locks containing SHA-256 hashes for every resolved package distribution. (PR #36)
- Added `scripts/check_dependency_locks.py` plus regressions that reject missing hashes, malformed SHA-256 values, non-exact pins, missing direct dependencies and direct versions outside the declared policy range. (PR #36)
- Added CycloneDX runtime SBOM generation and retention alongside Windows CI/release artifacts, plus weekly Dependabot checks for Python dependencies and GitHub Actions. (PR #36)
- Added `tools/ui_feedback.py`, a reusable Qt feedback renderer that keeps concise user-facing summaries separate from optional expandable technical diagnostics. (PR #39)
- Added domain-specific service regression suites for Disk Analyzer, WiFi, Process Manager and Duplicate Finder, covering real error, cancellation, identity, parsing and recovery paths without changing production service behavior. (PR #41)
- Added dedicated behavior-driven Qt regression suites for Converter, Network, System Report, Archive, Process Manager, Duplicate Finder, Disk Analyzer, Temp Cleaner, Config and WiFi, covering worker lifecycle, overlap rejection, stale/current callbacks, cancellation, deferred close, dialogs, import/export, confirmations and technical-error paths without changing production behavior. (PR #42)
- Added Camera Exposure Auditor for authorized local IPv4 scopes, with bounded ONVIF discovery, HTTP/HTTPS/RTSP exposure evidence, conservative risk reporting, JSON/CSV export and single-host handoff support without credentials or media retrieval. (PR #43)
- Added Network Intelligence as a first-class domain that reuses bounded discovery and camera evidence to classify local PCs, routers, printers, NAS devices, cameras and unknown assets with explainable evidence. (PR #44)
- Added a persistent SQLite Asset Inventory with stable MAC-first identity, first/last-seen timestamps, online/offline state, change timeline, explainable Network Security Score and snapshot-based device-specific auditors. (PR #45)
- Added an interactive logical Network Topology projected from persisted inventory without triggering a second network scan. (PR #46)
- Added persistent relationship evidence with explicit confirmed/inferred/unknown confidence, local default-route evidence and topology edge explanations. (PR #47)
- Added import-driven physical-network evidence for LLDP/MAC-table snapshots, including physical link metadata, confidence and transactional persistence without switch probing or credential attempts. (PRs #48, #49)
- Added a conservative Network Explorer to Camera Exposure Auditor handoff that requires a current persisted Camera identity match and opens only the exact `/32` host. (PR #50)
- Added deterministic Network Intelligence snapshot reporting as JSON or ZIP evidence bundles containing inventory, relationships, timeline and security-score data with spreadsheet-safe CSV serialization. (PR #51)
- Added fully offline MAC OUI/vendor enrichment using a bundled curated registry, privacy-aware MAC validation and conservative manufacturer-assisted classification without third-party lookups. (PR #52)
- Added a reproducible Network Intelligence OUI benchmark smoke that records lookup throughput as a retained CI artifact while keeping correctness, rather than shared-runner timing, as the gate. (PR #52)
- Added deterministic `0..100` Device Classification Confidence with explicit LOW/MEDIUM/HIGH bands and persisted weighted matched/unmatched signals, keeping classification certainty separate from security risk. (PR #53)
- Added a confidence-aware Network Intelligence presentation layer that exposes the score and contributing evidence in Asset Inventory and Device Profile without changing the underlying conservative device-type precedence. (PR #53)

### Changed

- Persisted configuration is loaded before the application UI is created; theme and language now use one canonical runtime configuration path, including migration of legacy `Ingles` values to `Inglés`. (PR #3)
- Network scanning now chooses the default interface using the IPv4 address selected by the operating-system routing table, falls back deterministically, validates real ping replies, bounds pending futures and applies a reverse-DNS timeout. (PR #9)
- Duplicate Finder now excludes its quarantine directory, skips symlinks, ignores hardlinks by physical file identity and revalidates duplicates immediately before moving them. (PRs #10, #17)
- Archive creation and extraction now run through managed background workers with progress reporting, cooperative cancellation, busy-state controls and cleanup of incomplete staging output. (PR #19)
- Process Manager CPU sampling now uses two non-blocking samples around one shared cancellation-aware sampling window instead of waiting per process. (PR #19)
- File-converter outputs are staged and published transactionally; PDF-to-image and folder TXT/KML conversions use all-or-nothing publication with rollback and preservation of pre-existing destinations. (PR #18)
- Converter results now distinguish successful outputs, warnings and failures instead of showing unconditional success messages. (PR #18)
- WiFi profile loading moved out of `setup_ui()` into a managed worker with refresh/cancel state and explicit `netsh` timeouts. (PR #17)
- Each WiFi profile is exported into an isolated temporary directory and matched to the correct XML profile before reading its key material. (PR #17)
- The entire first-party application has been migrated to a uniform layered architecture: `models.py <- service.py <- window.py <- tools/*_tool.py adapter`. (PRs #12, #24)
- `tools/*_tool.py` modules are now thin dynamic-loader / legacy-compatibility adapters rather than the primary home of business logic. (PR #24)
- Legacy adapter reads, writes, exports and test monkeypatch behavior are preserved by forwarding compatibility hooks to the separated domain service/window modules. (PRs #24, #27)
- Ruff enforcement was expanded from a minimal critical-error subset to full Pyflakes (`F`) plus import sorting (`I`), with the repository baseline cleaned to satisfy the stricter rules. (PR #27)
- Runtime configuration, history and logs are stored outside the repository under the user profile instead of beside source files.
- VirusTotal configuration uses the `VIRUSTOTAL_API_KEY` environment variable instead of a source-code secret.
- Runtime/development dependencies and OCR requirements were completed and normalized, including the canonical `requirements.txt` path.
- Archive services now consume `pythonkni.infrastructure.archives` directly; `tools.zip_7zip_utils` remains only as a legacy/UI compatibility facade with monkeypatch forwarding. (PR #34)
- Application filesystem paths now live in `pythonkni.infrastructure.paths`; `tools.app_paths` is retained as a compatibility alias. (PR #34)
- Configuration normalization/atomic persistence remains in framework-independent `config.service`, while theme/language manager integration moved to `config.runtime`. (PR #34)
- Process Manager presentation now delegates process lookup/termination to its service instead of importing `psutil` and performing operating-system mutations from the window. (PR #34)
- Raised CI/release coverage ratchets to **84.0% repository-wide** and **91.0% across services**, with individual non-regression gates for the reinforced services and Startup/Event Viewer/PDF windows. (PR #35)
- Migrated first-party PDF reading/writing from deprecated `PyPDF2` to maintained `pypdf`, including the modern merge API, PDF regressions and PyInstaller collection metadata. (PR #36)
- Aligned the supported Python contract to **Python >=3.10** with Windows / CPython **3.10.11** as the canonical CI and release environment instead of retaining a partial legacy Python 3.8 claim. (PR #36)
- CI and release now install the committed dependency graphs with `pip --require-hashes`, validate the resulting graph with `pip check`, and publish both dependency locks with validated build/release artifacts. (PR #36)
- GitHub Actions used by CI/release are pinned to immutable commit SHAs rather than mutable version tags. (PR #36)
- Tool-loader failures, configuration persistence failures, Archive worker failures and Process Manager refresh/VirusTotal worker failures now show actionable primary text while preserving exception/diagnostic data in expandable details. Domain confirmations and business-specific warnings remain unchanged. (PR #39)
- Completed the structured technical-feedback migration across the remaining first-party windows, keeping actionable primary text separate from expandable diagnostics while preserving explicit validation, confirmation and domain-warning flows. (PR #40)
- Raised CI/release coverage ratchets to **86.0% repository-wide** and **93.0% across services**, added dedicated floors for Disk Analyzer, Duplicate Finder, Process Manager and WiFi, and raised the Process/config/infrastructure aggregate floor to **88.5%**. (PR #41)
- Raised the repository-wide CI/release branch-coverage ratchet to **92.5%** and expanded presentation non-regression floors to 13 first-party windows while keeping the service-layer floor at **93.0%**. (PR #42)
- Network Intelligence snapshot reports now use schema version 2 and include classification confidence level plus structured signal contributions in JSON and spreadsheet-safe CSV output. (PR #53)
- Existing Network Intelligence SQLite databases are migrated in place with neutral confidence defaults so previously persisted assets and timeline history remain intact. (PR #53)

### Fixed

- Startup Manager registry and startup-folder enable/disable operations are transactional, with backups, rollback and explicit failure handling when both the primary operation and rollback fail. (PR #2)
- Startup Manager refuses to overwrite a Run value that reappeared while an entry was disabled and commits disabled-folder metadata atomically. (PR #2)
- Process Manager now requires confirmation before terminating a process, blocks PythonKni from terminating itself, applies a second confirmation to likely system processes and aborts on process-identity changes that could indicate PID reuse. (PR #4)
- Closing tools with active background work no longer destroys running QThreads: worker discovery, cooperative cancellation, bounded waiting and deferred close handling are centralized in `BaseTool`. (PR #14)
- Event Viewer now drains `wevtutil` stdout/stderr while the child process is running, avoiding pipe-buffer deadlocks and false timeouts on large RenderedXml responses. (PR #15)
- Event Viewer child processes are killed, drained and reaped consistently on cancellation, timeout and communication failures. (PR #15)
- Duplicate scans/moves reject concurrent replacement workers, perform filesystem moves in the background and record partial move counts when cancellation interrupts a move. (PR #16)
- Process Manager now keeps every overlapping refresh and VirusTotal-analysis worker managed until its native QThread has finished, and ignores stale refresh callbacks that could overwrite newer UI state. (PR #25)
- Fatal tool-discovery errors such as directory enumeration/permission failures now leave the loading state, are logged and surface a persistent loader failure instead of silently killing the loader thread. (PR #22)
- Configuration persistence now writes through a same-directory temporary file with flush, `fsync` and atomic `os.replace()`, preserving the previous valid configuration on failure. (PR #21)
- Configuration save errors are surfaced to the UI without applying theme/language state that failed to persist. (PR #21)
- Process termination now revalidates PID liveness and `create_time` inside the service immediately before `terminate()`, keeping PID-reuse protection adjacent to the destructive OS operation. (PR #34)
- Removed vulnerable `setuptools 80.10.2` from the development lock after the new audit gate detected `PYSEC-2026-3447`; the policy now resolves to patched `setuptools 84.0.0` rather than suppressing the advisory. (PR #36)
- Network Intelligence now promotes an active IP fallback to the canonical MAC identity in one transaction, preserving first-seen history and rewriting timeline/relationship references instead of creating a duplicate asset. Legacy duplicates are repaired only with corroborated transition evidence, so ambiguous offline IP reuse remains separate for DHCP safety. (PR #54)

### Security

- ZIP and 7Z extraction now validates archive members before extraction, rejecting path traversal, absolute/UNC paths, ambiguous Windows paths, ADS/device names, symbolic links and special files. (PR #11)
- Archive extraction enforces entry-count, per-file, total-uncompressed-size, path depth/length and suspicious compression-ratio limits, verifies actual extracted data and publishes only a verified staging tree. (PR #11)
- Duplicate files are not trusted solely because hashes match: final byte equality is required and duplicate identity is revalidated before each move. (PR #10)
- Hardlinks are ignored during duplicate discovery/movement so multiple directory entries for the same physical file are not treated as reclaimable duplicate data. (PR #17)
- CSV exports neutralize formula-injection prefixes (`=`, `+`, `-`, `@`), including leading whitespace/tab bypasses, while preserving non-string numeric values. (PR #20)
- Temp Cleaner now separates broad location containers from exact authorized cleanup targets and rejects dangerous roots such as the user home, filesystem anchors, `LOCALAPPDATA`, `SystemRoot` and TEMP/TMP parent directories. (PR #21)
- Temp Cleaner rejects empty/relative environment paths, symlink/reparse components and unapproved paths, and only permits exact known cleanup targets. (PRs #21, #26)
- Temp Cleaner destructive traversal uses `lstat()`/`scandir()` without following links or junctions, removes links themselves, avoids recursive `shutil.rmtree()` and deliberately fails closed when new/replaced directory content appears. (PR #26)
- Temp Cleaner records directory identity with `(st_dev, st_ino)` and revalidates root/subdirectory identity around destructive operations to reduce path-replacement/TOCTOU risk. (PR #26)
- Temp Cleaner preview follows the same no-link traversal rules, and Windows CI includes a real NTFS junction regression test. (PR #26)
- Process termination and startup-management operations gained explicit protection/transaction controls for destructive system changes. (PRs #2, #4)
- VirusTotal analysis hashes executables locally and queries by SHA-256 rather than uploading executable contents; the API key is read from the environment. (PR #5 and configuration hardening)
- Runtime and development dependency graphs are exact-version/SHA-256 locked; CI/release reject unapproved package artifacts through `pip --require-hashes`. (PR #36)
- Both Python dependency locks are audited with strict `pip-audit` gates, so known advisories fail validation; the runtime SBOM is generated in CycloneDX JSON format. (PR #36)
- Dependency integrity tests, action SHA pinning and weekly Dependabot checks add non-regression controls around the project supply chain. (PR #36)

### Testing and CI

- Qt tests run offscreen in CI using `pytest-qt`, covering real menu/plugin loading, window state, workers and tool-specific GUI behavior. (PR #7)
- Added focused regressions for network CIDR validation, interface selection, cancellation, ARP parsing, reverse-DNS timeouts, bounded future queues and partial cancelled results. (PRs #8, #9)
- Added duplicate regressions for staged hashing, forced hash collisions, symlink/hardlink handling, stale revalidation, restoration manifests, cancellation and background movement. (PRs #10, #16, #17)
- Added archive regressions for ZIP/7Z traversal hazards, Windows path edge cases, symlinks/special files, decompression limits, cancellation, progress and staging cleanup. (PRs #11, #19)
- Added architecture tests that prevent models/services from importing forbidden Qt/window/tool dependencies and require all first-party domains to preserve the layered structure. (PRs #12, #24)
- Added packaged-application validation to Windows CI: PyInstaller builds the real bundle and CI executes `dist\\PythonKni\\PythonKni.exe --smoke-test`. (PR #13)
- Added worker-lifecycle regressions covering close behavior, overlapping Process Manager refreshes, Event Viewer subprocess cleanup, WiFi background loading and managed analysis workers. (PRs #14, #15, #17, #25)
- Added Temp Cleaner regressions for broad-root rejection, unsafe environment paths, symlink files/directories, Windows junctions and root/subdirectory replacement during traversal. (PRs #21, #26)
- CI now validates `compileall`, the full pytest suite, Ruff `F + I`, Ruff formatting, the Windows PyInstaller bundle and the frozen-application smoke test before changes are merged. (PRs #13, #27)
- Added service-level Process Manager regressions for own-process rejection, unavailable processes, process identity reuse and delegated termination, while UI tests now focus on confirmation/orchestration. (PR #34)
- Added architecture regressions requiring shared infrastructure to remain PyQt/`tools` independent and preventing `psutil` from returning to `process_manager/window.py`. (PR #34)
- Measured the first full `pythonkni` + `tools` branch-coverage baseline at 58.85% with 289/289 tests passing; CI established non-regression ratchets of 58.8% repository-wide, 64.7% across services and 80% across the critical code refactored in PR #34. (PR #34)
- Coverage XML is preserved alongside validated Windows CI/release artifacts so subsequent coverage work has a machine-readable baseline. (PR #34)
- Expanded the suite from **289 to 530 tests**, raising measured branch coverage from **58.85% to 84.6% repository-wide** and from **64.7% to 91.5% across all `service.py` modules**. (PR #35)
- Archive, Converter, Network, PDF and Temp Cleaner services now measure **95.7%**, **94.5%**, **96.7%**, **95.3%** and **86.4%** respectively; Startup, Event Viewer and System Report remain at **87.7%**, **95.4%** and **97.2%**. (PR #35)
- Startup, Event Viewer and PDF windows now measure **95.8%**, **98.9%** and **93.4%**, with dedicated CI/release non-regression gates. (PR #35)
- Repository/service ratchets now enforce **84.0% / 91.0%**, while priority-module gates preserve the stronger coverage reached by the reinforced services and Qt windows. (PR #35)
- Expanded the suite to **535 tests** with PDF migration/dependency-lock regressions while preserving the established **84.6% repository-wide / 91.5% service-layer** application coverage baseline. (PR #36)
- The canonical Windows pipeline now validates hash-locked installation, lock structure, `pip check`, runtime/development vulnerability audits and SBOM generation before compile/test/lint/build/smoke/package stages. (PR #36)
- Expanded the suite to **545 tests** for structured feedback behavior, raising repository-wide branch coverage to **84.7%** while preserving **91.5%** service-layer coverage. Archive, Config and Process Manager windows now measure **70.2%**, **85.0%** and **74.6%** respectively, and the shared feedback helper measures **80.0%**. (PR #39)
- Completed the structured-feedback coverage tranche at **555 tests** and **85.6% repository-wide branch coverage**, while preserving **91.5% aggregate service coverage** and validating the complete migrated window set through the frozen Windows bundle. (PR #40)
- Expanded the suite from **555 to 578 tests**, raising repository-wide branch coverage from **85.6% to 86.4%** and aggregate service coverage from **91.5% to 93.2%**. Disk Analyzer now measures **95.0%**, Duplicate **90.5%**, Process Manager **99.3%** and WiFi **96.0%**. (PR #41)
- Expanded the suite from **578 to 686 tests**, raising repository-wide branch coverage from **86.4% to 92.9%** while preserving **93.2% aggregate service coverage**. Presentation coverage now measures Archive **97.2%**, Config **90.7%**, Converter **86.9%**, Disk Analyzer **96.9%**, Duplicate Finder **97.4%**, Event Viewer **98.9%**, Network **91.5%**, PDF **93.1%**, Process Manager **98.0%**, Startup **95.3%**, System Report **94.7%**, Temp Cleaner **94.2%** and WiFi **95.0%**. (PR #42)
- Expanded the Network Intelligence stack regression suite to **885 tests**, preserving **92.9% repository-wide branch coverage** and raising aggregate service coverage to **93.5%** on the validated OUI integration candidate. (PRs #43-#52)
- The Windows CI pipeline now runs and retains the Network Intelligence OUI benchmark smoke alongside coverage, SBOM, checksum and packaged application artifacts. (PR #52)
- Extended the retained Network Intelligence benchmark smoke to measure deterministic classification-scoring throughput as well as offline OUI lookup throughput, while keeping shared-runner timing informational rather than a pass/fail threshold. (PR #53)
- Added focused identity-reconciliation regressions for active MAC promotion, completed-scan continuity, timeline/relationship rewriting, relationship collisions, legacy duplicate repair and DHCP-safe non-merges. (PR #54)

### Documentation

- Documented the actual plugin contract: discovered `*_tool.py` modules must export a valid `Tool` inheriting `BaseTool`, override `setup_ui()` and expose non-empty metadata. (PR #23)
- Rewrote `docs/architecture.md` around the complete layered-domain model and its legacy compatibility behavior. (PRs #24, #28)
- Rebuilt the README around the current toolset, architecture, project structure, technical highlights, testing, packaging, limitations and active roadmap. (PR #28)
- Removed completed architecture, worker, plugin-contract and packaging work from the roadmap so it only tracks genuinely open work. (PR #28)
- Expanded `docs/usage.md` from a minimal launcher/build stub into a per-tool operational guide covering all first-party tools, runtime data, permissions, cancellation, troubleshooting and CI-equivalent validation. (PR #29)
- Expanded `docs/security.md` with sensitive-data flows, destructive-operation guarantees and limitations, archive/Temp Cleaner controls, process/startup protections, network authorization boundaries, WiFi/VirusTotal privacy behavior and dependency/packaging risks. (PR #29)
- Documented installation, Windows build behavior, optional Tesseract/Poppler OCR dependencies and secret-handling guidance.
- Updated architecture and README documentation for `pythonkni.infrastructure`, Process Manager service ownership and the measured coverage-ratchet strategy. (PR #34)
- Synchronized the README with the already-implemented CI artifacts and tag-driven GitHub Release workflow, removing release automation from the future-work roadmap. (PR #34)
- Updated README and architecture documentation with the final **530-test / 84.6% global / 91.5% service** coverage baseline and removed the now-completed 80%/85% coverage target from the active roadmap. (PR #35)
- Synchronized README, architecture, usage and security documentation with the `pypdf` backend, Python 3.10+ support contract, hashed dependency locks, vulnerability audits, SBOM artifacts and the 535-test CI path; removed the completed PDF/dependency-hardening items from the active roadmap. (PR #36)
- Documented the first structured-feedback tranche, its presentation-layer boundary, troubleshooting flow, exact coverage/test metrics and the remaining incremental migration roadmap. (PR #39)
- Updated the first-party documentation to reflect the completed structured-feedback migration rather than the earlier partial rollout. (PR #40)
- Rebuilt README coverage/status sections around the **578-test / 86.4% global / 93.2% service** baseline, restored the regression-tested plugin example, synchronized architecture/usage guidance and redirected the active coverage roadmap toward lower-covered presentation modules. (PR #41)
- Synchronized README, architecture, usage and roadmap guidance with the **686-test / 92.9% global / 93.2% service** presentation-hardened baseline and the **92.5%** repository coverage ratchet. (PR #42)
- Added and synchronized `docs/network-intelligence.md` around the persistent asset, topology, relationship/physical-evidence, reporting and offline OUI layers, including their accuracy and authorization boundaries. (PRs #44-#52)
- Extended Network Intelligence documentation with confidence scoring semantics, weighted evidence, SQLite migration behavior, risk/confidence separation and report-schema v2. (PR #53)
- Documented transactional IP-to-MAC promotion, conservative legacy duplicate repair, relationship/timeline rewriting and the explicit DHCP-reuse safety boundary. (PR #54)

### Development cycle covered

This Unreleased section consolidates the major merged hardening/refactoring and Network Intelligence work from **PR #2 through PR #54** across the August-September 2026 development cycle. PR #1 was intentionally not merged and was superseded by the later Temp Cleaner work in PRs #21 and #26.
