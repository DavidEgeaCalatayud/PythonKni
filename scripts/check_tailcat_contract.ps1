param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,
    [string]$ExpectedVersion = "0.5.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Tailcat executable not found for CLI contract smoke: $Executable"
}

$versionOutput = (& $Executable version 2>&1 | Out-String).Trim()
$versionExitCode = $LASTEXITCODE
$escapedVersion = [regex]::Escape($ExpectedVersion)
if ($versionExitCode -ne 0 -or $versionOutput -notmatch "(?<!\d)v?$escapedVersion(?!\d)") {
    throw "Tailcat version contract failed. Expected v$ExpectedVersion, got: $versionOutput"
}

$readmeOutput = (& $Executable readme 2>&1 | Out-String)
$readmeExitCode = $LASTEXITCODE
if ($readmeExitCode -ne 0) {
    throw "Tailcat embedded README contract smoke failed with exit code $readmeExitCode."
}

$requiredFragments = @(
    "tailcat recv",
    "tailcat cp",
    "tailcat serve",
    "tailcat forward",
    "--key=new",
    "127.0.0.1"
)
foreach ($fragment in $requiredFragments) {
    if (-not $readmeOutput.Contains($fragment)) {
        throw "Tailcat v$ExpectedVersion CLI contract is missing required capability marker: $fragment"
    }
}

Write-Host "Tailcat v$ExpectedVersion CLI contract smoke passed for $Executable"
