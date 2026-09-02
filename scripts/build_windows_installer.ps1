param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$OutputPrefix,

    [Parameter(Mandatory = $false)]
    [ValidatePattern('^v\d+\.\d+\.\d+$')]
    [string]$ExpectedTag
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$projectPath = Join-Path $repoRoot "pyproject.toml"
$project = Get-Content -LiteralPath $projectPath -Raw
if ($project -notmatch '(?m)^version\s*=\s*"([^\"]+)"\s*$') {
    throw "Could not resolve project.version from $projectPath."
}

$version = $Matches[1]
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Installer builds require a numeric X.Y.Z project.version. Received: $version"
}

if ($ExpectedTag -and $ExpectedTag -ne "v$version") {
    throw "Installer version $version does not match release tag $ExpectedTag."
}

$bundleDir = Join-Path $repoRoot "dist\PythonKni"
$bundleExe = Join-Path $bundleDir "PythonKni.exe"
if (-not (Test-Path -LiteralPath $bundleExe -PathType Leaf)) {
    throw "Validated PyInstaller bundle executable not found: $bundleExe"
}

$installerDefinition = Join-Path $repoRoot "installer\PythonKni.iss"
if (-not (Test-Path -LiteralPath $installerDefinition -PathType Leaf)) {
    throw "Inno Setup definition not found: $installerDefinition"
}

$compiler = $null
$command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($command) {
    $compiler = $command.Source
}

if (-not $compiler) {
    foreach ($root in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if (-not $root) {
            continue
        }

        $candidate = Join-Path $root "Inno Setup 6\ISCC.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $compiler = $candidate
            break
        }
    }
}

if (-not $compiler) {
    throw "Inno Setup 6 compiler (ISCC.exe) is unavailable. Install it before building the installer; CI must not download it dynamically."
}

$outputDir = Join-Path $repoRoot "dist"
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$installer = Join-Path $outputDir "$OutputPrefix.exe"
$checksum = Join-Path $outputDir "$OutputPrefix.sha256"
foreach ($path in @($installer, $checksum)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

Write-Host "Using Inno Setup compiler: $compiler"
Write-Host "Building PythonKni installer version $version"

& $compiler "/DAppVersion=$version" "/DSourceDir=$bundleDir" "/DOutputBaseFilename=$OutputPrefix" "/O$outputDir" $installerDefinition
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Inno Setup did not produce the expected installer: $installer"
}

$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$installerName = Split-Path $installer -Leaf
"$hash  $installerName" | Set-Content -LiteralPath $checksum -Encoding ascii

Write-Host "Created $installer"
Write-Host "Created $checksum"
