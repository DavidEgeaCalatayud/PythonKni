# Windows installer

PythonKni's post-`v0.1.0` Windows distribution pipeline builds a first-class Inno Setup installer from the already validated PyInstaller bundle.

## Installation contract

The installer is **per-user** and does not require administrator privileges. Its default application directory is:

```text
%LOCALAPPDATA%\Programs\PythonKni\
```

A normal install creates a **PythonKni** Start Menu shortcut and registers the standard Inno Setup uninstaller for the current user. The installer does not install a Windows service or background daemon.

Future GitHub Releases built from installer-enabled source publish two additional assets alongside the portable ZIP and supply-chain evidence:

```text
PythonKni-vX.Y.Z-windows-x64-setup.exe
PythonKni-vX.Y.Z-windows-x64-setup.sha256
```

The installer version is read from `project.version` in `pyproject.toml`. Release builds additionally require that version to match the immutable `vX.Y.Z` release tag.

## Verify the installer checksum

Before running a downloaded installer, calculate its SHA-256 digest:

```powershell
Get-FileHash .\PythonKni-vX.Y.Z-windows-x64-setup.exe -Algorithm SHA256
```

Compare the resulting digest with the corresponding `.sha256` asset from the same GitHub Release.

## Install

Run the versioned `...-setup.exe` normally and follow the Inno Setup wizard. The default installation is scoped to the current Windows user, so elevation is not expected.

After installation, launch **PythonKni** from the Start Menu or directly from:

```text
%LOCALAPPDATA%\Programs\PythonKni\PythonKni.exe
```

## Uninstall

Use either the **Uninstall PythonKni** Start Menu entry or the normal Windows installed-apps/uninstall UI. The standard Inno Setup uninstaller removes the installed application files, shortcuts and per-user uninstall registration.

PythonKni runtime data is intentionally separate from installed program files and remains under:

```text
%LOCALAPPDATA%\PythonKni\
```

Uninstalling the application does **not** automatically delete this user data. Remove that directory manually only if you intentionally want to discard saved configuration, histories and other local application state.

## CI build and installed-app smoke

CI does not download an installer toolchain. It requires the Inno Setup 6 compiler already present on the Windows runner and fails clearly when `ISCC.exe` is unavailable.

After the PyInstaller bundle passes its frozen smoke test, CI runs:

```powershell
.\scripts\build_windows_installer.ps1 -OutputPrefix "PythonKni-windows-x64-setup"
.\scripts\smoke_test_windows_installer.ps1 -InstallerPath ".\dist\PythonKni-windows-x64-setup.exe"
```

The smoke test uses an isolated temporary installation directory and verifies the complete installed-app lifecycle:

1. silent per-user installation;
2. installed `PythonKni.exe --smoke-test` execution;
3. presence of the standard uninstaller, Start Menu shortcut and per-user uninstall registration;
4. silent uninstall; and
5. cleanup of the install directory, Start Menu shortcut and uninstall registration.

For safety, the smoke script refuses to run when PythonKni is already registered as installed for the current user, so it cannot silently replace an existing normal installation during local development.

## Signing limitation

The installer and packaged executable are currently **unsigned**. Windows may therefore show SmartScreen/reputation warnings even when the downloaded file matches the published SHA-256 checksum. Authenticode signing is intentionally a separate release-engineering milestone because certificate ownership, identity and secret-handling policy have not yet been defined.
