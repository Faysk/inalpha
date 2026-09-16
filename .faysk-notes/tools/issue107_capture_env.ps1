param(
    [ValidateSet("baseline", "candidate")]
    [string]$Kind = "baseline",
    [string]$Label = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Git([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs) {
    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed:`n$output"
    }
    return $output
}

function Command-Version([string]$Name, [string[]]$VersionArgs = @("--version")) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        return "$Name=NOT_FOUND"
    }
    try {
        $out = & $Name @VersionArgs 2>&1
        return "$Name=$(($out | Out-String).Trim())"
    }
    catch {
        return "$Name=ERROR:$($_.Exception.Message)"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required"
}

$repoRoot = (Invoke-Git rev-parse --show-toplevel | Select-Object -First 1).Trim()
$repoParent = Split-Path -Parent $repoRoot

$branch = (Invoke-Git branch --show-current | Select-Object -First 1).Trim()
$head = (Invoke-Git rev-parse HEAD | Select-Object -First 1).Trim()

$upstream = "UNAVAILABLE"
try {
    $upstream = (Invoke-Git rev-parse upstream/main | Select-Object -First 1).Trim()
}
catch {
    $upstream = "UNAVAILABLE"
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$safeLabel = ($Label -replace '[^A-Za-z0-9._-]', '-').Trim('-')
$sessionName = "$stamp-$Kind"
if ($safeLabel) {
    $sessionName += "-$safeLabel"
}

$outputRoot = Join-Path $repoParent "inalpha-issue107-results"
$sessionDir = Join-Path $outputRoot $sessionName
New-Item -ItemType Directory -Path $sessionDir -Force | Out-Null

$manifest = [System.Collections.Generic.List[string]]::new()
$manifest.Add("Inalpha issue #107 runtime evidence session")
$manifest.Add("date_local=$((Get-Date).ToString('o'))")
$manifest.Add("kind=$Kind")
$manifest.Add("label=$safeLabel")
$manifest.Add("branch=$branch")
$manifest.Add("head=$head")
$manifest.Add("upstream_main=$upstream")
$manifest.Add("head_equals_upstream=$($head -eq $upstream)")
$manifest.Add("")

$manifest.Add("[git_status_short]")
$status = & git -C $repoRoot status --short 2>&1
if ($LASTEXITCODE -ne 0) {
    $manifest.Add("ERROR: git status failed")
}
elseif ($status) {
    foreach ($line in $status) { $manifest.Add([string]$line) }
}
else {
    $manifest.Add("clean")
}
$manifest.Add("")

$manifest.Add("[tool_versions]")
$manifest.Add((Command-Version "git" @("--version")))
$manifest.Add((Command-Version "docker" @("--version")))
if (Get-Command docker -ErrorAction SilentlyContinue) {
    try {
        $compose = & docker compose version 2>&1
        $manifest.Add("docker_compose=$(($compose | Out-String).Trim())")
    }
    catch {
        $manifest.Add("docker_compose=ERROR:$($_.Exception.Message)")
    }
}
$manifest.Add((Command-Version "uv" @("--version")))
$manifest.Add((Command-Version "python" @("--version")))
$manifest.Add((Command-Version "node" @("--version")))
$manifest.Add((Command-Version "pnpm" @("--version")))
$manifest.Add("")

$manifest.Add("[host_summary]")
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $manifest.Add("os_caption=$($os.Caption)")
    $manifest.Add("os_version=$($os.Version)")
    $manifest.Add("os_build=$($os.BuildNumber)")
    $ramGiB = [math]::Round([double]$os.TotalVisibleMemorySize / 1MB, 2)
    $manifest.Add("ram_gib=$ramGiB")
}
catch {
    $manifest.Add("os=UNAVAILABLE")
}

try {
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $manifest.Add("cpu=$($cpu.Name)")
    $manifest.Add("logical_processors=$($cpu.NumberOfLogicalProcessors)")
}
catch {
    $manifest.Add("cpu=UNAVAILABLE")
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    try {
        $dockerSummary = & docker info --format 'server_version={{.ServerVersion}} cpus={{.NCPU}} memory_bytes={{.MemTotal}}' 2>&1
        if ($LASTEXITCODE -eq 0) {
            $manifest.Add("docker_runtime=$(($dockerSummary | Out-String).Trim())")
        }
        else {
            $manifest.Add("docker_runtime=UNAVAILABLE")
        }
    }
    catch {
        $manifest.Add("docker_runtime=UNAVAILABLE")
    }
}

$manifest.Add("")
$manifest.Add("[benchmark_constants_to_fill_manually]")
$manifest.Add("benchmark_db=inalpha_issue107")
$manifest.Add("data_workers=")
$manifest.Add("factor_workers=")
$manifest.Add("provider_mode=")
$manifest.Add("provider_delay_s=")
$manifest.Add("fake_bars_per_fetch=")
$manifest.Add("factor_cache=cold|warm")
$manifest.Add("data_bars=cold|warm")
$manifest.Add("scenario=")

$manifestPath = Join-Path $sessionDir "00-environment.txt"
[System.IO.File]::WriteAllLines(
    $manifestPath,
    $manifest,
    [System.Text.UTF8Encoding]::new($false)
)

$notesPath = Join-Path $sessionDir "notes.md"
$notes = @"
# Issue #107 evidence notes

Session: $sessionName

Do not paste secrets or full environment dumps here.

## Scenario notes

- 

## Unexpected observations

- 

## Negative evidence / hypotheses weakened

- 
"@
[System.IO.File]::WriteAllText(
    $notesPath,
    $notes,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Created evidence session:"
Write-Host $sessionDir
Write-Host ""
Write-Host "Environment manifest:"
Write-Host $manifestPath
Write-Host ""
if ($Kind -eq "baseline" -and $upstream -ne "UNAVAILABLE" -and $head -ne $upstream) {
    Write-Warning "Baseline HEAD differs from upstream/main. Review/rebase deliberately before using this session as the official baseline."
}
Write-Host "Capture a command without losing console output with, for example:"
Write-Host "  <command> 2>&1 | Tee-Object -FilePath (Join-Path '$sessionDir' 'A-data-tests.txt')"
Write-Host ""
Write-Host "This helper never records environment variable values and never uploads results."
