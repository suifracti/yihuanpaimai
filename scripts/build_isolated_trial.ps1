# build_isolated_trial.ps1 - Single fail-closed entrypoint for packaging isolated trial
param(
    [string]$DistPath = "",
    [string]$WorkPath = "",
    [string]$Revision = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

# 1. Determine git revision
if (-not $Revision) {
    try {
        $Revision = (git rev-parse --short HEAD).Trim()
    } catch {
        $Revision = "dev"
    }
}

$dateStamp = Get-Date -Format "yyyyMMdd"
$buildDirName = "isolated_trial_ux_fixes_${dateStamp}_${Revision}"

if (-not $DistPath) {
    $DistPath = "build\$buildDirName\dist"
}
if (-not $WorkPath) {
    $WorkPath = "build\$buildDirName\build"
}

Write-Host "================================================="
Write-Host " Building Isolated Trial Package"
Write-Host " Repo Root: $repoRoot"
Write-Host " Revision:  $Revision"
Write-Host " Dist Path: $DistPath"
Write-Host " Work Path: $WorkPath"
Write-Host "================================================="

# 2. Set environment variables to guarantee isolated trial build
$env:NTE_BUILD_ISOLATED_TRIAL = "1"
$env:NTE_BUILD_REVISION = $Revision

# 3. Locate PyInstaller
$pyinstallerCandidates = @(
    "$repoRoot\build\takeover_20260905\repro-venv\Scripts\pyinstaller.exe",
    "pyinstaller.exe"
)
$pyinstallerExe = $null
foreach ($cand in $pyinstallerCandidates) {
    if (Test-Path $cand) {
        $pyinstallerExe = $cand
        break
    }
}
if (-not $pyinstallerExe) {
    $pyinstallerExe = "pyinstaller"
}

# 4. Run PyInstaller
$specItem = Get-ChildItem -Path "$repoRoot\app" -Filter "*.spec" | Select-Object -First 1
if (-not $specItem) {
    Write-Error "Spec file not found in $repoRoot\app"
    exit 1
}
$specFile = $specItem.FullName
$specBaseName = $specItem.BaseName
Write-Host "Running PyInstaller with spec: $specFile..."
& $pyinstallerExe -y --clean --distpath $DistPath --workpath $WorkPath $specFile
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

# 5. Fail-closed post-build validation
$targetDir = Join-Path $DistPath $specBaseName
if (-not (Test-Path $targetDir)) {
    $targetDir = (Get-ChildItem -Path $DistPath -Directory | Select-Object -First 1).FullName
}
$targetExe = Join-Path $targetDir "$specBaseName.exe"
if (-not (Test-Path $targetExe)) {
    $targetExe = (Get-ChildItem -Path $targetDir -Filter "*.exe" | Select-Object -First 1).FullName
}
$internalDir = Join-Path $targetDir "_internal"
$markerPath = Join-Path $internalDir "isolated_trial.json"

if (-not (Test-Path $targetExe)) {
    Write-Error "BUILD FAILED: Target executable not found at $targetExe"
    exit 1
}

if (-not (Test-Path $markerPath)) {
    Write-Error "BUILD FAILED (FAIL-CLOSED): Required isolated marker missing at $markerPath"
    exit 1
}

try {
    $markerContent = Get-Content -Raw $markerPath -Encoding UTF8 | ConvertFrom-Json
    if ($markerContent.profile -ne "isolated-trial-v1") {
        Write-Error "BUILD FAILED (FAIL-CLOSED): Marker profile is '$($markerContent.profile)', expected 'isolated-trial-v1'"
        exit 1
    }
} catch {
    Write-Error "BUILD FAILED (FAIL-CLOSED): Failed to parse marker JSON at $markerPath : $_"
    exit 1
}

# 6. Output success verification
$exeHash = (Get-FileHash -Algorithm SHA256 $targetExe).Hash
Write-Host "================================================="
Write-Host " BUILD SUCCESSFUL (ISOLATED TRIAL CONFIRMED)"
Write-Host " EXE Path:   $targetExe"
Write-Host " EXE SHA256: $exeHash"
Write-Host " Marker:     $markerPath"
Write-Host " Marker Profile: $($markerContent.profile)"
Write-Host "================================================="
