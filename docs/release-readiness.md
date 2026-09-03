# Release readiness

This document records PythonKni's Windows release-engineering contract after the verified `v0.1.0` release, the first-class installer milestone and the pinned Nerva service-fingerprinting integration.

## Released baseline

`pyproject.toml` currently declares:

```text
0.1.0
```

`v0.1.0` is published as the first public release. Its tag remains an immutable reference to the exact released source revision. The release contains the validated portable Windows ZIP/checksum plus the CycloneDX SBOM, OUI provenance metadata and both dependency locks.

Installer generation and Nerva packaging were added **after** `v0.1.0`, so the historical `v0.1.0` release intentionally remains unchanged. Future releases built from current source add the versioned setup executable/checksum and embed the verified Nerva engine in the application bundle.

## Current validated baseline

The current Nerva-enabled installer branch baseline has been validated on Windows / **CPython 3.13.15** with:

- **1,131/1,131 tests** passing;
- **93.0%** repository branch coverage;
- **93.5%** aggregate `service.py` coverage;
- **93.4%** `pythonkni/network/window.py` coverage;
- **99.2%** `pythonkni/network/fingerprinting.py` coverage;
- exact SHA-256-locked runtime/development dependency graphs;
- `pip check` plus strict runtime/development `pip-audit` with no known vulnerabilities;
- CycloneDX runtime SBOM generation;
- offline validation of the **40,046-assignment** bundled IEEE MA-L registry and provenance metadata;
- Network Intelligence benchmark smoke;
- Network Intelligence structural typing ratchet at **683/736 annotation slots (92.8%)**, **269 fully annotated / 308 tracked callables**, with the explicit-`Any` ceiling unchanged at 39;
- Ruff check/format;
- exact Nerva **v1.69.4** Windows amd64 pin and SHA-256 validation before extraction;
- required upstream Apache-2.0 license retention during Nerva staging;
- PyInstaller Windows build containing the staged Nerva engine;
- packaged `nerva.exe --capabilities` verification;
- frozen `PythonKni.exe --smoke-test`;
- ZIP/checksum artifact generation;
- Inno Setup installer generation using the preinstalled runner toolchain;
- real installed-app smoke: silent install, installed executable smoke, silent uninstall and cleanup verification;
- installer executable + SHA-256 artifact retention.

Grouped CI coverage ratchets also fail immediately on native-command errors, preventing an individual floor failure from being masked by a later successful PowerShell command.

A release must repeat the Release workflow against the exact immutable release commit; a previous CI artifact is supporting evidence, not a substitute for the release run.

## Functional milestone completed

The current Network Intelligence platform includes persistent inventory/identity reconciliation, classification confidence, relationships/topology/physical evidence, contextual Security Score, deterministic snapshot reporting, offline snapshot comparison, Security Score History, opt-in scheduled checks, automatic snapshots, local change notifications, History Center/trends/configurable retention and a reproducible build-time IEEE OUI registry updater.

Network Explorer additionally supports explicit application-layer fingerprinting of already-confirmed open TCP ports through the pinned Nerva engine. Results are normalized into PythonKni-owned models, can be exported as JSON and can be explicitly applied to one matching online Network Intelligence asset. Service/product/version changes then participate in persisted timeline and snapshot comparison without automatically changing the asset's risk or classification.

The quality/toolchain milestone also includes the CPython 3.13.15 runtime contract, incremental Network Intelligence structural typing ratchet, first-class per-user Windows installer pipeline and reproducible Nerva staging/packaging contract.

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

Historical recovery has compatibility rules for both later distribution milestones. If an immutable old tag predates installer or Nerva support, recovery republishes only the assets and runtime contents supported by that tagged source. It never injects current installer code or a current Nerva binary into old immutable source. New direct/bootstrap releases require the corresponding support files to be present.

After resolving and checking out the release source, the same workflow must:

1. install both committed dependency locks with `--require-hashes`;
2. validate locks, `pip check`, runtime/dev audits and CycloneDX SBOM;
3. compile source and validate the bundled OUI registry offline;
4. run the full test suite and coverage ratchets;
5. enforce the Network Intelligence structural typing ratchet;
6. run Ruff check/format;
7. for Nerva-enabled source, stage the exact pinned engine only after SHA-256/license validation;
8. build with PyInstaller, verify the packaged Nerva engine when enabled and run the frozen smoke test;
9. package the versioned Windows ZIP + SHA-256 checksum;
10. for installer-enabled source, build the version-bound Inno Setup installer and run the installed-app lifecycle smoke;
11. upload retained workflow artifacts; and
12. publish/update the GitHub Release with the validated files.

The publication probe is intentionally compatible with the Windows PowerShell runner: a missing GitHub Release is treated as the expected create path rather than as a terminating native-command error. Existing releases use an idempotent asset upload with `--clobber`; missing releases are created with `--verify-tag`.

The release is complete only after the Release workflow conclusion is `success`, the immutable tag resolves to the intended `main` commit and the GitHub Release assets are present for that exact tag.

## Expected release assets

For current installer/Nerva-enabled source, future releases publish:

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

Nerva is embedded inside the validated Windows application bundle rather than published as an independent PythonKni release asset. The retained workflow evidence includes `coverage.xml` and the exact `third_party/nerva.lock.json` provenance pin. The historical `v0.1.0` release predates both installer and Nerva support and therefore correctly retains its original six assets only.

## Nerva distribution contract

`third_party/nerva.lock.json` pins Nerva `v1.69.4` for Windows amd64 and SHA-256:

```text
59e59eb54c8c5c581031387a0aa23c98983db94301e811f3c9b1802a05fc97f7
```

`scripts/fetch_nerva.ps1` downloads only that exact upstream archive during explicit build/CI/release preparation, verifies the digest before extraction and requires the upstream Apache-2.0 license. Normal application runtime does not download or update Nerva.

PyInstaller packages the staged engine, license and provenance. CI/release then execute the packaged `nerva.exe --capabilities` before accepting the Windows bundle. The current product integration uses Nerva only as an explicit fingerprinting step for TCP ports already confirmed open by Network Explorer; broader protocol/misconfiguration modes are not part of this milestone.

See [`network-service-fingerprinting.md`](network-service-fingerprinting.md).

## Installer contract

The installer is built with Inno Setup as a **per-user** package with `PrivilegesRequired=lowest`. Its default program directory is `%LOCALAPPDATA%\Programs\PythonKni`, it creates a Start Menu entry and uses the standard Inno Setup uninstaller.

The build script reads the application version from `pyproject.toml`; Release builds additionally require that version to match the resolved immutable release tag. CI never downloads Chocolatey packages, installer compilers or third-party Actions to construct the setup executable: it uses the Inno Setup compiler already present on the Windows runner and fails if that compiler is unavailable.

The installed-app smoke uses an isolated temporary target, verifies Start Menu and per-user uninstall registration, executes the **installed** `PythonKni.exe --smoke-test`, uninstalls silently and verifies cleanup. The smoke refuses to run if PythonKni is already registered as installed for the current user so local validation cannot silently replace a real installation.

See [`windows-installer.md`](windows-installer.md) for the installation, checksum and uninstall contract.

## Known distribution limitations

These do not block the current technical distribution model, but remain explicit:

- Windows is the only packaged/validated platform;
- the executable and installer are not yet Authenticode/code signed, so Windows SmartScreen/reputation warnings remain possible;
- Python 3.14+, free-threaded CPython and non-Windows packaging are not claimed;
- optional OCR workflows still depend on local Tesseract/Poppler;
- localization is incomplete.

## Post-v0.1.0 distribution roadmap

1. add representative screenshots/demo media;
2. define certificate ownership, identity and secret handling for Authenticode signing;
3. sign the executable/installer once that policy is established;
4. keep dependency/OUI/runtime/typing/installer/Nerva gates non-regressive while product features evolve.
