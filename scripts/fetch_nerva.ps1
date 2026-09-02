$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $repositoryRoot "third_party\nerva.lock.json"
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "Nerva lock metadata not found: $lockPath"
}

$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
foreach ($property in @("version", "tag", "archive", "url", "sha256", "license")) {
    if (-not $lock.PSObject.Properties.Name.Contains($property) -or [string]::IsNullOrWhiteSpace([string]$lock.$property)) {
        throw "Nerva lock metadata is missing '$property'."
    }
}

if ([string]$lock.tag -ne "v$($lock.version)") {
    throw "Nerva tag/version mismatch in lock metadata."
}
if ([string]$lock.url -notmatch '^https://github\.com/praetorian-inc/nerva/releases/download/') {
    throw "Nerva download URL must point to the official praetorian-inc/nerva GitHub Releases path."
}
if ([string]$lock.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw "Nerva SHA-256 in lock metadata is invalid."
}

$targetDir = Join-Path $repositoryRoot "third_party\nerva"
$targetExe = Join-Path $targetDir "nerva.exe"
$sourceMetadata = Join-Path $targetDir "source.json"

if ((Test-Path -LiteralPath $targetExe -PathType Leaf) -and (Test-Path -LiteralPath $sourceMetadata -PathType Leaf)) {
    try {
        $existing = Get-Content -LiteralPath $sourceMetadata -Raw | ConvertFrom-Json
        if ([string]$existing.version -eq [string]$lock.version -and [string]$existing.archive_sha256 -eq ([string]$lock.sha256).ToLowerInvariant()) {
            Write-Host "Verified Nerva v$($lock.version) is already staged at $targetExe"
            exit 0
        }
    } catch {
        Write-Host "Existing Nerva staging metadata is invalid; refreshing the staged engine."
    }
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pythonkni-nerva-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $tempRoot ([string]$lock.archive)
$extractDir = Join-Path $tempRoot "extract"

New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
try {
    Write-Host "Downloading pinned Nerva $($lock.tag) from official GitHub Releases..."
    Invoke-WebRequest -Uri ([string]$lock.url) -OutFile $archivePath -UseBasicParsing

    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedHash = ([string]$lock.sha256).ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Nerva archive SHA-256 mismatch. Expected $expectedHash but received $actualHash."
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDir -Force
    $engine = Get-ChildItem -LiteralPath $extractDir -Recurse -File -Filter "nerva.exe" | Select-Object -First 1
    if ($null -eq $engine) {
        throw "The verified Nerva archive does not contain nerva.exe."
    }

    if (Test-Path -LiteralPath $targetDir) {
        Remove-Item -LiteralPath $targetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Copy-Item -LiteralPath $engine.FullName -Destination $targetExe

    $licenseFile = Get-ChildItem -LiteralPath $extractDir -Recurse -File | Where-Object {
        $_.Name -match '^LICENSE(?:\..+)?$'
    } | Select-Object -First 1
    if ($null -ne $licenseFile) {
        Copy-Item -LiteralPath $licenseFile.FullName -Destination (Join-Path $targetDir $licenseFile.Name)
    }

    [ordered]@{
        name = [string]$lock.name
        version = [string]$lock.version
        tag = [string]$lock.tag
        source = [string]$lock.source
        license = [string]$lock.license
        archive = [string]$lock.archive
        archive_sha256 = $expectedHash
    } | ConvertTo-Json | Set-Content -LiteralPath $sourceMetadata -Encoding UTF8

    Write-Host "Staged verified Nerva v$($lock.version) at $targetExe"
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
