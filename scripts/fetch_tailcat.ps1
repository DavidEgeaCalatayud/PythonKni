$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $repositoryRoot "third_party\tailcat.lock.json"
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "Tailcat lock metadata not found: $lockPath"
}

$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
foreach ($property in @("version", "tag", "archive", "url", "sha256", "license")) {
    if (-not $lock.PSObject.Properties.Name.Contains($property) -or [string]::IsNullOrWhiteSpace([string]$lock.$property)) {
        throw "Tailcat lock metadata is missing '$property'."
    }
}

if ([string]$lock.tag -ne "v$($lock.version)") {
    throw "Tailcat tag/version mismatch in lock metadata."
}
if ([string]$lock.version -ne "0.5.0") {
    throw "Secure Transfer currently supports only Tailcat v0.5.0."
}
if ([string]$lock.url -notmatch '^https://github\.com/tailscale/tailcat/releases/download/') {
    throw "Tailcat download URL must point to the official tailscale/tailcat GitHub Releases path."
}
if ([string]$lock.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw "Tailcat SHA-256 in lock metadata is invalid."
}

$targetDir = Join-Path $repositoryRoot "third_party\tailcat"
$targetExe = Join-Path $targetDir "tailcat.exe"
$targetLicense = Join-Path $targetDir "LICENSE"
$sourceMetadata = Join-Path $targetDir "source.json"

if ((Test-Path -LiteralPath $targetExe -PathType Leaf) -and (Test-Path -LiteralPath $targetLicense -PathType Leaf) -and (Test-Path -LiteralPath $sourceMetadata -PathType Leaf)) {
    try {
        $existing = Get-Content -LiteralPath $sourceMetadata -Raw | ConvertFrom-Json
        if ([string]$existing.version -eq [string]$lock.version -and [string]$existing.archive_sha256 -eq ([string]$lock.sha256).ToLowerInvariant()) {
            Write-Host "Verified Tailcat v$($lock.version) is already staged at $targetExe"
            exit 0
        }
    } catch {
        Write-Host "Existing Tailcat staging metadata is invalid; refreshing the staged transport."
    }
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pythonkni-tailcat-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $tempRoot ([string]$lock.archive)
$extractDir = Join-Path $tempRoot "extract"

New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
try {
    Write-Host "Downloading pinned Tailcat $($lock.tag) from official GitHub Releases..."
    Invoke-WebRequest -Uri ([string]$lock.url) -OutFile $archivePath -UseBasicParsing

    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedHash = ([string]$lock.sha256).ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Tailcat archive SHA-256 mismatch. Expected $expectedHash but received $actualHash."
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDir -Force
    $transport = Get-ChildItem -LiteralPath $extractDir -Recurse -File -Filter "tailcat.exe" | Select-Object -First 1
    if ($null -eq $transport) {
        throw "The verified Tailcat archive does not contain tailcat.exe."
    }
    $licenseFile = Get-ChildItem -LiteralPath $extractDir -Recurse -File | Where-Object {
        $_.Name -match '^LICENSE(?:\..+)?$'
    } | Select-Object -First 1
    if ($null -eq $licenseFile) {
        throw "The verified Tailcat archive does not contain a distributable LICENSE file."
    }

    if (Test-Path -LiteralPath $targetDir) {
        Remove-Item -LiteralPath $targetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Copy-Item -LiteralPath $transport.FullName -Destination $targetExe
    Copy-Item -LiteralPath $licenseFile.FullName -Destination $targetLicense

    [ordered]@{
        name = [string]$lock.name
        version = [string]$lock.version
        tag = [string]$lock.tag
        source = [string]$lock.source
        license = [string]$lock.license
        archive = [string]$lock.archive
        archive_sha256 = $expectedHash
    } | ConvertTo-Json | Set-Content -LiteralPath $sourceMetadata -Encoding UTF8

    $versionOutput = (& $targetExe version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch '0\.5\.0') {
        throw "Staged Tailcat version smoke failed: $versionOutput"
    }

    Write-Host "Staged verified Tailcat v$($lock.version) at $targetExe"
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
