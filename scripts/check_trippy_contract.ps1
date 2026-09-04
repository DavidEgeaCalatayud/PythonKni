param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Trippy executable not found: $Executable"
}

$versionOutput = (& $Executable --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Trippy --version failed with exit code $LASTEXITCODE: $versionOutput"
}
if ($versionOutput -notmatch [regex]::Escape($ExpectedVersion)) {
    throw "Trippy version contract mismatch. Expected $ExpectedVersion, received: $versionOutput"
}

$helpOutput = (& $Executable --help 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Trippy --help failed with exit code $LASTEXITCODE."
}
foreach ($required in @("--mode", "--protocol", "--report-cycles", "--max-ttl", "icmp", "udp", "tcp")) {
    if ($helpOutput -notmatch [regex]::Escape($required)) {
        throw "Trippy CLI contract is missing '$required'."
    }
}

Write-Host "Verified Trippy v$ExpectedVersion CLI contract at $Executable"
