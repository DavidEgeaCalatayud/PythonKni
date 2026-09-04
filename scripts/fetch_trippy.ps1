$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $repositoryRoot "third_party\trippy.lock.json"
$contractScript = Join-Path $PSScriptRoot "check_trippy_contract.ps1"
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "Trippy lock metadata not found: $lockPath"
}
if (-not (Test-Path -LiteralPath $contractScript -PathType Leaf)) {
    throw "Trippy CLI contract smoke script not found: $contractScript"
}

$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
foreach ($property in @("version", "tag", "archive", "url", "sha256", "license")) {
    if (-not $lock.PSObject.Properties.Name.Contains($property) -or [string]::IsNullOrWhiteSpace([string]$lock.$property)) {
        throw "Trippy lock metadata is missing '$property'."
    }
}

if ([string]$lock.tag -ne [string]$lock.version) {
    throw "Trippy tag/version mismatch in lock metadata."
}
if ([string]$lock.version -ne "0.13.0") {
    throw "Network Path Analyzer currently supports only Trippy v0.13.0."
}
if ([string]$lock.url -notmatch '^https://github\.com/fujiapple852/trippy/releases/download/') {
    throw "Trippy download URL must point to the official fujiapple852/trippy GitHub Releases path."
}
if ([string]$lock.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw "Trippy SHA-256 in lock metadata is invalid."
}

$targetDir = Join-Path $repositoryRoot "third_party\trippy"
$targetExe = Join-Path $targetDir "trip.exe"
$targetLicense = Join-Path $targetDir "LICENSE"
$sourceMetadata = Join-Path $targetDir "source.json"

if ((Test-Path -LiteralPath $targetExe -PathType Leaf) -and (Test-Path -LiteralPath $targetLicense -PathType Leaf) -and (Test-Path -LiteralPath $sourceMetadata -PathType Leaf)) {
    try {
        $existing = Get-Content -LiteralPath $sourceMetadata -Raw | ConvertFrom-Json
        $hasBinaryHash = $existing.PSObject.Properties.Name.Contains("binary_sha256")
        if (
            [string]$existing.version -eq [string]$lock.version -and
            [string]$existing.archive_sha256 -eq ([string]$lock.sha256).ToLowerInvariant() -and
            $hasBinaryHash -and
            [string]$existing.binary_sha256 -match '^[0-9a-fA-F]{64}$'
        ) {
            $actualBinaryHash = (Get-FileHash -LiteralPath $targetExe -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualBinaryHash -eq ([string]$existing.binary_sha256).ToLowerInvariant()) {
                & $contractScript -Executable $targetExe -ExpectedVersion ([string]$lock.version)
                Write-Host "Verified Trippy v$($lock.version) is already staged at $targetExe"
                exit 0
            }
            Write-Host "Existing Trippy binary hash does not match staging metadata; refreshing."
        }
    } catch {
        Write-Host "Existing Trippy staging verification failed; refreshing the staged backend: $($_.Exception.Message)"
    }
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pythonkni-trippy-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $tempRoot ([string]$lock.archive)
$extractDir = Join-Path $tempRoot "extract"

New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
try {
    Write-Host "Downloading pinned Trippy $($lock.tag) from official GitHub Releases..."
    Invoke-WebRequest -Uri ([string]$lock.url) -OutFile $archivePath -UseBasicParsing

    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedHash = ([string]$lock.sha256).ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Trippy archive SHA-256 mismatch. Expected $expectedHash but received $actualHash."
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDir -Force
    $backend = Get-ChildItem -LiteralPath $extractDir -Recurse -File -Filter "trip.exe" | Select-Object -First 1
    if ($null -eq $backend) {
        throw "The verified Trippy archive does not contain trip.exe."
    }
    $licenseFile = Get-ChildItem -LiteralPath $extractDir -Recurse -File | Where-Object {
        $_.Name -match '^LICENSE(?:\..+)?$'
    } | Select-Object -First 1
    if ($null -eq $licenseFile) {
        throw "The verified Trippy archive does not contain a distributable LICENSE file."
    }

    if (Test-Path -LiteralPath $targetDir) {
        Remove-Item -LiteralPath $targetDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Copy-Item -LiteralPath $backend.FullName -Destination $targetExe
    Copy-Item -LiteralPath $licenseFile.FullName -Destination $targetLicense

    $binaryHash = (Get-FileHash -LiteralPath $targetExe -Algorithm SHA256).Hash.ToLowerInvariant()
    [ordered]@{
        name = [string]$lock.name
        version = [string]$lock.version
        tag = [string]$lock.tag
        source = [string]$lock.source
        license = [string]$lock.license
        archive = [string]$lock.archive
        archive_sha256 = $expectedHash
        binary_sha256 = $binaryHash
    } | ConvertTo-Json | Set-Content -LiteralPath $sourceMetadata -Encoding UTF8

    & $contractScript -Executable $targetExe -ExpectedVersion ([string]$lock.version)
    Write-Host "Staged verified Trippy v$($lock.version) at $targetExe"
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
