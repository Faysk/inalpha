# Issue #107 — Local Environment Bootstrap

**Status:** execution-prep companion to `11-local-test-runbook.md`.  
**Production impact:** none.

This note exists to make contributor-machine setup boring and reproducible. It does **not** generate benchmark load and does not select a production fix.

---

## 1. Toolchain target

Use the repository's current requirements and CI versions as the compatibility target:

```text
Git
Docker + docker compose
Python >= 3.12
uv
Node 22
pnpm 11.x
```

The Python service projects require Python 3.12+, and current CI runs Node 22 with pnpm 11.x for the TypeScript workspaces.

Record exact local versions before collecting performance evidence.

---

## 2. Checkout gate

Work only from the contribution branch:

```text
Faysk/inalpha:fix/data-service-saturation
```

Recommended initial commands:

```bash
git clone https://github.com/Faysk/inalpha.git
cd inalpha
git remote add upstream https://github.com/mirror29/inalpha.git
git fetch upstream main
git fetch origin notes/issue-107
git checkout fix/data-service-saturation

git status --short
git rev-parse HEAD
git rev-parse upstream/main
```

Before baseline diagnostics:

```text
working tree = clean
HEAD == upstream/main
```

Do not automatically reset/rebase if this is false. Inspect first.

---

## 3. Ordinary repository dependencies

Follow `CONTRIBUTING.md` rather than introducing a contributor-specific dependency layout.

### Bash / WSL

```bash
cd packages/orchestration
pnpm i
cd ../..

for service in data paper research factor evolver; do
  (cd "services/$service" && uv sync)
done

cp .env.example .env
cp infra/.env.example infra/.env
```

### PowerShell

```powershell
Push-Location packages/orchestration
pnpm i
Pop-Location

foreach ($service in @("data", "paper", "research", "factor", "evolver")) {
    Push-Location "services/$service"
    uv sync
    Pop-Location
}

Copy-Item .env.example .env
Copy-Item infra/.env.example infra/.env
```

If `.env` files already exist, inspect them instead of blindly overwriting local configuration.

For this issue we later exercise mainly `data` and `factor`, but keeping the repository's documented setup avoids an environment that only works for our harness.

Do not place secrets in the notes/results tree.

---

## 4. Start only infrastructure first

Start Postgres/TimescaleDB and Redis from the repository compose:

```bash
cd infra
docker compose up -d
docker compose ps
cd ..
```

Repository local defaults are currently:

```text
Postgres user = quant
Postgres DB   = inalpha
Host port     = 5433
Redis port    = 6379
```

The Postgres image is TimescaleDB on PostgreSQL 17.

Do **not** run `scripts/dev.sh` yet for the capacity investigation. The runtime tests need explicit service worker counts and contributor wrappers.

---

## 5. Create the dedicated benchmark database

The benchmark database name is fixed:

```text
inalpha_issue107
```

Never repurpose the normal `inalpha` development database for destructive cold-state resets.

### PowerShell

From `infra/`:

```powershell
$exists = docker compose exec -T postgres psql -U quant -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='inalpha_issue107';"
if (($exists | Out-String).Trim() -ne "1") {
    docker compose exec -T postgres createdb -U quant inalpha_issue107
}
```

### Bash / WSL

From `infra/`:

```bash
if ! docker compose exec -T postgres \
  psql -U quant -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='inalpha_issue107';" \
  | grep -qx 1; then
  docker compose exec -T postgres createdb -U quant inalpha_issue107
fi
```

These commands only create the fixed benchmark DB when it is absent.

---

## 6. Migrate the benchmark database

The Alembic environment reads `DATABASE_URL` from the process environment, with `infra/.env` as the fallback. For benchmark migration, set the process variable explicitly so the ordinary `infra/.env` can remain pointed at the normal development DB.

Benchmark URL with repository defaults:

```text
postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107
```

### PowerShell

```powershell
$env:DATABASE_URL = "postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107"
$env:ISSUE107_DATABASE_URL = $env:DATABASE_URL

Push-Location infra/migrations
uv sync
uv run alembic upgrade head
Pop-Location
```

### Bash / WSL

```bash
export DATABASE_URL='postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107'
export ISSUE107_DATABASE_URL="$DATABASE_URL"

(
  cd infra/migrations
  uv sync
  uv run alembic upgrade head
)
```

The initial migration enables `timescaledb` and `pgcrypto`, so the dedicated DB receives the same schema capabilities as the normal development DB.

Important:

```text
root .env may stay on ordinary inalpha
shell DATABASE_URL points benchmark processes at inalpha_issue107
```

When the shell/session is restarted, re-export the benchmark `DATABASE_URL` before starting contributor data-service wrappers or any benchmark command that relies on service settings.

---

## 7. No-load verification

Before materializing or running any issue-specific load tool, verify infrastructure and schema only.

### Bash / WSL

From `infra/`:

```bash
docker compose ps
docker compose exec -T postgres \
  psql -U quant -d inalpha_issue107 -Atc \
  "SELECT current_database(), coalesce(to_regclass('public.bars')::text, '');"
```

### PowerShell

From `infra/`:

```powershell
docker compose ps
docker compose exec -T postgres psql -U quant -d inalpha_issue107 -Atc "SELECT current_database(), coalesce(to_regclass('public.bars')::text, '');"
```

Expected database identity:

```text
inalpha_issue107
```

and `public.bars`/`bars` must exist after migrations.

At this point there should still be **no benchmark traffic**.

---

## 8. Capture environment metadata

Before the baseline, record at minimum:

```text
git --version
docker --version
docker compose version
uv --version
python --version
node --version
pnpm --version
branch
HEAD
upstream/main
OS / WSL version
CPU / RAM
explicit Docker resource limits, if any
```

After contributor helpers are safely materialized, `scripts/issue107_capture_env.ps1` can create the evidence-session directory outside the Git working tree.

Do not dump the whole environment: it can contain keys/tokens.

---

## 9. Handoff point

Environment preparation is complete when all of these are true:

```text
[ ] fix/data-service-saturation checked out
[ ] working tree clean before diagnostic materialization
[ ] HEAD == fresh upstream/main
[ ] repository dependencies synced
[ ] infra postgres + redis healthy
[ ] inalpha_issue107 exists
[ ] migrations are at head on inalpha_issue107
[ ] benchmark DATABASE_URL is known/exportable
[ ] no issue107 load has been generated yet
```

Then return to the authoritative runtime sequence:

```text
11-local-test-runbook.md
→ materialize contributor diagnostics
→ safety checks
→ Stage A
→ B ... O
```

---

## Working-principle checkpoint

Environment setup must not silently change the experiment.

In particular:

```text
normal dev DB != benchmark DB
normal app startup != capacity-test startup
real provider traffic != benchmark provider traffic
```

The goal here is only to make the runtime baseline safe, isolated and reproducible.