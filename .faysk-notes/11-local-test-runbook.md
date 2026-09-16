# Issue #107 — Local Baseline Test Runbook

**Purpose:** exact steps to run later on the contributor machine without improvising setup or touching production behavior first.

This is contributor-only documentation. Commands are based on the repository's current `CONTRIBUTING.md`, test fixtures, and dev compose files.

---

## 1. Safety / branch check

Work only on:

```text
Faysk/inalpha:fix/data-service-saturation
```

Before setup:

```bash
git status --short
git fetch upstream
git checkout fix/data-service-saturation
git reset --hard upstream/main
git rev-parse HEAD
```

Expected reviewed baseline at the time these notes were prepared:

```text
ed01be9056776c107ab76a404c328a4fed19f529
```

If upstream has moved, stop and re-review the #107-sensitive files before using old benchmark conclusions.

Do **not** commit contributor diagnostics copied from the notes branch.

---

## 2. Tool versions to record

Capture these in the baseline notes:

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

Performance numbers are only comparable when the execution environment is known.

---

## 3. Official local dependency setup

The repository's documented setup is:

```bash
cd packages/orchestration && pnpm i && cd ../..
for service in data paper research factor evolver; do
  (cd "services/$service" && uv sync)
done
cp .env.example .env
cp infra/.env.example infra/.env
(cd infra && docker compose up -d)
(cd infra/migrations && uv sync && uv run alembic upgrade head)
```

The current local infra example sets:

```text
POSTGRES_USER=quant
POSTGRES_PASSWORD=devpass
POSTGRES_DB=inalpha
POSTGRES_PORT=5433
```

This matches the data test fixture's default test DB URL:

```text
postgresql+psycopg://quant:devpass@localhost:5433/inalpha
```

Do not silently change the database port/password between setup and tests.

---

## 4. Pre-change baseline checks

Before running any new #107 diagnostic, prove the current checkout is healthy.

### Required project consistency

```bash
bash scripts/check-consistency.sh
```

### Data service

```bash
cd services/data
uv run ruff check .
uv run pytest
cd ../..
```

### Factor service

```bash
cd services/factor
uv run ruff check .
uv run pytest
cd ../..
```

Record:

```text
command
exit code
passed / failed / skipped counts
runtime
unexpected warnings
```

If existing upstream tests fail before our changes, preserve that output separately. Do not "fix" unrelated failures inside #107 without deciding whether they block the investigation.

---

## 5. Fetch contributor diagnostics without merging notes

Stay on `fix/data-service-saturation`.

```bash
git fetch origin notes/issue-107
```

### Pure factor diagnostics

```bash
git show origin/notes/issue-107:.faysk-notes/tools/test_macro_cache_stampede_draft.py \
  > services/factor/tests/test_issue107_macro_stampede_local.py

git show origin/notes/issue-107:.faysk-notes/tools/test_factor_live_cache_stampede_draft.py \
  > services/factor/tests/test_issue107_live_cache_stampede_local.py
```

### Data DB-pool diagnostic

```bash
git show origin/notes/issue-107:.faysk-notes/tools/test_backfill_pool_pressure_draft.py \
  > services/data/tests/test_issue107_pool_pressure_local.py
```

Confirm they are temporary/untracked:

```bash
git status --short
```

Do not `git add` them.

---

## 6. Run the pure factor cache diagnostics

These use no data-service, DB, FRED API key or external network.

### H8 — macro-key cold stampede

```bash
cd services/factor
uv run pytest -vv -s tests/test_issue107_macro_stampede_local.py
cd ../..
```

Expected current-main structural behavior:

```text
sequential same-key macro requests
→ one underlying fetch after cache population

6 simultaneous cold same-key requests
→ all 6 miss before first cache put
→ six underlying fake fetches
```

If observed, this proves lack of macro same-key in-flight coalescing (**H8 structure**), not that H8 is materially responsible for #107.

### H11 — whole live-score cold stampede

```bash
cd services/factor
uv run pytest -vv -s tests/test_issue107_live_cache_stampede_local.py
cd ../..
```

This checks whether simultaneous identical live score requests all miss the module-level live cache before the first result is installed.

Again:

```text
structural duplication ≠ production materiality
```

The service-level macro/mixed harnesses later decide whether H8/H11 matter enough to change production code.

---

## 7. Run the DB pool-pressure diagnostic

```bash
cd services/data
uv run pytest -vv -s tests/test_issue107_pool_pressure_local.py
cd ../..
```

The diagnostic deliberately overrides the test app's pool to:

```text
max_size = 2
```

so it does not depend on the repository's normal pool default staying at 10.

### Control

```text
1 blocked fake-provider backfill
→ 1/2 DB connections retained by route-scoped DBConn
→ one pool slot remains
→ /health expected to complete
```

### Pressure case

```text
2 blocked fake-provider backfills
→ 2/2 DB connections retained
→ /openapi.json expected to remain responsive
→ /health expected to wait
→ release fake provider
→ backfills complete
→ /health completes
```

No real market-data provider is contacted.

### Interpretation

If the behavior matches:

```text
confirmed:
current route/resource ordering can starve unrelated DB-backed requests while the ASGI/event-loop
path remains alive

NOT YET confirmed:
this is the dominant production root cause of #107
```

If it does **not** match, preserve the result and investigate why. Do not edit the test to force our hypothesis.

---

## 8. Cleanup the temporary pytest diagnostics

```bash
rm services/factor/tests/test_issue107_macro_stampede_local.py
rm services/factor/tests/test_issue107_live_cache_stampede_local.py
rm services/data/tests/test_issue107_pool_pressure_local.py
git status --short
```

PowerShell:

```powershell
Remove-Item services/factor/tests/test_issue107_macro_stampede_local.py
Remove-Item services/factor/tests/test_issue107_live_cache_stampede_local.py
Remove-Item services/data/tests/test_issue107_pool_pressure_local.py
git status --short
```

The contribution branch should still contain zero #107 production changes at this point.

---

## 9. Materialize service-level contributor harnesses

### Data-side wrapper and low-level probes

```bash
git show origin/notes/issue-107:.faysk-notes/tools/issue107_slow_data_app.py \
  > services/data/issue107_slow_data_app.py

git show origin/notes/issue-107:.faysk-notes/tools/issue107_load_probe.py \
  > services/data/issue107_load_probe.py

git show origin/notes/issue-107:.faysk-notes/tools/issue107_timeout_persistence_probe.py \
  > services/data/issue107_timeout_persistence_probe.py
```

### Factor full-stack probe

A convenient location is `services/factor/` because its environment already contains factor/shared dependencies:

```bash
git show origin/notes/issue-107:.faysk-notes/tools/issue107_factor_macro_probe.py \
  > services/factor/issue107_factor_macro_probe.py
```

### Runner-like and mixed probes

These import only shared auth/config plus HTTPX and can also be run from `services/factor/` after `uv sync`:

```bash
git show origin/notes/issue-107:.faysk-notes/tools/issue107_runner_poll_probe.py \
  > services/factor/issue107_runner_poll_probe.py

git show origin/notes/issue-107:.faysk-notes/tools/issue107_mixed_workload_probe.py \
  > services/factor/issue107_mixed_workload_probe.py
```

All of the above are temporary contributor tooling. Keep them untracked.

The data wrapper exposes:

```text
X-Issue107-Worker-Pid response header
GET /__issue107/state          # DB-free per-worker provider/http/thread/pool counters
provider start/done/cancel/fail logs
```

The state endpoint now includes direct Psycopg `get_stats()` values plus per-path HTTP in-flight counts, so peak pressure can be measured instead of guessed.

---

## 10. Service-level slow-provider baseline

Follow `16-two-worker-fake-provider-harness.md` for the real Uvicorn/TCP one-worker and two-worker load runs.

Start with one data worker and fake Binance only. The goal is to reproduce the DB/non-DB isolation signal with a real TCP server before adding factor/runner traffic.

The load probe reports worker PID distribution for responses it receives, so the two-worker result does not assume a 50/50 split.

---

## 11. DB-side transaction evidence

For the one-worker fake-provider run, follow:

```text
25-pg-stat-activity-diagnostic.md
```

Use a temporary diagnostic `application_name` and capture PostgreSQL activity while the **first** fake-provider fetches are blocked.

Strong current-main signal would be:

```text
provider waits are active outside PostgreSQL
AND
data-service sessions appear idle in transaction after latest_bar_ts SELECT
```

Do not change global autocommit or `_shared` to make the metric disappear.

---

## 12. Client-timeout persistence diagnostic

After the basic one-worker HTTP harness is understood, run the server with a provider delay longer than the client timeout and execute:

```bash
uv run python issue107_timeout_persistence_probe.py \
  --base-url http://127.0.0.1:18001 \
  --attempts 4 \
  --request-timeout 0.5 \
  --settle-wait 6
```

Interpret using `24-client-timeout-cancellation.md`.

Question:

```text
After clients have already timed out, are older fake-provider requests still active/completing,
or did Uvicorn/ASGI cancellation propagate promptly?
```

This tests H9 and determines whether retry amplification can include overlapping abandoned server work.

---

## 13. Full-stack factor macro baseline

Follow:

```text
36-safe-full-stack-macro-harness.md
```

For exact counts use:

```text
data workers   = 1
factor workers = 1
fake venues    = binance,fred
fake bars/fetch = 1000
```

Run the factor macro probe with:

```text
cold single caller
cold concurrent same-symbol callers
cold concurrent unique-symbol callers
immediate warm wave
```

Restart factor before a true cold run.

Record actual factor→data request/provider-call deltas. Do not infer them from static “18 FRED series” arithmetic when the harness can count them directly.

---

## 14. Live-runner-like aligned vs staggered baseline

Follow:

```text
38-runner-poll-harness.md
```

Use fake:

```text
binance,baostock,yfinance
ISSUE107_FAKE_BARS_PER_FETCH=1000
```

Compare the **same** run count/provider delay with:

```text
--stagger-ms 0
--stagger-ms 100
```

The probe samples peak provider/HTTP/DB-pool state while the wave is active.

This tests H6 without modifying `live_runner.py`.

---

## 15. Mixed representative acceptance workload

Only after the isolated mechanisms are understood, follow:

```text
39-mixed-workload-harness.md
```

Exact-count first pass:

```text
data workers   = 1
factor workers = 1
fake venues    = binance,fred,baostock,yfinance
fake bars/fetch = 1000
```

Run at least:

```text
M1: cold factor same-symbol + runner stagger=0
M2: cold factor unique-symbol + runner stagger=0
M3: cold factor same-symbol + runner stagger=100ms
```

Restart factor before each comparison that is intended to be cold.

The mixed probe also sends:

```text
/openapi.json  # DB-free control
/health        # DB-backed control
```

while factor/runner work is in flight.

This is the issue-level baseline we should rerun unchanged after Candidate A or any other selected fix.

---

## 16. Full baseline sequence

Do not start with the mixed scenario. Use this order:

```text
A. existing data/factor tests
B. pure H8/H11 factor diagnostics
C. controlled pool=2 H1 diagnostic
D. real-Uvicorn slow-provider pressure — 1 data worker
E. pg_stat_activity during blocked provider wait
F. H9 client-timeout/cancellation behavior
G. same low-level fake workload — 2 data workers
H. live factor + macro: cold single
I. live factor + macro: cold concurrent same keys
J. live factor + macro: cold concurrent unique price keys
K. immediate warm factor control
L. runner-like aligned polls
M. runner-like stagger control
N. mixed M1/M2/M3 issue-level baseline
O. only then select the first production intervention
```

This order lets us explain *why* the mixed workload fails instead of only observing that it fails.

---

## 17. One-worker vs two-worker discipline

The repository's production compose currently runs:

```text
data WORKERS=2
factor WORKERS=1
paper WORKERS=1
research WORKERS=1
```

Use:

```text
1 data worker
→ deterministic diagnosis / easier attribution

2 data workers
→ production-like confirmation
```

Never describe a normal `asyncio.Semaphore`/lock/cache as service-global under the two-worker topology. It is process-local unless an external coordination mechanism is introduced.

State/counter caveat:

```text
/__issue107/state
```

is process-local. Exact deltas and peak samples are only directly interpretable with one data worker. In two-worker mode combine client-visible behavior, response PID headers and per-PID logs.

---

## 18. Evidence to save

For every run record:

```text
commit SHA
worker count / worker PIDs
test/scenario name
request count / concurrency
factor cache condition: cold/warm
factor symbol mode: same/unique
runner stagger
fake provider mode/delay/bars-per-fetch
duration
p50 / p95 / p99
HTTP status counts
concrete HTTPX exception types
DATA_SERVICE_UNREACHABLE count
zero-row/no-progress refresh count
DB pool requests/queued/wait/errors/available minimum
pg_stat_activity state/xact evidence where applicable
provider started/active/completed/cancelled counters
provider per-venue counts
HTTP in-flight peaks
CPU / memory where practical
notes on freshness/cutoff behavior
```

For the initial controlled-pool diagnostic, the important evidence is:

```text
1/2 pool slots retained: health available? yes/no
2/2 pool slots retained: openapi available? yes/no; health blocked? yes/no
```

For the mixed workload, preserve factor, runner, health and OpenAPI outcomes separately.

---

## 19. Cleanup contributor harness files

Before making or reviewing the actual contribution diff, remove every materialized contributor tool:

```bash
rm services/data/issue107_slow_data_app.py
rm services/data/issue107_load_probe.py
rm services/data/issue107_timeout_persistence_probe.py
rm services/factor/issue107_factor_macro_probe.py
rm services/factor/issue107_runner_poll_probe.py
rm services/factor/issue107_mixed_workload_probe.py
git status --short
```

PowerShell equivalents are fine.

The final upstream PR should not accidentally contain the contributor harness unless the maintainer explicitly asks for a generally reusable benchmark tool.

---

## 20. Stop conditions

Stop before implementing a production fix if:

- the baseline cannot reproduce a capacity problem;
- current upstream moved materially since the reviewed commit;
- failures are caused by local setup rather than service saturation;
- the proposed solution would require touching `_shared`, live-runner/risk paths, or a large cross-service contract without renewed scope review;
- a lower error rate would only be achieved by weakening freshness or hiding a failed refresh.

---

## 21. First implementation gate

Only after baseline evidence exists, decide among:

```text
A. shorten DB connection lifetime around provider I/O
B. add bounded admission before scarce DB checkout
C. address factor macro duplicate/fan-out behavior if materially measured
D. address factor HTTP client reuse if materially measured
E. another measured bottleneck
```

Current project precedent already favors separating DB work from external HTTP in the live runner (see `37-existing-db-http-separation-precedent.md`), which strengthens Candidate A's project fit **if H1 is measured**. It does not replace the baseline requirement.

Do not implement all candidates together. One measured cause, one minimal intervention, same benchmark before/after.
