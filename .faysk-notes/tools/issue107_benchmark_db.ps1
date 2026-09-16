param(
    [ValidateSet("verify", "reset-bars")]
    [string]$Action = "verify"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedDatabase = "inalpha_issue107"
$PostgresUser = "quant"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Invoke-ComposePsql([string]$Sql, [switch]$TuplesOnly) {
    $args = @(
        "compose", "exec", "-T", "postgres",
        "psql", "-U", $PostgresUser, "-d", $ExpectedDatabase,
        "-v", "ON_ERROR_STOP=1"
    )
    if ($TuplesOnly) {
        $args += "-Atc"
    }
    else {
        $args += "-c"
    }
    $args += $Sql

    $output = & docker @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose psql failed:`n$($output | Out-String)"
    }
    return (($output | Out-String).Trim())
}

Require-Command git
Require-Command docker

$repoRoot = (& git rev-parse --show-toplevel 2>&1 | Select-Object -First 1).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw "Run this helper from inside the Inalpha checkout."
}

$infraDir = Join-Path $repoRoot "infra"
if (-not (Test-Path (Join-Path $infraDir "docker-compose.yml"))) {
    throw "infra/docker-compose.yml not found under repository root: $repoRoot"
}

Push-Location $infraDir
try {
    $running = & docker compose ps --status running --services 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose ps failed:`n$($running | Out-String)"
    }
    if (-not ($running -contains "postgres")) {
        throw "The infra postgres service is not running. Start it before using this helper."
    }

    # The database name is deliberately hard-coded. This helper must never accept an arbitrary DB
    # name for a destructive benchmark reset.
    $actualDatabase = Invoke-ComposePsql "select current_database();" -TuplesOnly
    if ($actualDatabase -ne $ExpectedDatabase) {
        throw "Safety check failed: expected database '$ExpectedDatabase', psql reports '$actualDatabase'."
    }

    $barsRegclass = Invoke-ComposePsql "select coalesce(to_regclass('public.bars')::text, '');" -TuplesOnly
    $barsReady = $barsRegclass -eq "bars"

    Write-Host "benchmark_database=$actualDatabase"
    Write-Host "bars_table_ready=$barsReady"

    if (-not $barsReady) {
        if ($Action -eq "reset-bars") {
            throw "public.bars does not exist in $ExpectedDatabase. Apply current migrations first."
        }
        Write-Host "Database identity is correct; migrations still need to create public.bars."
        exit 0
    }

    $before = Invoke-ComposePsql "select count(*) from public.bars;" -TuplesOnly
    Write-Host "bars_count_before=$before"

    if ($Action -eq "verify") {
        Write-Host "verify only: no data changed"
        exit 0
    }

    Write-Host "Resetting ONLY public.bars in the dedicated benchmark database..."
    [void](Invoke-ComposePsql "TRUNCATE TABLE public.bars;")

    $after = Invoke-ComposePsql "select count(*) from public.bars;" -TuplesOnly
    Write-Host "bars_count_after=$after"
    if ($after -ne "0") {
        throw "Reset verification failed: public.bars count is '$after', expected 0."
    }

    Write-Host "benchmark bars reset complete"
}
finally {
    Pop-Location
}
