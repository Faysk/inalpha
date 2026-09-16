# Issue #107 — Benchmark Database State / Determinism

**Purpose:** prevent persistent bar cache from making M1/M2/M3 or before/after measurements incomparable.

This matters because `/backfill/bars` is incremental. Running one benchmark populates the `bars` table; a later run against the same keys may only refresh the tail instead of doing the same initial persistence work.

A factor-process restart clears process-local factor caches, but it does **not** clear data-service bars in PostgreSQL.

---

## 1. The benchmark needs two separate cache dimensions

When we say “cold” or “warm”, record both:

```text
factor process cache: cold / warm
data-service DB bars: cold / warm
```

Examples:

```text
restart factor only
→ factor cache cold
→ data DB may still be warm

truncate dedicated benchmark bars only
→ data DB cold
→ factor process may still be warm
```

For reproducible cold M1/M2/M3 comparisons we generally want:

```text
factor cache cold
+ benchmark bars table cold
```

For the immediate warm control we intentionally keep both populated.

---

## 2. Use a dedicated benchmark database

Do **not** repeatedly truncate the normal developer database if it may contain useful local market data or other state.

Recommended database:

```text
inalpha_issue107
```

Connection URL with the repository's default local port:

```text
postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107
```

The repository's local migration environment respects an already-exported `DATABASE_URL`, because `load_dotenv()` does not overwrite an existing environment variable by default.

The data test fixture also uses `os.environ.setdefault`, so exporting this URL before pytest keeps the deterministic tests on the dedicated DB rather than silently forcing the ordinary `inalpha` database.

---

## 3. Create the dedicated DB

Start normal infra first:

```bash
cd infra
docker compose up -d postgres
cd ..
```

### Bash / WSL — create only if absent

```bash
if ! docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U quant -d postgres -Atc \
  "select 1 from pg_database where datname = 'inalpha_issue107';" | grep -qx '1'; then
  docker compose -f infra/docker-compose.yml exec -T postgres \
    psql -U quant -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE inalpha_issue107;"
fi
```

### PowerShell — create only if absent

```powershell
$exists = docker compose -f infra/docker-compose.yml exec -T postgres `
  psql -U quant -d postgres -Atc "select 1 from pg_database where datname = 'inalpha_issue107';"

if (($exists | Out-String).Trim() -ne '1') {
    docker compose -f infra/docker-compose.yml exec -T postgres `
      psql -U quant -d postgres -v ON_ERROR_STOP=1 `
      -c "CREATE DATABASE inalpha_issue107;"
}
```

Verify:

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U quant -d inalpha_issue107 -Atc "select current_database();"
```

Expected:

```text
inalpha_issue107
```

---

## 4. Apply current migrations to the dedicated DB

### Bash / WSL

```bash
export ISSUE107_DATABASE_URL='postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107'
(
  cd infra/migrations
  DATABASE_URL="$ISSUE107_DATABASE_URL" uv run alembic upgrade head
)
```

### PowerShell

```powershell
$env:ISSUE107_DATABASE_URL = 'postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107'
Push-Location infra/migrations
$oldDb = $env:DATABASE_URL
$env:DATABASE_URL = $env:ISSUE107_DATABASE_URL
uv run alembic upgrade head
if ($null -eq $oldDb) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue } else { $env:DATABASE_URL = $oldDb }
Pop-Location
```

Do not edit tracked `.env` files merely to point diagnostics at this database.

---

## 5. Run #107 services/tests against the dedicated DB

For the runtime session export/set:

```text
DATABASE_URL=postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107
```

before starting the data/factor services or running the #107 integration diagnostic.

The benchmark report must record the exact database name/URL **without secrets beyond the local documented dev credential**. In the notes/results, the database name is enough:

```text
benchmark DB = inalpha_issue107
```

---

## 6. Reset only benchmark bars between cold scenarios

Because the DB is dedicated to this issue, resetting `bars` is safe and does not erase the contributor's ordinary development data.

After all requests from the previous scenario have finished:

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U quant -d inalpha_issue107 -v ON_ERROR_STOP=1 \
  -c "TRUNCATE TABLE bars;"
```

Safety verification before any truncate:

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U quant -d inalpha_issue107 -Atc "select current_database();"
```

Never substitute the normal `inalpha` DB name in the reset command.

---

## 7. Cold-comparison sequence

For a comparison intended to start from the same state:

```text
1. finish/stop current probe wave
2. stop/restart factor so module cache is empty
3. TRUNCATE bars in inalpha_issue107
4. verify bars count = 0
5. keep provider mode/delay and worker topology unchanged
6. start/confirm factor against the dedicated DB/data URL
7. run exactly one scenario
8. save output before resetting again
```

Verify empty bars:

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U quant -d inalpha_issue107 -Atc "select count(*) from bars;"
```

Expected before a DB-cold scenario:

```text
0
```

---

## 8. M1/M2/M3 discipline

Recommended:

```text
M1:
  factor cache cold
  bars cold
  same-symbol factor
  runner stagger 0

reset factor + bars

M2:
  factor cache cold
  bars cold
  unique factor price keys
  runner stagger 0

reset factor + bars

M3:
  factor cache cold
  bars cold
  same-symbol factor
  runner stagger 100ms
```

This makes M1↔M2 mainly a key-shape comparison and M1↔M3 mainly a runner-alignment comparison instead of accidentally comparing a cold DB to an already-populated DB.

---

## 9. Warm control discipline

For the factor macro harness's immediate warm wave:

```text
do NOT restart factor
do NOT truncate bars
```

That wave intentionally asks whether the already-populated process/DB state eliminates repeated work.

Label it clearly:

```text
factor cache = warm
data DB = warm
```

---

## 10. Before/after Candidate A comparison

For the strongest comparison:

```text
baseline revision
→ dedicated DB reset
→ factor cache reset
→ run scenario
→ save evidence

apply selected Candidate A revision
→ dedicated DB reset
→ factor cache reset
→ run identical scenario
→ save evidence
```

Do not compare:

```text
Before = empty bars
After  = already populated bars
```

or the reverse.

---

## 11. Why unique symbol suffixes are not enough

Synthetic unique price symbols help isolate main price keys, but macro factor calculations use real logical FRED series IDs such as the configured macro series.

Therefore a per-run symbol suffix cannot make the entire factor workload DB-cold.

A dedicated resettable benchmark DB is the cleaner control.

---

## 12. Data preservation rule

This plan follows the repository's own local-data discipline:

```text
not in git ≠ disposable
```

The dedicated DB exists specifically so benchmark resets never require gambling with the contributor's normal local data.
