# Release readiness

This document records the first-release gate for PythonKni after the Network Intelligence roadmap, runtime/quality-gate work and public documentation synchronization.

## Intended first version

`pyproject.toml` currently declares:

```text
0.1.0
```

The coherent first release tag is therefore **`v0.1.0`**. Release status is established only after the Release workflow finishes successfully and the published assets are verified; the presence of a tag or retained workflow artifact alone is not sufficient.

## Current validated baseline

The current pre-release `main` baseline has been validated on Windows / **CPython 3.13.15** with:

- **1,063/1,063 tests** passing;
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

A release must repeat the Release workflow against the exact immutable release commit; a previous CI artifact is supporting evidence, not a substitute for the release run.

## Functional milestone completed

The current Network Intelligence platform includes persistent inventory/identity reconciliation, classification confidence, relationships/topology/physical evidence, contextual Security Score, deterministic snapshot reporting, offline snapshot comparison, Security Score History, opt-in scheduled checks, automatic snapshots, local change notifications, History Center/trends/configurable retention and a reproducible build-time IEEE OUI registry updater.

The quality/toolchain milestone also includes the CPython 3.13.15 runtime contract and incremental Network Intelligence structural typing ratchet enforced by both CI and Release.

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

After resolving and checking out the release source, the same workflow must:

1. install both committed dependency locks with `--require-hashes`;
2. validate locks, `pip check`, runtime/dev audits and CycloneDX SBOM;
3. compile source and validate the bundled OUI registry offline;
4. run the full test suite and coverage ratchets;
5. enforce the Network Intelligence structural typing ratchet;
6. run Ruff check/format;
7. build with PyInstaller and run the frozen smoke test;
8. package the versioned Windows ZIP + SHA-256 checksum;
9. upload retained workflow artifacts; and
10. publish/update the GitHub Release with the validated files.

The publication probe is intentionally compatible with the Windows PowerShell runner: a missing GitHub Release is treated as the expected create path rather than as a terminating native-command error. Existing releases use an idempotent asset upload with `--clobber`; missing releases are created with `--verify-tag`.

The release is complete only after the Release workflow conclusion is `success`, the immutable tag resolves to the intended `main` commit and the GitHub Release assets are present for that exact tag.

## Expected release assets

The release path publishes the versioned Windows ZIP/checksum plus supply-chain evidence including the CycloneDX SBOM, OUI provenance metadata and runtime/development locks. The retained workflow artifact also includes `coverage.xml` as build evidence.

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
