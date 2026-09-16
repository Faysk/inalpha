# Issue #107 — Safe Full-Stack Factor → Data Macro Harness

**Status:** contributor-only baseline harness.  
**Purpose:** exercise the current factor live macro path over real local HTTP while replacing both the main price provider and FRED with deterministic local fakes.

This fills the gap between:

```text
pure unit cache-stampede diagnostics
```

and

```text
real-provider integration
```

without stress-testing Binance or FRED.

---

## 1. What this harness exercises

Real components:

```text
factor FastAPI route
→ request-scoped FactorEngine
→ real factor DataClient/httpx behavior
→ POST /backfill/bars
→ GET /bars
→ real data FastAPI routing
→ real shared DB pool
→ real bars persistence/query
→ fake local provider wait/data
→ factor macro computation/cache
```

Replaced components:

```text
Binance external OHLCV
FRED external API
```

So the harness can measure:

- real factor→data HTTP fan-out;
- H8/H11 cold-cache duplication;
- DB pool pressure from macro bursts;
- one-worker vs two-worker data behavior;
- warm-cache collapse after population;
- Candidate A before/after under a factor-driven workload.

---

## 2. Why the fake must return many bars per fetch

A simple fake that returns only one bar is fine for the narrow 1-hour backfill diagnostic.

It is **not** suitable for factor macro tests because current factor windows can be hundreds of days long:

```text
main 1d price history: lookback + horizon + warmup
macro daily/monthly history: up to ~600 days warmup
```

If the fake returned one bar per call, `/backfill/bars` would loop once per timeframe step and the benchmark would mostly measure the fake's artificial pagination.

The wrapper therefore supports:

```text
ISSUE107_FAKE_BARS_PER_FETCH=1000
```

and returns deterministic spaced bars up to the requested batch limit. The real backfill route still filters rows after `to_ts` and advances its normal cursor.

---

## 3. Benchmark database state is part of the experiment

Use:

```text
41-benchmark-db-state-determinism.md
```

and the dedicated DB:

```text
inalpha_issue107
```

A factor restart clears factor process memory but **does not** clear PostgreSQL bars.

For each experiment described as cold in both layers:

```text
factor cache = cold
data DB bars = cold
```

perform:

```text
restart factor
TRUNCATE bars in dedicated benchmark DB
verify count(*) = 0
```

before the run.

The immediate warm wave inside `issue107_factor_macro_probe.py` is different: do not restart factor or truncate bars between the first and second wave because the second wave intentionally measures post-population reuse.

---

## 4. Materialize contributor tooling

Prefer `40-local-preflight-helper.md`.

Manual fallback from repository root on `fix/data-service-saturation`:

```bash
git fetch origin notes/issue-107

git show origin/notes/issue-107:.faysk-notes/tools/issue107_slow_data_app.py \
  > services/data/issue107_slow_data_app.py

git show origin/notes/issue-107:.faysk-notes/tools/issue107_factor_macro_probe.py \
  > services/factor/issue107_factor_macro_probe.py
```

Confirm both are untracked and **do not add them**:

```bash
git status --short
```

---

## 5. Start fake data-service — exact-count mode

For the first macro experiment, use **one data worker** so the wrapper state counters are exact for the whole data-service process.

From `services/data`:

### Bash

```bash
DATABASE_URL="$ISSUE107_DATABASE_URL" \
ISSUE107_FAKE_VENUES=binance,fred \
ISSUE107_FAKE_BARS_PER_FETCH=1000 \
ISSUE107_PROVIDER_MODE=async \
ISSUE107_PROVIDER_DELAY_S=0.25 \
uv run uvicorn issue107_slow_data_app:app \
  --host 127.0.0.1 --port 18001 --workers 1
```

### PowerShell

```powershell
$env:DATABASE_URL = $env:ISSUE107_DATABASE_URL
$env:ISSUE107_FAKE_VENUES = "binance,fred"
$env:ISSUE107_FAKE_BARS_PER_FETCH = "1000"
$env:ISSUE107_PROVIDER_MODE = "async"
$env:ISSUE107_PROVIDER_DELAY_S = "0.25"
uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 1
```

Important safety check:

```text
/__issue107/state -> fake_venues must include binance,fred
```

The macro probe refuses to run if either fake is absent.

FRED does not need a real API key: the wrapper installs a local registry entry even if normal startup skipped the real FRED connector.

---

## 6. Start factor-service against fake data

Use one factor worker to match the current production topology and to keep the module-level cache model unambiguous.

From `services/factor` in a separate terminal:

### Bash

```bash
DATABASE_URL="$ISSUE107_DATABASE_URL" \
DATA_SERVICE_URL=http://127.0.0.1:18001 \
FACTOR_MACRO_ENABLED=true \
uv run uvicorn inalpha_factor.main:app \
  --host 127.0.0.1 --port 18004 --workers 1
```

### PowerShell

```powershell
$env:DATABASE_URL = $env:ISSUE107_DATABASE_URL
$env:DATA_SERVICE_URL = "http://127.0.0.1:18001"
$env:FACTOR_MACRO_ENABLED = "true"
uv run uvicorn inalpha_factor.main:app --host 127.0.0.1 --port 18004 --workers 1
```

Factor DB is optional for `/score`; the dedicated DB simply keeps all #107 runtime state isolated and reproducible.

Use the same root environment/JWT secret for factor and data so the token factor forwards is accepted by data-service.

---

## 7. Cold identical-key wave — H11 + H8 shape

Start from:

```text
factor cache = cold
data DB bars = cold
```

by restarting factor and resetting the dedicated bars table immediately before this run.

From `services/factor`:

```bash
uv run python issue107_factor_macro_probe.py \
  --factor-url http://127.0.0.1:18004 \
  --data-url http://127.0.0.1:18001 \
  --concurrency 6 \
  --symbol-mode same \
  --factor-set macro \
  --timeframe 1d
```

This asks six concurrent request-scoped engines for the same live score key.

Possible current-main shape, if cold misses line up before cache population:

```text
6 main price fresh fetches
+
up to 6 × 18 macro fresh fetches
```

Do **not** treat that arithmetic as the result. The probe records actual fake-provider deltas.

Immediately afterward the script runs the same wave again. That second wave is the intentional warm control:

```text
do not truncate bars
do not restart factor
```

---

## 8. Cold different-symbol wave — isolate shared macro-key duplication

After saving the previous results:

```text
restart factor
TRUNCATE dedicated bars
verify bars count = 0
```

then run:

```bash
uv run python issue107_factor_macro_probe.py \
  --factor-url http://127.0.0.1:18004 \
  --data-url http://127.0.0.1:18001 \
  --concurrency 6 \
  --symbol-mode unique \
  --factor-set macro \
  --timeframe 1d
```

Now the six main price keys are intentionally different, but the macro FRED/date keys are shared.

Interpretation:

```text
binance provider starts ≈ 6
fred provider starts materially > 18
→ evidence of same macro-key cold duplication
```

Exact values remain timing-dependent and must be recorded, not assumed.

The DB reset matters here: otherwise the unique-symbol experiment could be compared against FRED series already persisted by the same-symbol experiment.

---

## 9. Full factor-set control

After the macro-only behavior is understood, optionally perform another full cold reset and run:

```bash
uv run python issue107_factor_macro_probe.py \
  --concurrency 6 \
  --symbol-mode same \
  --factor-set all
```

This adds normal price-factor computation and is closer to the default `/score` workload.

Do not start here: the macro-only run gives cleaner attribution first.

---

## 10. Thread-mode control

FRED and some other connectors wrap synchronous SDK calls with `asyncio.to_thread` in current code.

The fake wrapper can approximate the executor shape without external traffic:

```text
ISSUE107_PROVIDER_MODE=thread
```

Repeat a modest cold run after:

```text
restarting factor
resetting dedicated bars
restarting data wrapper in thread mode
```

Record:

```text
thread_active
thread_started
thread_completed
pool queue/wait
health/openapi behavior
factor latency/errors
```

This does not claim to reproduce real fredapi internals exactly; it isolates async-vs-thread capacity behavior.

---

## 11. Production-like two-data-worker confirmation

Exact aggregate provider counters are easiest with one data worker.

After understanding the request shape, reset the dedicated bars DB, restart factor, then restart the fake data service with:

```text
--workers 2
```

and rerun a representative cold factor wave.

In this topology:

- each data worker has its own DB pool;
- fake/provider counters are process-local;
- request distribution is not guaranteed 50/50;
- the state endpoint only describes the worker that served that request.

Use:

- worker PID response/log evidence;
- repeated state samples;
- data request logs;
- p95/error behavior;

rather than pretending one state response is container-global.

---

## 12. What the factor probe reports

For each wave:

```text
factor status counts
HTTPX error types
machine codes
p50 / p95 / p99 / max
bars_used distribution
returned factor-count distribution
```

And from the one-worker fake data process:

```text
aggregate provider starts/completions/failures
binance provider starts/completions/failures
fred provider starts/completions/failures
pool request count / queued / wait-ms / errors / usage-ms deltas
pool size/availability after wave
```

The script warns if the data state PID changes, because then exact deltas are invalid.

---

## 13. Key comparisons

### Cold vs warm

Within one probe invocation:

```text
cold first wave:
  expected to exercise data-service

immediate warm second wave:
  should collapse data/provider work if cache population succeeded
```

Do not reset state between those two waves.

If warm still produces large data deltas, investigate cache keys/eviction/failures rather than assuming stampede.

### Same vs unique symbols

Across separately reset cold experiments:

```text
same:
  whole-score key duplicated + macro keys duplicated

unique:
  price keys legitimately differ; macro keys still shared
```

This helps separate H11 from H8.

### Before vs Candidate A

If H1 selects Candidate A, repeat the exact same cold scenario after resetting the same dedicated benchmark DB:

```text
same concurrency
same fake delay
same bars-per-fetch
same workers
same factor set
same symbol mode
same factor cache state
same data DB state
```

Compare DB availability/waits, factor errors/p95, provider starts/failures and data progress.

---

## 14. Do not over-interpret fake data quality

The fake produces deterministic synthetic bars purely to drive the current data/factor control flow.

It is **not** designed to make every macro effectiveness statistic economically meaningful.

For #107 capacity work, the relevant signals are:

- request/fan-out counts;
- provider concurrency;
- DB pool pressure;
- HTTP latency/errors;
- cache behavior;
- no fake-success/no-progress regression.

A factor returning fewer meaningful macro rows against synthetic data is not itself evidence of a capacity bug.

---

## 15. Cleanup

Use the preflight helper cleanup from `40-local-preflight-helper.md` or remove the two files manually and confirm:

```bash
git status --short
```

The contribution branch must return clean except for intentionally selected production changes later.

---

## Success criterion for this harness

The harness succeeds if it lets us answer, without touching a real external provider:

> How much factor-driven live macro traffic actually reaches data-service on a cold concurrent burst, which resource degrades first, and does the selected fix stabilize that exact workload without weakening freshness or moving failure to the provider layer?
