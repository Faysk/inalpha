# Issue #107 — Baseline Results

**Status:** waiting for reproduction run.  
**Purpose:** record pre-change evidence against current upstream behavior.

---

## Environment

```text
Date:
Commit SHA:
OS:
Python:
Docker:
CPU:
RAM:
Data worker count:
Factor worker count:
Paper worker count:
DB pool config observed:
Deployment topology:
Relevant env overrides:
Fake provider mode/delay/bars-per-fetch:
Cache state (cold/warm):
```

Do not record secrets.

---

## Existing tests before reproduction

```text
services/data pytest:
services/factor pytest:
ruff:
mypy notes:
check-consistency:
```

---

## Scenario summary

| Scenario | Topology / concurrency | HTTP success | Refresh progress | Fail | p50 | p95 | p99 | Key signal |
|---|---|---:|---:|---:|---:|---:|---:|---|
| H8 pure macro cold same-key | factor unit / 6 callers | N/A | N/A | TBD | N/A | N/A | N/A | underlying fetch count |
| H11 pure live-score cold same-key | factor unit / 6 callers | N/A | N/A | TBD | N/A | N/A | N/A | main data fetch count |
| H1 controlled small-pool | pool=2 / 1 then 2 blocked | TBD | TBD | TBD | TBD | TBD | TBD | health vs OpenAPI isolation |
| Fake slow provider — 1 worker | TBD | TBD | TBD | TBD | TBD | TBD | TBD | pool wait / health degradation |
| H9 client-timeout persistence | 1 worker / TBD attempts | TBD | N/A | TBD | TBD | TBD | TBD | server work survives client deadline? |
| Fake slow provider — 2 workers | TBD | TBD | TBD | TBD | TBD | TBD | TBD | PID distribution / client-visible effect |
| Factor macro cold — single | 1 data / 1 factor | TBD | TBD | TBD | TBD | TBD | TBD | FRED provider calls |
| Factor macro cold — same-key concurrent | 1 data / 1 factor / TBD callers | TBD | TBD | TBD | TBD | TBD | TBD | H8/H11 amplification |
| Factor macro cold — unique price keys | 1 data / 1 factor / TBD callers | TBD | TBD | TBD | TBD | TBD | TBD | H8 with reduced H11 |
| Factor macro warm | 1 data / 1 factor | TBD | TBD | TBD | TBD | TBD | TBD | post-population cache reuse |
| Runner aligned | 1 data / 8 polls / 0 ms stagger | TBD | TBD | TBD | TBD | TBD | TBD | peak pool/provider overlap |
| Runner stagger control | 1 data / 8 polls / 100 ms stagger | TBD | TBD | TBD | TBD | TBD | TBD | H6 delta |
| Mixed M1 | cold factor same-key + 8 runner / 0 ms | TBD | TBD | TBD | TBD | TBD | TBD | issue-level baseline |
| Mixed M2 | cold factor unique price keys + runner / 0 ms | TBD | TBD | TBD | TBD | TBD | TBD | H11 isolation |
| Mixed M3 | cold factor same-key + runner / 100 ms | TBD | TBD | TBD | TBD | TBD | TBD | H6 isolation |
| Mixed M1 — 2 data workers | production-like confirmation | TBD | TBD | TBD | TBD | TBD | TBD | client-visible + per-PID evidence |

`Refresh progress` means the refresh actually advanced/inserted expected data, not merely that HTTP returned 200.

---

## Repeatability

Record representative runs separately rather than reporting only the best one.

| Scenario | Run | p95 | Errors | Refresh no-progress | Pool wait | Notes |
|---|---:|---:|---:|---:|---:|---|
| TBD | 1 | TBD | TBD | TBD | TBD | |
| TBD | 2 | TBD | TBD | TBD | TBD | |
| TBD | 3 | TBD | TBD | TBD | TBD | |

---

## Detailed observations

### H8 pure macro-cache structural diagnostic

```text
Sequential same-key fetch count:
Concurrent callers:
Concurrent same-key underlying fetch count:
Result:
```

Expected current-main structural signal:

```text
sequential population works
but
simultaneous cold same-key callers do not coalesce
```

This proves H8 structure only, not production materiality.

### H11 whole live-score structural diagnostic

```text
Concurrent identical live-score callers:
Main _fetch_df entries before first cache put:
Warm request main fetch count:
Result:
```

This isolates the outer live-score cache from macro H8 by disabling macro in the unit diagnostic.

### Controlled small-pool diagnostic

The contributor test overrides data DB pool capacity to `max_size=2` so the proof does not depend on normal production tuning.

```text
Control — 1 blocked provider call:
/health available?:

Pressure — 2 blocked provider calls:
/openapi.json available?:
/health blocked while provider sleeps?:
/health completes after provider release?:
```

Isolation signal:

```text
/openapi.json remains responsive while /health blocks? yes/no
```

If yes, this is stronger evidence for DB-backed capacity starvation than generic event-loop/ASGI starvation.

Question to answer:

```text
Does holding route-level DBConn across provider I/O materially contribute to saturation?
```

### DB-side activity during provider wait

Follow `25-pg-stat-activity-diagnostic.md`.

```text
application_name used:
provider calls currently blocked:
pg_stat_activity total data sessions:
idle sessions:
idle in transaction sessions:
active sessions:
oldest xact age:
last query sample:
```

Strong H1-supporting baseline signal:

```text
fake provider work is sleeping outside PostgreSQL
AND
connections that already executed latest_bar_ts remain idle in transaction / retained
```

Remember plain `idle` does not by itself prove whether a connection is checked out vs available in the Psycopg pool.

### Production-like fake-provider run

```text
Workers:
Fake provider delay:
Concurrent backfills:
Worker PIDs observed:
Backfill responses by PID:
Health responses by PID:
OpenAPI responses by PID:
Provider starts by PID from logs/state:
Request distribution skew:
/openapi.json p95:
/health p95:
Backfill p95:
Concrete transport error types:
HTTP machine codes:
Rows/progress:
```

Do not assume a 50/50 split across two workers.

### Direct Psycopg pool stats

Record state from the contributor wrapper during the wave:

```text
pool_pool_size:
pool_pool_available minimum:
pool_requests_waiting maximum:
pool_requests_num delta:
pool_requests_queued delta:
pool_requests_wait_ms delta:
pool_requests_errors delta:
pool_usage_ms delta:
```

Interpret cumulative values as deltas over one experiment. Do not mistake cumulative `requests_queued` for instantaneous queue depth; use `requests_waiting` for the sampled current queue.

### Client-timeout persistence / H9

Run against the contributor fake provider over real TCP/Uvicorn, one worker first.

```text
Fake provider mode: async/thread
Fake provider delay:
Client timeout:
Attempts:
Client outcomes (ReadTimeout/etc):
State before:
State immediately after client timeouts:
  started:
  active:
  completed:
  cancelled:
  failed:
  thread_active:
State after settle:
  started:
  active:
  completed:
  cancelled:
  failed:
  thread_active:
```

Interpretation:

```text
client timeout + active > 0 afterward
→ old server/provider work survived caller deadline in this topology

cancelled ~= started and active quickly 0
→ async cancellation propagated promptly

thread_active remains > 0 after async waiter/caller cancellation
→ underlying synchronous provider work outlived the asyncio request path

completed rises only after clients timed out
→ retries/new callers could overlap older work; H9 support
```

Do not assume real providers behave exactly like either fake mode; the two modes establish cancellation boundaries.

### Live factor macro

Use `36-safe-full-stack-macro-harness.md`.

```text
Macro factor ids selected:
Unique FRED series expected:
Actual factor→data POST /backfill count:
Actual factor→data GET /bars count:
Binance provider calls:
FRED provider calls:
Cold single-caller behavior:
Cold same-symbol concurrent behavior:
Cold unique-symbol concurrent behavior:
Warm-cache behavior:
Macro degradation/failures:
Pool wait/available minimum:
HTTP client/connection observations:
```

#### Macro cache coalescing/stampede check

```text
Concurrent factor callers:
Unique macro cache keys requested:
Actual macro data/provider fetches:
Duplicate-work ratio = actual same-key fetches / unique keys:
Pure H8 diagnostic current-main fetch_count:
```

Interpretation:

```text
sequential/warm reuse works
but concurrent cold same-key ratio >> 1
→ H8 service-level evidence
```

Do not count 18 different FRED series as duplicate work. H8 is specifically about repeated fetches for the **same macro cache key** before first population completes.

#### Whole live-score H11 isolation

Compare:

```text
same-symbol cold concurrent callers
vs
unique-symbol cold concurrent callers
```

Main price keys are shared only in the first case; macro/date keys remain shared in both.

A large M1/same-symbol delta over unique-symbol behavior supports H11 materiality.

### Factor panel control

Panel is no longer the primary reproduction path because current main already bounds panel fetch concurrency and panel scoring avoids forced per-symbol fresh backfills.

If run as a control:

```text
Observed:
Data request fan-out:
Max observed symbol fetch concurrency:
Did any per-symbol backfill occur?:
Failure mode:
```

Do not prioritize panel tuning unless this current behavior still reproduces a material problem.

### Live runner aligned vs staggered / H6

Use `38-runner-poll-harness.md`.

```text
Run count:
Fake provider delay:
Stagger:
POST /backfill count:
GET /bars count:
Runner p50/p95/p99:
Backfill transport errors:
Bars transport errors:
Provider active max:
Per-venue active max:
Backfill HTTP in-flight max:
GET /bars in-flight max:
Pool available min:
Pool waiting max:
Pool wait delta:
```

Compare the exact same workload with:

```text
stagger=0 ms
stagger=100 ms
```

Interpretation:

```text
small stagger materially reduces peak pool/provider pressure and p95/errors
→ H6 support

little/no difference
→ runner jitter likely not a first-fix requirement
```

The generic fake does not reproduce yfinance's real provider lock; this comparison isolates caller alignment.

### Live runner resume/warmup burst

Current startup behavior is structurally:

```text
list_all_running
→ start one asyncio task per run
→ concurrent _build_session
→ fresh warmup bars
→ capture_factor_baseline after successful build
→ first poll
```

Record only if we later run a seeded paper integration scenario:

```text
Persisted running runs resumed:
Timeframe distribution:
Warmup bars setting:
Fresh backfills started during restart:
Peak overlap:
Baseline source per run: lineage/environment
Concurrent factor baseline captures:
Did cold macro requests overlap?:
Data-service effect:
```

`29-runner-resume-factor-burst-shape.md` defines the exact lineage/environment distinction; do not claim every resumed run triggers all 18 FRED series.

### Same-key backfill duplication check

```text
Caller path:
Unique refresh keys:
Provider calls:
Dashboard coalescing observed?:
Cross-service duplication observed?:
```

### Mixed M1/M2/M3

Use `39-mixed-workload-harness.md`.

Common configuration:

```text
Data workers:
Factor workers:
Fake venues:
Fake provider mode/delay:
Fake bars/fetch:
Factor concurrency:
Runner count:
Health/OpenAPI probe count:
```

#### M1 — cold same-symbol factor + aligned runner

```text
factor_symbol_mode=same
runner_stagger_ms=0
Factor outcomes:
Runner outcomes:
Health outcomes:
OpenAPI outcomes:
Data/provider request deltas:
Peak provider active:
Peak pool waiting:
Pool available min:
p95/p99:
First resource to degrade:
```

#### M2 — cold unique factor price keys + aligned runner

```text
factor_symbol_mode=unique
runner_stagger_ms=0
Same metrics:
Delta vs M1:
```

M2 reduces whole-score same-key H11 overlap while retaining shared macro/date H8 potential.

#### M3 — cold same-symbol factor + staggered runner

```text
factor_symbol_mode=same
runner_stagger_ms=100
Same metrics:
Delta vs M1:
```

M3 tests H6 while holding the cold factor shape constant.

### Mixed interpretation

```text
Strongest first constrained resource:
First client-visible failure/result class:
DATA_SERVICE_UNREACHABLE count:
Runner GET /bars failures:
Health failures:
OpenAPI failures:
Zero-row/no-progress backfills:
Macro unique keys vs actual calls:
Provider work surviving caller timeouts?:
```

If OpenAPI survives while health/factor/runner DB-backed paths degrade, the evidence points away from generic event-loop death and toward DB-backed capacity/resource ordering.

---

## Resource measurements

| Metric | Idle | Representative load | Peak |
|---|---:|---:|---:|
| data CPU | TBD | TBD | TBD |
| data memory | TBD | TBD | TBD |
| factor CPU | TBD | TBD | TBD |
| DB pool size | TBD | TBD | TBD |
| DB pool available | TBD | TBD | TBD |
| DB requests waiting | TBD | TBD | TBD |
| DB queued cumulative delta | TBD | TBD | TBD |
| DB wait ms cumulative delta | TBD | TBD | TBD |
| DB `idle in transaction` | TBD | TBD | TBD |
| provider calls in flight | TBD | TBD | TBD |
| provider calls cancelled | TBD | TBD | TBD |
| provider thread work active | TBD | TBD | TBD |
| backfill HTTP in-flight | TBD | TBD | TBD |
| bars HTTP in-flight | TBD | TBD | TBD |
| client connections/sockets | TBD | TBD | TBD |
| macro unique keys | TBD | TBD | TBD |
| macro actual same-key fetches | TBD | TBD | TBD |

---

## Error / result classification

Do not use `DATA_SERVICE_UNREACHABLE` alone as a root-cause category. Factor maps multiple HTTPX transport failures into that code.

| Error/result | Count | Scenario | Meaning / retry behavior | Notes |
|---|---:|---|---|---|
| `httpx.ConnectTimeout` | TBD | TBD | transport connect deadline | Distinguish from server slowness |
| `httpx.ReadTimeout` | TBD | TBD | connected but no response bytes within read deadline | Key H1b/H9 signal when server work is slow |
| `httpx.WriteTimeout` | TBD | TBD | request-body send deadline | TBD |
| `httpx.PoolTimeout` (client) | TBD | TBD | load-generator/caller client pool exhausted | Must not confuse with server DB pool |
| `httpx.ConnectError` | TBD | TBD | actual connection error | Closest to literal “failed to connect” |
| other `httpx.RequestError` | TBD | TBD | preserve concrete subtype | TBD |
| `DATA_SERVICE_UNREACHABLE` | TBD | TBD | factor's mapped transport failure after retries | Record underlying subtype/log evidence where possible |
| HTTP 500 `INTERNAL_ERROR` | TBD | TBD | unexpected server error; can include DB pool checkout timeout | Correlate logs/trace ID |
| `BARS_UPSTREAM_UNAVAILABLE` | TBD | TBD | provider exception surfaced by backfill | provider-dependent |
| HTTP 200 + zero/no progress | TBD | TBD | not necessarily success | watch yfinance/#74 |
| intentional busy/backpressure | N/A baseline | after fix only | selected semantics TBD | report separately from transport failure |

### 30-second race to look for

Current static values:

```text
server DB pool checkout timeout ≈ 30s
factor GET HTTP timeout          ≈ 30s
paper/factor-client outer timeout ≈ 30s in several paths
```

If the same capacity event sometimes yields HTTP 500 and sometimes caller `ReadTimeout`, preserve both; do not assume they are unrelated until trace/timing evidence says so.

---

## Retry amplification

Where practical record:

```text
logical factor GET operations:
physical GET attempts:
retry ratio:
older server requests still active when retry starts?:
```

Questions:

```text
Does sustained slowness convert one logical read into multiple physical requests because the
client deadline is reached?

If yes, do retries replace cancelled work or overlap older work that remains active?
```

---

## Hypothesis results

- [ ] H1: DB connection lifetime across provider I/O is a major saturation multiplier
- [ ] H1b: DB wait/server slowness reaches factor HTTP deadlines and is mapped to `DATA_SERVICE_UNREACHABLE`
- [ ] H2: expensive backfill concurrency is independently a bottleneck
- [ ] H3: factor HTTP connection churn is material
- [ ] H4: duplicate same-key backfill work outside dashboard is material
- [ ] H5: one provider monopolizes capacity
- [ ] H6: live-runner synchronization/resume burst materially contributes
- [ ] H7: event-loop saturation is primary
- [ ] H8: cold macro cache stampede materially duplicates same-key factor→data work
- [ ] H9: timed-out clients leave older server/provider work active long enough to overlap retries/new requests
- [ ] H10: shared/default executor contention is materially involved for thread-backed providers
- [ ] H11: whole live-score cold cache stampede materially duplicates main data work

Evidence:

```text
TBD
```

---

## What was ruled out

```text
TBD
```

Record negative evidence. It prevents us from re-adding unnecessary fixes to the PR later.

---

## Baseline conclusion

```text
Strongest root-cause evidence:

Contributing factors:

What is NOT the bottleneck:

Smallest justified next intervention:

Why that intervention is at the correct service boundary:

Risks/correctness constraints:

Does the intended fix remain data-service-local?:
```

No production implementation should begin until this section has enough evidence to justify the first change.
