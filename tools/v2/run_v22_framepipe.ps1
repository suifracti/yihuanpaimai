param(
    [string]$InputImage = "tests/fixtures/real_snapshots_4d2d1j/fixture_settlement_client_sanitized.png",
    [string]$WorkDir = "build/goal-luna/frames/candidate-final",
    [ValidateSet("", "model_load_fail", "state_unwritable")]
    [string]$EngineFault = ""
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonExe = Join-Path $repoRoot "build\takeover_20260905\repro-venv\Scripts\python.exe"
$hostExe = Join-Path $repoRoot "build\goal-luna\frames\dotnet\Release\net8.0\NteHost.exe"
$engineScript = Join-Path $repoRoot "architecture\v2\host\engine_v22\nte_engine_v22.py"
$contractsDir = Join-Path $repoRoot "architecture\v2\contracts"
$sourceImage = (Resolve-Path (Join-Path $repoRoot $InputImage)).Path
$runDir = (Join-Path $repoRoot $WorkDir)
$rawPath = Join-Path $runDir "input.bgra"
$metaPath = Join-Path $runDir "input.json"
$resultPath = Join-Path $runDir "host-result.json"
$tracePath = Join-Path $runDir "host-trace.jsonl"
$tempDir = Join-Path $runDir "temp"

foreach ($required in @($pythonExe, $hostExe, $engineScript, $contractsDir, $sourceImage)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "缺少运行依赖或输入：$required"
    }
}
New-Item -ItemType Directory -Force -Path $runDir, $tempDir | Out-Null

# The launcher scopes child-process temporary files to this project evidence tree.
$env:TEMP = $tempDir
$env:TMP = $tempDir

if (-not (Test-Path -LiteralPath $rawPath) -or -not (Test-Path -LiteralPath $metaPath)) {
    & $pythonExe (Join-Path $repoRoot "tools\v2\prepare_v2_frame_input.py") `
        --input $sourceImage --raw-output $rawPath --metadata-output $metaPath
    if ($LASTEXITCODE -ne 0) {
        throw "帧输入准备失败，退出码 $LASTEXITCODE"
    }
}

$hostArgs = @(
    "--scenario", "framepipe",
    "--python", $pythonExe,
    "--engine", $engineScript,
    "--work-dir", $runDir,
    "--contracts", $contractsDir,
    "--frame-raw", $rawPath,
    "--frame-meta", $metaPath,
    "--out", $resultPath,
    "--trace", $tracePath
)
if ($EngineFault) {
    $hostArgs += @("--engine-fault", $EngineFault)
}

Write-Output "候选运行目录：$runDir"
Write-Output "输入素材：$sourceImage"
Write-Output "真实输入动作：关闭（回放/受控帧，仅观察）"
& $hostExe @hostArgs
exit $LASTEXITCODE
