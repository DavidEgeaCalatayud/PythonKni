param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputPrefix
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$bundleDir = Join-Path $PWD "dist\PythonKni"
$exe = Join-Path $bundleDir "PythonKni.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Validated bundle executable not found: $exe"
}

function Test-PackagedNativeRuntime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LockPath,

        [Parameter(Mandatory = $true)]
        [string]$PackagedExecutable,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Contract
    )

    if (-not (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
        return
    }
    if (-not (Test-Path -LiteralPath $PackagedExecutable -PathType Leaf)) {
        throw "Source declares native runtime $LockPath but the packaged executable is missing: $PackagedExecutable"
    }
    & $Contract $PackagedExecutable
}

$nervaLock = Join-Path $PWD "third_party\nerva.lock.json"
$nerva = Join-Path $bundleDir "_internal\third_party\nerva\nerva.exe"
Test-PackagedNativeRuntime -LockPath $nervaLock -PackagedExecutable $nerva -Contract {
    param($path)
    & $path --capabilities | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged Nerva capability contract failed with exit code $LASTEXITCODE"
    }
}

$tailcatLock = Join-Path $PWD "third_party\tailcat.lock.json"
$tailcat = Join-Path $bundleDir "_internal\third_party\tailcat\tailcat.exe"
$tailcatContract = Join-Path $PWD "scripts\check_tailcat_contract.ps1"
Test-PackagedNativeRuntime -LockPath $tailcatLock -PackagedExecutable $tailcat -Contract {
    param($path)
    if (-not (Test-Path -LiteralPath $tailcatContract -PathType Leaf)) {
        throw "Tailcat contract script is missing: $tailcatContract"
    }
    $lock = Get-Content -LiteralPath $tailcatLock -Raw | ConvertFrom-Json
    & $tailcatContract -Executable $path -ExpectedVersion ([string]$lock.version)
}

$trippyLock = Join-Path $PWD "third_party\trippy.lock.json"
$trippy = Join-Path $bundleDir "_internal\third_party\trippy\trip.exe"
$trippyContract = Join-Path $PWD "scripts\check_trippy_contract.ps1"
Test-PackagedNativeRuntime -LockPath $trippyLock -PackagedExecutable $trippy -Contract {
    param($path)
    if (-not (Test-Path -LiteralPath $trippyContract -PathType Leaf)) {
        throw "Trippy contract script is missing: $trippyContract"
    }
    $lock = Get-Content -LiteralPath $trippyLock -Raw | ConvertFrom-Json
    & $trippyContract -Executable $path -ExpectedVersion ([string]$lock.version)
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
