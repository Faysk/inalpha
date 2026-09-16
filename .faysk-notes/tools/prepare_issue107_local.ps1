param(
    [switch]$Cleanup
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedBranch = "fix/data-service-saturation"
$NotesRef = "origin/notes/issue-107"

$Files = [ordered]@{
    ".faysk-notes/tools/test_macro_cache_stampede_draft.py" = "services/factor/tests/test_issue107_macro_stampede_local.py"
    ".faysk-notes/tools/test_factor_live_cache_stampede_draft.py" = "services/factor/tests/test_issue107_live_cache_stampede_local.py"
    ".faysk-notes/tools/test_backfill_pool_pressure_draft.py" = "services/data/tests/test_issue107_pool_pressure_local.py"
    ".faysk-notes/tools/issue107_slow_data_app.py" = "services/data/issue107_slow_data_app.py"
    ".faysk-notes/tools/issue107_load_probe.py" = "services/data/issue107_load_probe.py"
    ".faysk-notes/tools/issue107_timeout_persistence_probe.py" = "services/data/issue107_timeout_persistence_probe.py"
    ".faysk-notes/tools/issue107_factor_app.py" = "services/factor/issue107_factor_app.py"
    ".faysk-notes/tools/issue107_factor_macro_probe.py" = "services/factor/issue107_factor_macro_probe.py"
    ".faysk-notes/tools/issue107_runner_poll_probe.py" = "services/factor/issue107_runner_poll_probe.py"
    ".faysk-notes/tools/issue107_mixed_workload_probe.py" = "services/factor/issue107_mixed_workload_probe.py"
    ".faysk-notes/tools/issue107_target_check.py" = "services/factor/issue107_target_check.py"
    ".faysk-notes/tools/issue107_capture_env.ps1" = "scripts/issue107_capture_env.ps1"
    ".faysk-notes/tools/issue107_benchmark_db.ps1" = "scripts/issue107_benchmark_db.ps1"
    ".faysk-notes/tools/issue107_benchmark_db.sh" = "scripts/issue107_benchmark_db.sh"
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Invoke-Git([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args) {
    $output = & git @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed:`n$output"
    }
    return $output
}

function Assert-Untracked([string]$Path) {
    & git ls-files --error-unmatch -- $Path *> $null
    if ($LASTEXITCODE -eq 0) {
        throw "Refusing to touch tracked file: $Path"
    }
}

Require-Command git

$repoRoot = (Invoke-Git rev-parse --show-toplevel | Select-Object -First 1).Trim()
Set-Location $repoRoot

$branch = (Invoke-Git branch --show-current | Select-Object -First 1).Trim()
if ($branch -ne $ExpectedBranch) {
    throw "Expected branch '$ExpectedBranch', current branch is '$branch'."
}

if ($Cleanup) {
    foreach ($destination in $Files.Values) {
        if (-not (Test-Path $destination)) {
            continue
        }
        Assert-Untracked $destination
        Remove-Item -LiteralPath $destination -Force
        Write-Host "removed $destination"
    }
    Write-Host ""
    Write-Host "Remaining git status:"
    & git status --short
    exit 0
}

$statusBefore = (& git status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "git status failed"
}
if ($statusBefore) {
    throw "Working tree is not clean. Preserve/commit/stash your own work before materializing diagnostics.`n$statusBefore"
}

$remotes = Invoke-Git remote
if ($remotes -notcontains "origin") {
    throw "Missing git remote 'origin' (expected Faysk/inalpha fork)."
}
if ($remotes -notcontains "upstream") {
    throw "Missing git remote 'upstream' (expected mirror29/inalpha)."
}

Write-Host "Fetching reviewed upstream baseline and contributor notes..."
Invoke-Git fetch upstream main | Out-Null
Invoke-Git fetch origin notes/issue-107 | Out-Null

$head = (Invoke-Git rev-parse HEAD | Select-Object -First 1).Trim()
$upstream = (Invoke-Git rev-parse upstream/main | Select-Object -First 1).Trim()

Write-Host "HEAD          $head"
Write-Host "upstream/main $upstream"

if ($head -ne $upstream) {
    throw "Contribution branch is not exactly at upstream/main. Do not run an old baseline against a drifted checkout; review/rebase deliberately first."
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

foreach ($entry in $Files.GetEnumerator()) {
    $source = $entry.Key
    $destination = $entry.Value

    if (Test-Path $destination) {
        throw "Refusing to overwrite existing diagnostic path: $destination"
    }
    Assert-Untracked $destination

    $parent = Split-Path -Parent $destination
    if (-not (Test-Path $parent)) {
        throw "Expected repository directory does not exist: $parent"
    }

    $content = & git show "${NotesRef}:$source" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read ${NotesRef}:$source`n$content"
    }

    # PowerShell normally joins native-command output as lines. Reconstruct with LF and write without
    # a UTF-8 BOM so Python/scripts remain byte-clean and comparable across Windows/WSL.
    $text = ($content -join "`n") + "`n"
    [System.IO.File]::WriteAllText((Join-Path $repoRoot $destination), $text, $utf8NoBom)
    Write-Host "materialized $destination"
}

Write-Host ""
Write-Host "Diagnostic/helper files are intentionally UNTRACKED:"
& git status --short

Write-Host ""
Write-Host "Tool versions / availability:"
foreach ($cmd in @("docker", "uv", "python", "node", "pnpm")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        try {
            & $cmd --version
        }
        catch {
            Write-Host "$cmd present (version query failed: $($_.Exception.Message))"
        }
    }
    else {
        Write-Host "$cmd NOT FOUND"
    }
}

Write-Host ""
Write-Host "Next: read the runbook without switching branches:"
Write-Host "  git show origin/notes/issue-107:.faysk-notes/11-local-test-runbook.md"
Write-Host "Factor/mixed benchmarks must use services/factor/issue107_factor_app.py (fail-closed data target)."
Write-Host "Before factor/mixed load, run services/factor/issue107_target_check.py."
Write-Host "Useful local helpers now materialized under scripts/:"
Write-Host "  scripts/issue107_capture_env.ps1"
Write-Host "  scripts/issue107_benchmark_db.ps1"
Write-Host "Cleanup later with: & `"$PSCommandPath`" -Cleanup"
