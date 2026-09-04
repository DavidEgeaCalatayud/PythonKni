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

$requiredOptions = @(
    "--mode",
    "--protocol",
    "--report-cycles",
    "--addr-family",
    "--dns-resolve-method",
    "--max-ttl",
    "--target-port",
    "--multipath-strategy",
    "--min-round-duration",
    "--max-round-duration"
)
foreach ($required in $requiredOptions) {
    if ($helpOutput -notmatch [regex]::Escape($required)) {
        throw "Trippy CLI contract is missing '$required'."
    }
}
foreach ($protocol in @("icmp", "udp", "tcp")) {
    if ($helpOutput -notmatch [regex]::Escape($protocol)) {
        throw "Trippy CLI contract no longer advertises protocol '$protocol'."
    }
}

Write-Host "Verified Trippy v$ExpectedVersion CLI contract at $Executable"
