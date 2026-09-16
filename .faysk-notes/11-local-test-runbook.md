# Issue #107 — Local Baseline Test Runbook

**Purpose:** authoritative runtime sequence for issue #107. Avoid improvising setup, contaminating the benchmark with persistent cache state, or touching production behavior before the baseline selects a fix.

Contributor-only documentation. Diagnostics copied from `notes/issue-107` must remain untracked.

---

## 1. Branch / SHA safety gate

Work on:

```text
Faysk/inalpha:fix/data-service-saturation
```

Before any runtime work:

```bash
git status --short
git fetch upstream main
git fetch origin notes/issue-107
git branch --show-current
git rev-parse HEAD
git rev-parse upstream/main
```

Requirements:

```text
branch = fix/data-service-saturation
working tree = clean before diagnostics are materialized
HEAD == upstream/main
```

Reviewed upstream SHA when this runbook was prepared:

```text
ed01be9056776c107ab76a404c328a4fed19f529
```

If upstream has moved, stop and re-review the #107-sensitive code paths first. Do not silently `reset --hard` over contributor work.

`40-local-preflight-helper.md` contains safe PowerShell/Bash helpers that perform these checks and materialize the known diagnostics without applying a production patch.

---

## 2. Record environment

Save:

```bash
git --version
docker --version
docker compose version
uv --version
python --version
node --version
pnpm --version
```

Also record:

```text
OS / WSL version
CPU
RAM
Docker resource limits if explicitly configured
```

Performance numbers are not meaningful without the execution environment and worker topology.

---

## 3. Repository dependency setup

Follow current `CONTRIBUTING.md`:

```bash
cd packages/orchestration && pnpm i && cd ../..
for service in data paper research factor evolver; do
  (cd "services/$service" && uv sync)
done
cp .env.example .env
cp infra/.env.example infra/.env
(cd infra && docker compose up -d)
```

Do not start all application services with `scripts/dev.sh` for the first diagnostic. We want explicit one-worker/two-worker service processes later.

---

## 4. Create a dedicated benchmark database

Use:

```text
inalpha_issue107
```

rather than repeatedly clearing the normal developer database.

See `41-benchmark-db-state-determinism.md` for the exact create/reset commands.

Recommended URL with repository defaults:

```text
postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107
```

Apply migrations to that DB:

### Bash / WSL

```bash
export ISSUE107_DATABASE_URL='postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107'
(
  cd infra/migrations
  DATABASE_URL="$ISSUE107_DATABASE_URL" uv sync
  DATABASE_URL="$ISSUE107_DATABASE_URL" uv run alembic upgrade head
)
export DATABASE_URL="$ISSUE107_DATABASE_URL"
```

### PowerShell

```powershell
$env:ISSUE107_DATABASE_URL = 'postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107'
Push-Location infra/migrations
uv sync
$oldDb = $env:DATABASE_URL
$env:DATABASE_URL = $env:ISSUE107_DATABASE_URL
uv run alembic upgrade head
Pop-Location
$env:DATABASE_URL = $env:ISSUE107_DATABASE_URL
```

The benchmark report must distinguish:

```text
factor process cache = cold/warm
data DB bars          = cold/warm
```

A factor restart alone does not make the data DB cold.

---

## 5. Pre-change repository checks

With `DATABASE_URL` pointing to the dedicated benchmark DB:

### Consistency

```bash
bash scripts/check-consistency.sh
```

### Data

```bash
(cd services/data && uv run ruff check . && uv run pytest)
```

### Factor

```bash
(cd services/factor && uv run ruff check . && uv run pytest)
```

Record command, exit code, pass/fail/skip counts, runtime and unexpected warnings.

If current upstream already fails, preserve the output separately. Do not fix unrelated failures inside #107 unless they prevent the investigation.

---

## 6. Materialize contributor diagnostics

Preferred: use `40-local-preflight-helper.md`.

It creates only these untracked files:

```text
services/factor/tests/test_issue107_macro_stampede_local.py
services/factor/tests/test_issue107_live_cache_stampede_local.py
services/data/tests/test_issue107_pool_pressure_local.py
services/data/issue107_slow_data_app.py
services/data/issue107_load_probe.py
services/data/issue107_timeout_persistence_probe.py
services/factor/issue107_factor_macro_probe.py
services/factor/issue107_runner_poll_probe.py
services/factor/issue107_mixed_workload_probe.py
```

It deliberately does **not** materialize Candidate A or its post-fix regression yet.

After materialization:

```bash
git status --short
```

should show only the expected untracked diagnostic files.

---

## 7. A — pure factor H8 / H11 diagnostics

No data service or provider network is used.

```bash
(cd services/factor && uv run pytest -vv -s tests/test_issue107_macro_stampede_local.py)
(cd services/factor && uv run pytest -vv -s tests/test_issue107_live_cache_stampede_local.py)
```

Record:

```text
H8 sequential same-key underlying fetch count
H8 concurrent same-key underlying fetch count
H11 concurrent identical score main-fetch count
H11 warm identical score main-fetch count
```

Expected current structure, to be verified rather than assumed:

```text
post-population cache reuse works
but
cold in-flight same-key calls are not coalesced
```

This does not establish production materiality.

---

## 8. B — controlled H1 pool=2 diagnostic

Run:

```bash
(cd services/data && uv run pytest -vv -s tests/test_issue107_pool_pressure_local.py)
```

The test owns a two-connection pool.

Control:

```text
1 blocked provider call
→ /health succeeds
```

Pressure:

```text
2 blocked provider calls
→ /openapi.json succeeds
→ /health cannot acquire DB until provider release
```

If observed, this proves current resource ordering can starve unrelated DB-backed traffic while the ASGI/event-loop path is alive.

It still does not prove H1 is the dominant production #107 mechanism.

---

## 9. C — real-Uvicorn slow-provider baseline, one data worker

Use `16-two-worker-fake-provider-harness.md`.

Start with:

```text
data workers = 1
fake venue = binance
provider mode = async
```

Run `issue107_load_probe.py` with a concurrency sweep only as large as needed to see the pressure transition.

Capture:

```text
backfill p50/p95/p99
health p50/p95/p99
openapi p50/p95/p99
HTTP status/error classes
provider active
backfill HTTP in-flight
pool available minimum
pool waiting maximum
pool wait-ms delta
```

OpenAPI healthy + health degraded is the important isolation signal.

---

## 10. D — PostgreSQL-side evidence

During blocked first-provider waits, follow:

```text
25-pg-stat-activity-diagnostic.md
```

Capture:

```text
provider work sleeping outside PostgreSQL
idle in transaction count
oldest transaction age
last query sample
```

Use direct Psycopg pool stats from the wrapper alongside PostgreSQL activity; PostgreSQL `idle` alone does not tell us whether the application has returned a connection to its pool.

---

## 11. E — H9 / H10 client-timeout and thread persistence

Follow:

```text
24-client-timeout-cancellation.md
26-h10-default-executor-contention.md
```

Run the real-TCP timeout probe first with:

```text
provider mode = async
```

then repeat where useful with:

```text
provider mode = thread
```

Question:

```text
after the client deadline, is older server/provider work still active?
```

Thread mode additionally asks whether the underlying synchronous worker survives cancellation of the asyncio waiter.

---

## 12. F — two-data-worker confirmation

Repeat the understood low-level workload with:

```text
data workers = 2
```

matching current production compose.

Do not treat `/__issue107/state` as service-global: its counters are per process.

Use:

```text
response worker PID headers
per-PID logs
client-visible latency/errors
```

and do not assume a 50/50 split.

---

## 13. G — full-stack factor macro baseline

Follow:

```text
36-safe-full-stack-macro-harness.md
```

Recommended exact-count topology:

```text
data workers   = 1
factor workers = 1
fake venues    = binance,fred
fake bars/fetch = 1000
benchmark DB   = inalpha_issue107
```

Before a DB-cold/factor-cold comparison:

```text
restart factor
TRUNCATE bars in dedicated DB
verify count(*) = 0
```

Run:

```text
cold single caller
cold concurrent same-symbol callers
cold concurrent unique price-key callers
immediate warm wave
```

Do **not** truncate/restart between the first wave and its intentional immediate warm control.

Record actual provider/data call counts. Static “18 FRED series” arithmetic is not a substitute for runtime counts.

---

## 14. H — runner aligned vs staggered

Follow:

```text
38-runner-poll-harness.md
```

Use:

```text
data workers = 1
fake venues = binance,baostock,yfinance
fake bars/fetch = 1000
benchmark DB = inalpha_issue107
```

For each comparison reset the dedicated bars table first.

Compare:

```text
--runs 8 --stagger-ms 0
```

against:

```text
--runs 8 --stagger-ms 100
```

with the same provider delay/mode.

This tests H6 without changing `live_runner.py`.

---

## 15. I — mixed issue-level M1/M2/M3 baseline

Follow:

```text
39-mixed-workload-harness.md
41-benchmark-db-state-determinism.md
```

Exact-count first pass:

```text
data workers   = 1
factor workers = 1
fake venues    = binance,fred,baostock,yfinance
fake bars/fetch = 1000
benchmark DB   = inalpha_issue107
```

For **each** cold scenario:

```text
1. stop previous wave
2. restart factor so module cache is cold
3. TRUNCATE bars in inalpha_issue107
4. verify bars count = 0
5. keep provider mode/delay and worker topology unchanged
6. run exactly one scenario
7. save output
```

Scenarios:

```text
M1  factor same-symbol + runner stagger 0
M2  factor unique price keys + runner stagger 0
M3  factor same-symbol + runner stagger 100ms
```

This avoids accidentally comparing M1's cold DB to M2/M3 after M1 already populated bars.

---

## 16. J — fill the baseline decision record

Update `04-baseline-results.md` with:

```text
first resource to degrade
DB pool available/wait evidence
provider active/failure evidence
concrete transport error classes
DATA_SERVICE_UNREACHABLE chain if observed
H6/H8/H9/H10/H11 evidence
negative evidence / ruled-out hypotheses
```

Do not choose a fix until the conclusion section can answer:

```text
What is the smallest measured cause we can remove without weakening freshness or changing unrelated contracts?
```

---

## 17. K — first production decision gate

Possible outcomes:

```text
H1 material
→ Candidate A: narrow /backfill/bars DB lease

DB healthy after H1 correction but provider/in-flight work saturates
→ Candidate C: bounded admission before scarce-resource checkout

H8/H11 materially amplify the representative workload after the data boundary is healthy
→ factor single-flight / bounded fan-out candidate

H3 connection churn material
→ safe factor HTTP reuse with per-request Authorization

H6 still changes failures materially after Candidate A
→ consider runner scheduling/jitter with maintainer alignment

none explain failure
→ investigate further; do not force a planned solution
```

Candidate A is not applied before this gate.

---

## 18. If Candidate A is selected

Only then materialize:

```text
.faysk-notes/tools/candidate_a_narrow_db_lease.patch
.faysk-notes/tools/test_candidate_a_regression_draft.py
```

Prefer translating the draft into a clean production commit rather than blindly applying it if upstream has changed.

First regression property:

```text
pool max_size=2
4 blocked provider requests all reach provider I/O
while /health remains DB-responsive
```

Then rerun the **same** low-level/factor/runner/mixed baselines with identical DB-reset/cache discipline.

Record in `07-before-after-results.md`.

---

## 19. Final cleanup before production commit review

Remove every contributor-only materialized harness/diagnostic and verify:

```bash
git status --short
```

The production diff should contain only the selected fix and intentionally upstream-worthy regression tests/docs.

Never accidentally commit:

```text
issue107_slow_data_app.py
load probes
notes branch files
local benchmark scripts/results
```

unless the maintainer explicitly asks for a reusable benchmark artifact.

---

## 20. Evidence discipline

For every benchmark save:

```text
commit SHA
benchmark DB name
factor cache cold/warm
data bars cold/warm
worker count / PIDs
provider fake mode/delay/bars-per-fetch
request shape/concurrency
runner stagger
p50/p95/p99
HTTP status counts
concrete HTTPX exception types
DATA_SERVICE_UNREACHABLE count
refresh row/timestamp progress
DB pool available/wait/queue/error metrics
provider active/completed/cancelled/failed metrics
thread-active metrics where applicable
pg_stat_activity evidence where applicable
```

Rules:

1. Change one meaningful variable at a time.
2. Preserve failing reproduction before fixing it.
3. Never stress real provider APIs for load testing.
4. HTTP 200 without expected data progress is not refresh success.
5. Lower errors achieved by stale current data are not success.
6. Use the exact same benchmark state before/after the selected fix.
7. Record negative evidence as carefully as supporting evidence.
