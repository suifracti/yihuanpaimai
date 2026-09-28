# Preview: .\scripts\cleanup-obsolete-builds.ps1
# Delete:  .\scripts\cleanup-obsolete-builds.ps1 -Delete
# No backup, no recycle bin, no additional confirmation prompt.
[CmdletBinding()]
param([switch]$Delete)

$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
if ($taskRoot -ne 'D:\yihuanpaimai') { throw "Unexpected project root: $taskRoot" }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'core\version.py'))) { throw 'Project marker missing.' }

function Get-CheckedTarget([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $full.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Outside workspace: $full" }
    $relative = $full.Substring($taskRoot.Length + 1)
    $allowed = ($relative -eq 'dist') -or
        ($relative -match '^build\\isolated_trial_[^\\]+\\(build|dist)$') -or
        ($relative -match '^(architecture|spikes)\\.+\\(bin|obj)$')
    if (-not $allowed) { throw "Not in cleanup scope: $full" }
    # Check every ancestor so a junction cannot redirect an allowed lexical path.
    $cursor = $full
    while ($cursor.Length -ge $taskRoot.Length) {
        $item = Get-Item -LiteralPath $cursor -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Link not allowed: $cursor" }
        if ($cursor -eq $taskRoot) { break }
        $cursor = Split-Path -Parent $cursor
    }
    $resolved = (Resolve-Path -LiteralPath $full).ProviderPath.TrimEnd('\')
    if (-not $resolved.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Resolved outside workspace: $resolved" }
    if (@(Get-ChildItem -LiteralPath $resolved -Force -Recurse -Attributes ReparsePoint).Count) { throw "Nested link found: $resolved" }
    return $resolved
}

$taskCandidates = [Collections.Generic.List[string]]::new()
$taskDist = Join-Path $taskRoot 'dist'
if (Test-Path -LiteralPath $taskDist -PathType Container) { $taskCandidates.Add($taskDist) }
foreach ($package in @(Get-ChildItem -LiteralPath (Join-Path $taskRoot 'build') -Directory | Where-Object Name -Like 'isolated_trial_*')) {
    foreach ($child in @('build','dist')) {
        $candidate = Join-Path $package.FullName $child
        if (Test-Path -LiteralPath $candidate -PathType Container) { $taskCandidates.Add($candidate) }
    }
}
foreach ($area in @('architecture','spikes')) {
    $areaRoot = Join-Path $taskRoot $area
    if (-not (Test-Path -LiteralPath $areaRoot)) { continue }
    # Walk explicitly and never follow a link or descend into a selected output.
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($areaRoot)
    while ($pending.Count) {
        foreach ($dir in @(Get-ChildItem -LiteralPath $pending.Pop() -Directory -Force)) {
            if ($dir.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
            if ($dir.Name -in @('bin','obj')) { $taskCandidates.Add($dir.FullName) }
            else { $pending.Push($dir.FullName) }
        }
    }
}

$taskPlan = @(
    foreach ($candidate in @($taskCandidates | Sort-Object -Unique)) {
        $checked = Get-CheckedTarget $candidate
        $files = @(Get-ChildItem -LiteralPath $checked -Recurse -Force -File)
        [pscustomobject]@{ Path=$checked; Files=$files.Count; Bytes=[long](($files | Measure-Object Length -Sum).Sum) }
    }
)
$taskPlan | Select-Object Path,Files,@{Name='GiB';Expression={[Math]::Round($_.Bytes/1GB,3)}} | Format-Table -AutoSize
$total = [long](($taskPlan | Measure-Object Bytes -Sum).Sum)
Write-Host ("Targets: {0}; total: {1:N2} GiB" -f $taskPlan.Count,($total/1GB))
if (-not $Delete) {
    Write-Host 'PREVIEW ONLY. Run with -Delete to permanently remove these generated directories. No backup will be made.'
    exit 0
}

# Refuse in-use targets. Never kill programs as part of cleanup.
$taskProcesses = @(Get-CimInstance Win32_Process)
foreach ($target in $taskPlan) {
    foreach ($proc in $taskProcesses) {
        if ($proc.ProcessId -eq $PID) { continue }
        $exe = [string]$proc.ExecutablePath
        $command = [string]$proc.CommandLine
        if (($exe -and $exe.StartsWith($target.Path + '\',[StringComparison]::OrdinalIgnoreCase)) -or
            ($command -and $command.IndexOf($target.Path,[StringComparison]::OrdinalIgnoreCase) -ge 0)) {
            throw "Target is in use by PID $($proc.ProcessId): $($target.Path). Close that program and retry."
        }
    }
}

$deleted = 0
foreach ($target in $taskPlan) {
    # Re-check absolute target, ancestors and links immediately before deletion.
    $checked = Get-CheckedTarget $target.Path
    Remove-Item -LiteralPath $checked -Recurse -Force
    if (Test-Path -LiteralPath $checked) { throw "Deletion incomplete: $checked" }
    $deleted++
    Write-Host "Deleted: $checked"
}
Write-Host ("Done. Deleted {0} directories ({1:N2} GiB measured before deletion). No backups created." -f $deleted,($total/1GB))
