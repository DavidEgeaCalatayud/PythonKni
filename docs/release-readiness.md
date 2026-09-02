# Release readiness

This document records the first-release gate for PythonKni after the Network Intelligence roadmap and Python runtime/quality-gate work through PR #64.

## Intended first version

`pyproject.toml` currently declares:

```text
0.1.0
```

The coherent first release tag is therefore **`v0.1.0`**. This document does not assert that the tag or GitHub Release already exists; release status is established only after the tag-triggered workflow finishes successfully and the published assets are verified.

## Current validated baseline

The pre-release `main` baseline before this documentation synchronization has been validated on Windows / **CPython 3.13.15** with:

- **1,060/1,060 tests** passing;
- **92.8%** repository branch coverage;
- **93.5%** aggregate `service.py` coverage;
- exact SHA-256-locked runtime/development dependency graphs;
- `pip check` plus strict runtime/development `pip-audit` with no known vulnerabilities;
- CycloneDX runtime SBOM generation;
- offline validation of the **40,046-assignment** bundled IEEE MA-L registry and provenance metadata;
- Network Intelligence benchmark smoke;
- Network Intelligence structural typing ratchet (**92.65%** current annotation coverage);
- Ruff check/format;
- PyInstaller Windows build;
- frozen `PythonKni.exe --smoke-test`;
- ZIP/checksum artifact publication.

A release tag must repeat the Release workflow on the exact tagged commit; a previous CI artifact is supporting evidence, not a substitute for the release run.

## Functional milestone completed

The current Network Intelligence platform includes persistent inventory/identity reconciliation, classification confidence, relationships/topology/physical evidence, contextual Security Score, deterministic snapshot reporting, offline snapshot comparison, Security Score History, opt-in scheduled checks, automatic snapshots, local change notifications, History Center/trends/configurable retention and a reproducible build-time IEEE OUI registry updater.

The quality/toolchain milestone also includes the CPython 3.13.15 runtime contract and incremental Network Intelligence structural typing ratchet enforced by both CI and Release.

## Release workflow contract

A tag matching exact `vX.Y.Z` triggers `.github/workflows/release.yml`. The workflow must:

1. confirm the tag uses exact semantic `vX.Y.Z` syntax and points to a commit contained in `main`;
2. install both committed dependency locks with `--require-hashes`;
3. validate locks, `pip check`, runtime/dev audits and CycloneDX SBOM;
4. compile source and validate the bundled OUI registry offline;
5. run the full test suite and coverage ratchets;
6. enforce the Network Intelligence structural typing ratchet;
7. run Ruff check/format;
8. build with PyInstaller and run the frozen smoke test;
9. package the versioned Windows ZIP + SHA-256 checksum;
10. upload retained workflow artifacts and publish/update the GitHub Release with the validated files.

The release is complete only after the workflow conclusion is `success` and the GitHub Release assets are present for the exact tag commit.

## Expected release assets

The release path publishes the versioned Windows ZIP/checksum plus supply-chain evidence including the CycloneDX SBOM, OUI provenance metadata and runtime/development locks. CI additionally retains `coverage.xml` and the Network Intelligence benchmark artifact for build evidence.

## Known distribution limitations

These do **not** block a technical `v0.1.0` pre-1.0 release, but should be explicit:

- Windows is the only packaged/validated platform;
- the executable is not Authenticode/code signed;
- there is no MSI/Inno Setup/NSIS installer yet; distribution is the validated ZIP bundle;
- Python 3.14+, free-threaded CPython and non-Windows packaging are not claimed;
- optional OCR workflows still depend on local Tesseract/Poppler;
- localization is incomplete.

## Post-v0.1.0 distribution roadmap

1. add representative screenshots/demo media;
2. add Windows installer generation;
3. add executable/installer signing once certificate/identity handling is defined;
4. keep dependency/OUI/runtime/typing gates non-regressive while product features evolve.
