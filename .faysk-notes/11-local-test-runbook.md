# Issue #107 — Local Baseline Test Runbook

**Purpose:** authoritative runtime sequence for issue #107. Avoid improvising setup, contaminating the benchmark with persistent cache state, contacting real providers, or touching production behavior before evidence selects a fix.

Contributor-only documentation. Diagnostics copied from `notes/issue-107` must remain untracked.

Where an older harness note conflicts with this file, `49-runtime-safety-order.md`, or `52-provider-isolation-and-soak-hardening.md`, follow the newer safety rule.

---

## 1. Branch / SHA safety gate

Work on:

```text
Faysk/inalpha:fix/data-service-saturation
```

Before runtime work:

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

Reviewed upstream SHA when this revision was prepared:

```text
ed01be9056776c107ab76a404c328a4fed19f529
```

If upstream moved, stop and re-review #107-sensitive code paths first. Do not silently reset/rebase over contributor work.

Prefer the safe materialization helper from `40-local-preflight-helper.md`.

---

## 2. Record environment before measuring

Capture:

```text
git / Docker / docker compose / uv / Python / Node / pnpm versions
OS / WSL version
CPU
RAM
Docker resource limits if explicitly configured
HEAD / upstream-main SHA
```

Use `scripts/issue107_capture_env.ps1` where convenient. Performance numbers without machine/topology metadata are not PR-quality evidence.

---

## 3. Repository dependency setup

Follow current `CONTRIBUTING.md` rather than inventing a separate environment:

```bash
cd packages/orchestration && pnpm i && cd ../..
for service in data paper research factor evolver; do
  (cd "services/$service" && uv sync)
done
cp .env.example .env
cp infra/.env.example infra/.env
(cd infra && docker compose up -d)
```

Do not start all app services with `scripts/dev.sh` for the first capacity diagnostics. Worker counts must be explicit.

---

## 4. Dedicated benchmark database

Use only:

```text
inalpha_issue107
```

Recommended local URL with repository defaults:

```text
postgresql+psycopg://quant:devpass@localhost:5433/inalpha_issue107
```

Apply current migrations to it and export/store the URL as `ISSUE107_DATABASE_URL`.

Before a benchmark session, verify with:

```powershell
.\scripts\issue107_benchmark_db.ps1 verify
```

or:

```bash
bash scripts/issue107_benchmark_db.sh verify
```

For a deliberately DB-cold scenario, reset only after all previous workload stopped:

```powershell
.\scripts\issue107_benchmark_db.ps1 reset-bars
```

or:

```bash
bash scripts/issue107_benchmark_db.sh reset-bars
```

Never manually substitute the ordinary `inalpha` DB into reset commands.

Always distinguish:

```text
factor process cache = cold / warm
data DB bars          = cold / warm
```

A factor restart does not clear PostgreSQL bars.

---

## 5. Pre-change repository checks

With the dedicated DB configured, run at least:

```bash
bash scripts/check-consistency.sh
(cd services/data && uv run ruff check . && uv run pytest)
(cd services/factor && uv run ruff check . && uv run pytest)
```

Record exit codes, pass/fail/skip counts and unexpected warnings.

If untouched upstream already fails, preserve that evidence separately. Do not absorb unrelated fixes into #107 merely to make the session green.

---

## 6. Materialize contributor-only diagnostics

Use `40-local-preflight-helper.md`.

Expected untracked files include:

```text
services/factor/tests/test_issue107_macro_stampede_local.py
services/factor/tests/test_issue107_live_cache_stampede_local.py
services/data/tests/test_issue107_pool_pressure_local.py
services/data/issue107_slow_data_app.py
services/data/issue107_load_probe.py
services/data/issue107_timeout_persistence_probe.py
services/factor/issue107_factor_app.py
services/factor/issue107_target_check.py
services/factor/issue107_factor_macro_probe.py
services/factor/issue107_runner_poll_probe.py
services/factor/issue107_mixed_workload_probe.py
services/factor/issue107_sustained_mixed_probe.py
services/factor/issue107_sustained_acceptance_probe.py
scripts/issue107_capture_env.ps1
scripts/issue107_benchmark_db.ps1
scripts/issue107_benchmark_db.sh
```

Candidate A and its post-fix regression are intentionally **not** materialized yet.

After materialization, `git status --short` must contain only expected untracked contributor tooling.

---

## 7. Runtime provider-safety gate

The contributor data wrapper is stricter than normal data-service startup:

```text
startup constituent scheduler forced disabled
requested OHLCV venues → deterministic local fake
other registered OHLCV venues → fail-closed blocker
```

For factor/mixed/sustained tests, start factor only through:

```text
issue107_factor_app:app
```

with its expected URL pinned to the fake data target.

Then run the no-load verifier:

```bash
uv run python issue107_target_check.py \
  --data-url http://127.0.0.1:18001 \
  --factor-url http://127.0.0.1:18004 \
  --required-venues <scenario venues> \
  --require-macro
```

Required output:

```text
issue107_target_check=PASS
```

It must verify:

```text
all scenario venues are fake
required venues are not blocked
snapshot scheduler isolation is active
factor DATA_SERVICE_URL == checked fake data URL
factor expected data URL == checked fake data URL
macro enabled when required
```

If it fails, do not run load.

Runner-only and low-level data probes do not need the factor wrapper, but still must pass their own fake-target checks.

---

## 8. A — pure factor H8/H11 diagnostics

No data service/provider network is used:

```bash
(cd services/factor && uv run pytest -vv -s tests/test_issue107_macro_stampede_local.py)
(cd services/factor && uv run pytest -vv -s tests/test_issue107_live_cache_stampede_local.py)
```

Record sequential vs concurrent cold same-key underlying fetch counts and warm reuse.

Expected structure to verify, not assume:

```text
post-population cache reuse works
but
cold in-flight same-key work may duplicate
```

This establishes mechanism only, not production materiality.

---

## 9. B — controlled H1 pool=2 diagnostic

Run:

```bash
(cd services/data && uv run pytest -vv -s tests/test_issue107_pool_pressure_local.py)
```

The diagnostic owns a two-connection pool.

Control:

```text
1 blocked provider call
→ /health remains DB-responsive
```

Pressure:

```text
2 blocked provider calls
→ /openapi.json remains responsive
→ /health waits until provider release
```

If observed, this proves the current route/resource ordering can starve unrelated DB-backed traffic while the ASGI/event-loop path remains alive. It still does not prove H1 is the dominant issue-level cause.

---

## 10. C/D — real-Uvicorn one-worker capacity boundary

Use the fake data wrapper with:

```text
data workers = 1
fake venues = binance
provider mode = async
```

Run the low-level load probe only as far as needed to locate the transition, e.g. D08/D10/D12 from `44-runtime-execution-manifest.md`.

Capture:

```text
backfill latency/error classes
health latency/error classes
openapi latency/error classes
provider active
HTTP in-flight
pool available minimum
pool waiting maximum
pool wait-ms delta
```

Interpretation anchor:

```text
/openapi healthy + /health degraded
→ DB-backed path pressure rather than total event-loop death
```

Do not use the tiny D08/D10/D12 sample sizes as PR-quality p95 evidence.

---

## 11. E — PostgreSQL-side evidence

During controlled provider waits, follow `25-pg-stat-activity-diagnostic.md`.

Capture:

```text
idle in transaction count
oldest transaction age
last query sample
provider wait state
Psycopg pool available/queued/wait stats
```

PostgreSQL state and application pool state must be interpreted together.

---

## 12. F — H9/H10 timeout/cancellation/thread persistence

Follow:

```text
24-client-timeout-cancellation.md
26-h10-default-executor-contention.md
```

Run async fake mode first, then thread mode where useful.

Question:

```text
after caller timeout/cancellation, does older server/provider work remain active?
```

For thread mode, distinguish cancellation of the asyncio waiter from termination of the already-running synchronous worker.

---

## 13. G — two-data-worker production-like confirmation

Repeat the understood low-level workload with:

```text
data workers = 2
```

matching the current production compose topology.

Do not treat a single `/__issue107/state` response as container-global. Counters are process-local.

Use:

```text
worker PID headers
per-PID logs/state samples
client-visible latency/errors
```

and do not assume 50/50 request distribution.

---

## 14. H — full-stack factor macro baseline

Use:

```text
data workers    = 1
factor workers  = 1
fake venues     = binance,fred
fake bars/fetch = 1000
benchmark DB    = inalpha_issue107
```

Start the hardened data wrapper and fail-closed factor wrapper, then require the no-load target checker to PASS for `binance,fred`.

For each DB-cold/factor-cold scenario:

```text
restart factor
reset dedicated bars table
verify bars count = 0
```

Run:

```text
cold single caller
cold concurrent same-symbol callers
cold concurrent unique price-key callers
immediate warm wave
```

Do not restart/truncate between a first wave and its intentional immediate warm control.

Record actual provider/data HTTP counts; static “18 FRED series” arithmetic is not a measured result.

---

## 15. I — runner aligned vs staggered

Use:

```text
data workers    = 1
fake venues     = binance,baostock,yfinance
fake bars/fetch = 1000
benchmark DB    = inalpha_issue107
```

Compare a fully reset run with:

```text
--runs 8 --stagger-ms 0
```

against the same reset/settings with:

```text
--runs 8 --stagger-ms 100
```

This tests H6 without modifying live-runner production code.

Only carry runner staggering into a production candidate if this experiment remains materially relevant after the primary bottleneck is addressed.

---

## 16. J — mixed M1/M2/M3 baseline

Use:

```text
data workers    = 1
factor workers  = 1
fake venues     = binance,fred,baostock,yfinance
fake bars/fetch = 1000
benchmark DB    = inalpha_issue107
```

Require target-check PASS before each factor-driven session.

For each cold scenario:

```text
1. stop previous workload
2. restart factor
3. reset only inalpha_issue107 bars
4. verify bars count = 0
5. keep provider mode/delay + worker topology unchanged
6. run exactly one scenario
7. save output
```

Scenarios:

```text
M1 factor same-symbol + runner stagger 0
M2 factor unique price keys + runner stagger 0
M3 factor same-symbol + runner stagger 100ms
```

This is the issue-level burst comparison, not the final sustained p95 evidence.

---

## 17. K — sustained baseline acceptance O1/O2

Follow `50-sustained-load-acceptance.md` and record into `51-sustained-results-template.md`.

First perform a 30-second smoke to validate harness behavior. For evidence intended for the PR, once stable, use the same documented longer window for every revision, e.g.:

```text
60 seconds
at least 3 repetitions
```

### O1 — primary representative workload

```text
issue107_sustained_acceptance_probe.py
--factor-symbol-mode unique
runner stagger = 0
```

This models repeated cross-sectional factor requests plus the multi-market runner mix.

### O2 — H11 stress control

Repeat with only:

```text
--factor-symbol-mode same
```

### O3 — optional runner stagger

Run only if I/L-M evidence shows H6 is still material. Change only runner stagger.

The sustained probe records independently:

```text
cycles skipped because pending cap was reached
cycles skipped because the generator missed schedule slots
cycles still pending after settle
per-operation p50/p95/p99
provider start/completion/cancel/fail deltas
DB pool queue/wait deltas
```

Do not replay missed schedule slots as catch-up bursts.

For one data worker, before/after process counters are exact. For two data workers, rely on per-PID evidence.

Issue #107 asks for controlled p95 but does not define a numeric SLO. Record measured p95 under the exact workload and compare before/after; do not invent a project threshold.

---

## 18. L — baseline decision record

Fill `04-baseline-results.md` with:

```text
first resource to degrade
DB pool available/wait evidence
provider active/failure evidence
concrete transport error classes
DATA_SERVICE_UNREACHABLE chain if observed
H6/H8/H9/H10/H11 evidence
sustained O1/O2 evidence
negative evidence / ruled-out hypotheses
```

Do not choose a fix until the conclusion can answer:

> What is the smallest measured cause we can remove without weakening freshness or changing unrelated contracts?

---

## 19. M — first production decision gate

Possible evidence-driven outcomes:

```text
H1 material
→ Candidate A: narrow /backfill/bars DB lease

DB healthy after H1 correction but provider/in-flight work saturates
→ Candidate C: bounded admission before scarce-resource checkout

H8/H11 materially amplify representative workload after data boundary is healthy
→ factor single-flight / bounded fan-out candidate

H3 connection churn material
→ safe factor HTTP reuse with per-request Authorization

H6 still changes failures materially after primary correction
→ runner scheduling/jitter candidate, align scope with maintainer

none explain failure
→ investigate further; do not force a planned solution
```

Candidate A/B/C/D remains a hypothesis until this gate.

---

## 20. If Candidate A is selected

Only then materialize its patch/regression draft.

Do not blindly apply the draft if upstream moved; translate the measured design into clean current code.

First regression property:

```text
pool max_size=2
4 blocked provider requests all reach provider I/O
while /health remains DB-responsive
```

Then repeat the **same** relevant low-level, macro, runner, mixed and sustained O1 workload with identical:

```text
DB reset/cache state
worker topology
provider mode/delay
concurrency
runner stagger
sustained duration/interval
```

Record in `07-before-after-results.md` and `51-sustained-results-template.md`.

Also check Candidate A's known moved-bottleneck risk: releasing DB earlier may increase provider concurrency. DB improvement with provider failures increasing is not success.

---

## 21. Cleanup before production commit review

Remove every contributor-only harness/diagnostic and verify:

```bash
git status --short
```

The production diff should contain only the selected fix and intentionally upstream-worthy regression tests/docs.

Never accidentally commit contributor harnesses, notes, benchmark databases or local results unless the maintainer explicitly requests a reusable benchmark artifact.

---

## 22. Evidence discipline

For every benchmark preserve:

```text
commit SHA
benchmark DB name
factor cache cold/warm
data bars cold/warm
worker count / PIDs
provider fake mode/delay/bars-per-fetch
fake + blocked venue lists
snapshot scheduler isolation status
request shape/concurrency
runner stagger
p50/p95/p99 by operation
HTTP status counts
concrete HTTPX exception types
DATA_SERVICE_UNREACHABLE count
refresh row/timestamp progress
DB pool available/wait/queue/error metrics
provider active/completed/cancelled/failed metrics
thread-active metrics where applicable
pg_stat_activity evidence where applicable
cycles skipped pending-cap / schedule-lag where applicable
```

Rules:

1. Change one meaningful variable at a time.
2. Preserve failing reproduction before fixing it.
3. Never stress real provider APIs for load testing.
4. HTTP 200 without expected data progress is not automatically refresh success.
5. Zero backfill rows during repeated polling is not automatically failure either; interpret with timing/latest persisted data.
6. Lower errors achieved by stale current data are not success.
7. Use the exact same benchmark state before/after a selected fix.
8. Record negative evidence as carefully as supporting evidence.
9. Do not claim a production-wide SLO or capacity level beyond the tested topology/workload.
