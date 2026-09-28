$ErrorActionPreference = 'Stop'
$taskRoot = 'D:\yihuanpaimai'
$taskRecovery = 'D:\yihuanpaimai-recovery'
$taskBranches = @('D:\yihuanpaimai-v2-2a','D:\yihuanpaimai-v2-2b','D:\yihuanpaimai-v2-2c')
$taskIntegration = 'D:\yihuanpaimai-v2-2-integration'
$taskAllowed = @($taskRoot,$taskRecovery,$taskIntegration,'D:\yihuanpaimai-private','D:\video') + $taskBranches
$taskExternal = @(Get-ChildItem -LiteralPath 'D:\' -Directory | Where-Object { $_.Name -match '^(v2-2b-|v22b-)' })
$taskAllowed += @($taskExternal.FullName)
$taskLog = [System.Collections.Generic.List[object]]::new()

function Assert-TaskPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $ok = $false
    foreach ($root in $taskAllowed) {
        if ($full -eq $root -or $full.StartsWith($root + '\',[StringComparison]::OrdinalIgnoreCase)) { $ok = $true; break }
    }
    if (-not $ok -or $full -eq 'D:') { throw "Outside explicit task paths: $full" }
    return $full
}
function Remove-TaskTree([string]$Path) {
    $full = Assert-TaskPath $Path
    if (-not (Test-Path -LiteralPath $full)) { return }
    $item = Get-Item -Force -LiteralPath $full
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refuse recursive deletion of link: $full" }
    $links = @(Get-ChildItem -LiteralPath $full -Force -Recurse -Attributes ReparsePoint -ErrorAction Stop)
    if ($links.Count) { throw "Refuse tree containing links: $full" }
    Remove-Item -LiteralPath $full -Recurse -Force
    $taskLog.Add(@{action='delete';path=$full})
}
function Move-TaskTree([string]$Source,[string]$Destination) {
    $src = Assert-TaskPath $Source
    $dst = Assert-TaskPath $Destination
    if (Test-Path -LiteralPath $dst) { throw "Destination exists: $dst" }
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Move-Item -LiteralPath $src -Destination $dst
    $taskLog.Add(@{action='move';source=$src;destination=$dst})
}
function Merge-TaskTree([string]$Source,[string]$Destination,[bool]$Authoritative=$false) {
    $src = Assert-TaskPath $Source
    $dst = Assert-TaskPath $Destination
    if (-not (Test-Path -LiteralPath $dst)) { Move-TaskTree $src $dst; return }
    if (-not (Get-Item -Force -LiteralPath $src).PSIsContainer) {
        $same = (Get-FileHash -LiteralPath $src).Hash -eq (Get-FileHash -LiteralPath $dst).Hash
        if (-not $same -and -not $Authoritative) { throw "Unresolved file collision: $dst" }
        if (-not $same) { Copy-Item -LiteralPath $src -Destination $dst -Force }
        Remove-Item -LiteralPath $src -Force
        return
    }
    foreach ($item in @(Get-ChildItem -LiteralPath $src -Force)) {
        $target = Join-Path $dst $item.Name
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected link: $($item.FullName)" }
        if ($item.PSIsContainer) { Merge-TaskTree $item.FullName $target $Authoritative }
        elseif (-not (Test-Path -LiteralPath $target)) { Move-Item -LiteralPath $item.FullName -Destination $target }
        else {
            $same = (Get-FileHash -LiteralPath $item.FullName).Hash -eq (Get-FileHash -LiteralPath $target).Hash
            if (-not $same -and -not $Authoritative) { throw "Unresolved unique file collision: $target" }
            if (-not $same) { Copy-Item -LiteralPath $item.FullName -Destination $target -Force }
            Remove-Item -LiteralPath $item.FullName -Force
        }
    }
    Remove-Item -LiteralPath $src -Force
}

# The current integration contains the exact accepted A/B/C trees. Preserve
# their commit histories in the healthy repository before dropping clones.
foreach ($branchRoot in $taskBranches) {
    $status = @(git -C $branchRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0 -or $status.Count) { throw "Tracked changes in $branchRoot" }
}
if ((git -C $taskRecovery rev-parse HEAD).Trim() -ne 'cb86697c976a0658f5e301f5e199b269f26a14e6') { throw 'Unexpected integration HEAD' }

# Remove only the confirmed junction, never its live Python environment target.
$venvLink = Join-Path $taskRecovery 'build\takeover_20260905\repro-venv'
if (Test-Path -LiteralPath $venvLink) {
    $link = Get-Item -Force -LiteralPath $venvLink
    if ($link.LinkType -ne 'Junction' -or $link.Target -ne 'D:\yihuanpaimai\build\takeover_20260905\repro-venv') { throw 'Unexpected environment link' }
    [IO.Directory]::Delete((Assert-TaskPath $venvLink))
}

# Preserve actual branch evidence and ignored diagnostic text, not redundant code trees.
foreach ($branchRoot in $taskBranches) {
    $branchBuild = Join-Path $branchRoot 'build'
    if (Test-Path -LiteralPath $branchBuild) {
        foreach ($entry in @(Get-ChildItem -LiteralPath $branchBuild -Force)) {
            $target = Join-Path $taskRoot ('build\' + $entry.Name)
            if (Test-Path -LiteralPath $target) { $target = Join-Path $taskRoot ('build\evidence\' + (Split-Path $branchRoot -Leaf) + '\' + $entry.Name) }
            Move-TaskTree $entry.FullName $target
        }
    }
    $raw = Join-Path $branchRoot 'tools\v2\evidence_raw'
    if (Test-Path -LiteralPath $raw) { Move-TaskTree $raw (Join-Path $taskRoot ('build\evidence\' + (Split-Path $branchRoot -Leaf) + '\raw')) }
}

# A registered worktree must be deregistered while its original common Git exists.
$integrationPath = Assert-TaskPath $taskIntegration
git -C $taskRecovery worktree remove --force $integrationPath
if ($LASTEXITCODE -ne 0) { throw 'Cannot deregister integration worktree' }
$taskLog.Add(@{action='remove_duplicate_worktree';path=$integrationPath})

# Latest source is authoritative; leave original unique assets, evidence, history,
# and the real Python environment at their existing paths.
foreach ($entry in @(Get-ChildItem -LiteralPath $taskRecovery -Force)) {
    if ($entry.Name -in @('.git','_forensic')) { continue }
    Merge-TaskTree $entry.FullName (Join-Path $taskRoot $entry.Name) ($entry.Name -ne 'build')
}
Remove-TaskTree (Join-Path $taskRoot '.git')
Move-TaskTree (Join-Path $taskRecovery '.git') (Join-Path $taskRoot '.git')

# External evidence is moved into the project; disposable builds/old backups removed.
foreach ($entry in $taskExternal) {
    if ($entry.Name -match 'build|input-backup|live-prep') { Remove-TaskTree $entry.FullName }
    else { Move-TaskTree $entry.FullName (Join-Path $taskRoot ('build\evidence\' + $entry.Name)) }
}
if (Test-Path -LiteralPath 'D:\yihuanpaimai-private') { Move-TaskTree 'D:\yihuanpaimai-private' (Join-Path $taskRoot 'data\reference-crops') }
if (Test-Path -LiteralPath 'D:\video') { Move-TaskTree 'D:\video' (Join-Path $taskRoot 'data\videos') }
foreach ($branchRoot in $taskBranches) { Remove-TaskTree $branchRoot }
Remove-TaskTree $taskRecovery

$reportDir = Join-Path $taskRoot 'build\workspace-consolidation'
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$taskLog | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportDir 'actions.json') -Encoding utf8
Write-Output "Consolidated $($taskLog.Count) directory actions into $taskRoot"
