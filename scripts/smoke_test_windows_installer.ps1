param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$InstallerPath
)

$ErrorActionPreference = "Stop"

$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
$tempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
if (-not $tempRoot) {
    throw "Could not resolve a temporary directory for installer smoke testing."
}

$testRoot = Join-Path $tempRoot ("PythonKni-installer-smoke-" + [Guid]::NewGuid().ToString("N"))
$installDir = Join-Path $testRoot "app"
$installedExe = Join-Path $installDir "PythonKni.exe"
$uninstaller = Join-Path $installDir "unins000.exe"
$startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\PythonKni"
$startMenuShortcut = Join-Path $startMenuDir "PythonKni.lnk"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{A2F8C86B-77F6-4C90-A0D6-36B38C4C1F56}_is1"

if (Test-Path -LiteralPath $uninstallKey) {
    throw "Refusing installer smoke test because PythonKni is already registered for the current user."
}

New-Item -ItemType Directory -Path $testRoot -Force | Out-Null

try {
    $installArgs = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/DIR=`"$installDir`""
    )
    $installProcess = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
    if ($installProcess.ExitCode -ne 0) {
        throw "Silent installer failed with exit code $($installProcess.ExitCode)."
    }

    if (-not (Test-Path -LiteralPath $installedExe -PathType Leaf)) {
        throw "Installed application executable not found: $installedExe"
    }
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        throw "Standard Inno Setup uninstaller not found: $uninstaller"
    }
    if (-not (Test-Path -LiteralPath $startMenuShortcut -PathType Leaf)) {
        throw "Start Menu shortcut was not created: $startMenuShortcut"
    }
    if (-not (Test-Path -LiteralPath $uninstallKey)) {
        throw "Per-user uninstall registration was not created: $uninstallKey"
    }

    $smokeProcess = Start-Process -FilePath $installedExe -ArgumentList "--smoke-test" -Wait -PassThru
    if ($smokeProcess.ExitCode -ne 0) {
        throw "Installed application smoke test failed with exit code $($smokeProcess.ExitCode)."
    }

    $uninstallProcess = Start-Process -FilePath $uninstaller -ArgumentList @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART"
    ) -Wait -PassThru
    if ($uninstallProcess.ExitCode -ne 0) {
        throw "Silent uninstall failed with exit code $($uninstallProcess.ExitCode)."
    }

    if (Test-Path -LiteralPath $installDir) {
        throw "Installer smoke cleanup failed; install directory still exists: $installDir"
    }
    if (Test-Path -LiteralPath $startMenuShortcut) {
        throw "Installer smoke cleanup failed; Start Menu shortcut still exists: $startMenuShortcut"
    }
    if (Test-Path -LiteralPath $uninstallKey) {
        throw "Installer smoke cleanup failed; uninstall registration still exists: $uninstallKey"
    }

    Write-Host "Installed application smoke and uninstall cleanup succeeded."
}
finally {
    if (Test-Path -LiteralPath $installDir) {
        Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
