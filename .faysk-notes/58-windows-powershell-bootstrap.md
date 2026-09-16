# Issue #107 — Windows / PowerShell Bootstrap Commands

**Purpose:** PowerShell-native companion to `56-local-environment-bootstrap.md`.  
**Production impact:** none.

Use this when preparing the contributor machine from Windows PowerShell. It avoids translating Bash loops by hand and avoids overwriting an existing local `.env`.

---

## 1. Tool versions first

From a normal PowerShell terminal:

```powershell
git --version
docker --version
docker compose version
uv --version
python --version
node --version
pnpm --version
```

Compatibility target for the reviewed revision:

```text
Python >= 3.12
Node 22 is the CI reference
pnpm 11.x is the current CI family
Docker Compose v2
```

Do not collect performance evidence until exact versions are recorded.

---

## 2. Checkout and remotes

```powershell
git clone https://github.com/Faysk/inalpha.git
Set-Location .\inalpha

git remote add upstream https://github.com/mirror29/inalpha.git
git fetch upstream main
git fetch origin notes/issue-107
git checkout fix/data-service-saturation

git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse upstream/main
```

Required before materializing diagnostics:

```text
branch = fix/data-service-saturation
working tree = clean
HEAD == upstream/main
```

If the SHAs differ, stop. Do not automatically reset contributor work.

---

## 3. Create local env files without overwriting existing ones

From the repository root:

```powershell
if (-not (Test-Path .\.env)) {
    Copy-Item .\.env.example .\.env
}
else {
    Write-Host "root .env already exists; leaving it unchanged"
}

if (-not (Test-Path .\infra\.env)) {
    Copy-Item .\infra\.env.example .\infra\.env
}
else {
    Write-Host "infra/.env already exists; leaving it unchanged"
}
```

Do not paste secrets into contributor notes or benchmark result files.

The benchmark does not need a real FRED key because the contributor wrapper installs a fake `fred` venue for the relevant scenarios.

---

## 4. Sync repository dependencies

Orchestration:

```powershell
Push-Location .\packages\orchestration
try {
    pnpm install
}
finally {
    Pop-Location
}
```

Python services:

```powershell
$services = @("data", "paper", "research", "factor", "evolver")
foreach ($service in $services) {
    Push-Location ".\services\$service"
    try {
        uv sync
    }
    finally {
        Pop-Location
    }
}
```

Migrations environment:

```powershell
Push-Location .\infra\migrations
try {
    uv sync
}
finally {
    Pop-Location
}
```

Do not start all application services with `scripts/dev.sh` for the first #107 diagnostics. We need explicit worker counts.

---

## 5. Start infrastructure only

```powershell
Push-Location .\infra
try {
    docker compose up -d
    docker compose ps
}
finally {
    Pop-Location
}
```

Expected local defaults from the repository templates:

```text
postgres container = inalpha-postgres
postgres user      = quant
normal DB          = inalpha
host port          = 5433
redis host port    = 6379
```

Wait for Postgres to be healthy before creating the benchmark DB.

---

## 6. Create `inalpha_issue107` only if absent

```powershell
Push-Location .\infra
try {
    $exists = docker compose exec -T postgres psql -U quant -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='inalpha_issue107';"
    if (($exists | Out-String).Trim() -ne "1") {
        docker compose exec -T postgres createdb -U quant inalpha_issue107
        if ($LASTEXITCODE -ne 0) {
            throw "failed to create inalpha_issue107"
        }
    }
    else {
        Write-Host "inalpha_issue107 already exists"
    }
}
finally {
    Pop-Location
}
```

This database is intentionally separate from ordinary local development data.

---

## 7. Point only the current shell at the benchmark DB

With repository defaults:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107"
$env:ISSUE107_DATABASE_URL = $env:DATABASE_URL
```

This process-level environment value takes precedence over the fallback loaded from `infra/.env` by Alembic.

Do **not** rewrite the ordinary root `.env` to make benchmark resets convenient.

---

## 8. Apply migrations to the benchmark DB

```powershell
Push-Location .\infra\migrations
try {
    uv run alembic upgrade head
}
finally {
    Pop-Location
}
```

Then verify without changing data:

```powershell
Push-Location .\infra
try {
    docker compose exec -T postgres psql -U quant -d inalpha_issue107 -Atc "SELECT current_database(), coalesce(to_regclass('public.bars')::text, '');"
}
finally {
    Pop-Location
}
```

Expected output contains:

```text
inalpha_issue107
bars
```

or `public.bars` depending on PostgreSQL formatting.

---

## 9. Only then materialize contributor diagnostics

Read the current helper directly from the notes ref instead of switching the production branch to the notes branch.

A convenient one-time local copy can be made with `git show`, for example:

```powershell
git show origin/notes/issue-107:.faysk-notes/tools/prepare_issue107_local.ps1 > $env:TEMP\prepare_issue107_local.ps1
```

If PowerShell redirection changes encoding in the local shell/version, prefer copying the file through your editor or use the raw notes branch checkout separately. The helper itself writes materialized files as UTF-8 without BOM.

Run the helper only while the production checkout is still clean and exactly at `upstream/main`.

The current helper will then:

```text
fetch upstream + notes
verify branch/SHA
refuse tracked/existing destinations
materialize contributor files as untracked
syntax-parse materialized Python/PowerShell tooling
print git status and tool versions
```

After materialization, only the expected contributor diagnostics should appear as untracked files.

---

## 10. Windows shell split

Use PowerShell for:

```text
Docker Desktop interaction
environment variables
benchmark DB helper
capture-env helper
service startup commands
```

Use Git Bash or WSL for repository commands that are explicitly Bash-only, such as:

```text
bash scripts/check-consistency.sh
```

Do not silently replace a Bash repository check with a different Windows command and call it equivalent.

---

## 11. Ready-state checkpoint

Environment setup is ready for Stage A when:

```text
[ ] Docker Desktop/engine reachable
[ ] branch is fix/data-service-saturation
[ ] HEAD == upstream/main
[ ] root + infra env files exist without accidental overwrite
[ ] pnpm dependencies installed
[ ] five Python service environments synced
[ ] migration environment synced
[ ] Postgres + Redis healthy
[ ] inalpha_issue107 exists
[ ] migrations at head
[ ] public.bars exists in inalpha_issue107
[ ] current benchmark shell exports benchmark DATABASE_URL
[ ] no #107 load has been generated
```

Then continue with `11-local-test-runbook.md`, not with ad-hoc manual load.
