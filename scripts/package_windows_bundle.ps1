param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputPrefix
)

$ErrorActionPreference = "Stop"

$bundleDir = Join-Path $PWD "dist\PythonKni"
$exe = Join-Path $bundleDir "PythonKni.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Validated bundle executable not found: $exe"
}

$zip = Join-Path $PWD "dist\$OutputPrefix.zip"
$checksum = Join-Path $PWD "dist\$OutputPrefix.sha256"

foreach ($path in @($zip, $checksum)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

Compress-Archive -Path (Join-Path $bundleDir "*") -DestinationPath $zip -CompressionLevel Optimal

$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
$zipName = Split-Path $zip -Leaf
"$hash  $zipName" | Set-Content -LiteralPath $checksum -Encoding ascii

Write-Host "Created $zip"
Write-Host "Created $checksum"
