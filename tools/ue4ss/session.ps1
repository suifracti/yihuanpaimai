# Preparation only. Install/Remove must be run by the separately authorized field operator.
param([ValidateSet('Check','Install','Remove')][string]$Action = 'Check', [Parameter(Mandatory=$true)][string]$GameDir)
$ErrorActionPreference = 'Stop'
$probeRoot = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'build\ue4ss'
$gameDir = [IO.Path]::GetFullPath($GameDir)
$loader = Join-Path $gameDir 'dwmapi.dll'
$hostDir = Join-Path $gameDir 'ue4ss'
$receiptPath = Join-Path $probeRoot 'results\installation-receipt.json'
$manifest = Get-Content -LiteralPath (Join-Path $probeRoot 'payload-manifest.json') -Raw | ConvertFrom-Json
if ($Action -eq 'Check') {
    $names = @('HTGame.exe','dwmapi.dll','ue4ss','UE4SS.dll','UE4SS-settings.ini','Mods',
               'd3d12.dll','dxgi.dll','dinput8.dll','dsound.dll','version.dll','winmm.dll','plugins','HTGameBase.dll')
    $rows = foreach ($name in $names) {
        $path = Join-Path $gameDir $name
        $item = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
        [ordered]@{ name=$name; path=$path; exists=($null -ne $item)
            type=if ($item -and $item.PSIsContainer) {'directory'} elseif ($item) {'file'} else {$null}
            bytes=if ($item -and -not $item.PSIsContainer) {$item.Length} else {$null} }
    }
    $plugins = @(Get-ChildItem -LiteralPath (Join-Path $gameDir 'plugins') -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
    [ordered]@{ checkedUtc=[DateTime]::UtcNow.ToString('o'); gameDir=$gameDir
        sameNameConflict=((Test-Path -LiteralPath $loader) -or (Test-Path -LiteralPath $hostDir))
        entries=@($rows); existingPluginFiles=$plugins; runtimeCoexistence='NOT_TESTED' } | ConvertTo-Json -Depth 5
    return
}
if (Get-Process -Name HTGame -ErrorAction SilentlyContinue) { throw 'Exit HTGame normally before installation or removal.' }
if (-not (Test-Path -LiteralPath (Join-Path $gameDir 'HTGame.exe'))) { throw 'Expected HTGame directory not found.' }
if ($Action -eq 'Install') {
    if ((Test-Path -LiteralPath $loader) -or (Test-Path -LiteralPath $hostDir)) {
        throw 'dwmapi.dll or ue4ss already exists. Do not overwrite, rename, or remove existing loaders.'
    }
    foreach ($entry in $manifest) {
        $source = Join-Path (Join-Path $probeRoot 'payload') $entry.path
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $entry.sha256) { throw "Payload mismatch: $($entry.path)" }
    }
    # Record absent targets before copy, so even an interrupted copy has an ownership record.
    [ordered]@{ gameDir=$gameDir; loader=$loader; hostDir=$hostDir; createdUtc=[DateTime]::UtcNow.ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $probeRoot 'payload\dwmapi.dll') -Destination $loader
    Copy-Item -LiteralPath (Join-Path $probeRoot 'payload\ue4ss') -Destination $hostDir -Recurse
    Write-Output 'Installed only dwmapi.dll and ue4ss/. No process was launched. Follow FIELD-VALIDATION.md.'
    return
}
if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'No installation receipt; do not delete anything by guessing.' }
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.gameDir -ne $gameDir -or $receipt.loader -ne $loader -or $receipt.hostDir -ne $hostDir) { throw 'Receipt target mismatch.' }
$resolvedGame = (Resolve-Path -LiteralPath $gameDir).Path.TrimEnd('\')
foreach ($target in @($loader,$hostDir)) {
    $absolute = [IO.Path]::GetFullPath($target)
    if ([IO.Path]::GetDirectoryName($absolute) -ne $resolvedGame) { throw "Removal target outside expected directory: $absolute" }
    $item = Get-Item -LiteralPath $absolute -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Refuse a replaced link/junction.' }
}
if (Test-Path -LiteralPath $loader) {
    $expectedLoader = $manifest | Where-Object path -eq 'dwmapi.dll'
    if ((Get-FileHash -LiteralPath $loader -Algorithm SHA256).Hash -ne $expectedLoader.sha256) { throw 'Loader has changed; leave it for the operator.' }
}
# Refuse removal if another mod has since been added. Host-generated logs/cache remain allowed.
$extraMods = @(Get-ChildItem -LiteralPath (Join-Path $hostDir 'Mods') -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notin @('NteObjectReadProbe','mods.txt') })
if ($extraMods.Count) { throw 'Other mods were added after installation; leave the directory for the operator.' }
# Keep the host log in project build/ before removing this newly-created host directory.
$hostLog = Join-Path $hostDir 'UE4SS.log'
if (Test-Path -LiteralPath $hostLog) {
    $savedLog = Join-Path $probeRoot ('results\UE4SS-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '.log')
    Copy-Item -LiteralPath $hostLog -Destination $savedLog
}
if (Test-Path -LiteralPath $loader) { Remove-Item -LiteralPath $loader }
if (Test-Path -LiteralPath $hostDir) { Remove-Item -LiteralPath $hostDir -Recurse }
Remove-Item -LiteralPath $receiptPath
Write-Output 'Removed this session loader and host directory. Existing d3d12.dll/plugins were untouched.'
