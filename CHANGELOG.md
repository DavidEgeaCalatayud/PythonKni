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
- Raised CI/release coverage ratchets from 58.8% to 66.5% repository-wide and from 64.7% to 81.0% across services; Startup, Event Viewer and System Report now also have individual non-regression gates. (PR #35)

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
- Expanded the suite from 289 to 415 tests, raising measured branch coverage from 58.85% to 66.7% repository-wide and from 64.7% to 81.1% across all `service.py` modules. (PR #35)
- Startup, Event Viewer and System Report service coverage now measure 87.7%, 95.4% and 97.2% respectively, protected by individual CI/release ratchets of 87.5%, 95.0% and 97.0%. (PR #35)

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
- Updated README and architecture documentation with the 415-test coverage baseline, stronger ratchets and the next sub-80% service targets. (PR #35)

### Development cycle covered

This Unreleased section consolidates the major merged and pending hardening/refactoring work from **PR #2 through PR #35** during the August 2026 development cycle. PR #1 was intentionally not merged and was superseded by the later Temp Cleaner work in PRs #21 and #26.
