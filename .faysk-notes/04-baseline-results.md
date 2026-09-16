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
Other service worker counts:
DB pool config observed:
Deployment topology:
Relevant env overrides:
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

| Scenario | Topology / concurrency | Requests | HTTP success | Refresh progress | Fail | p50 | p95 | p99 | `DATA_SERVICE_UNREACHABLE` |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Controlled small-pool diagnostic | pool=2 / 1 then 2 blocked | TBD | TBD | TBD | TBD | TBD | TBD | TBD | N/A |
| Fake slow provider — 1 worker | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Fake slow provider — 2 workers | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Client-timeout persistence | 1 worker / TBD attempts | TBD | TBD | N/A | TBD | TBD | TBD | TBD | N/A |
| Live macro cold cache — single caller | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Live macro cold cache — concurrent callers | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Live macro warm cache | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 10 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 50 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 300 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Runner-like steady poll | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Runner resume/warmup burst | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Mixed | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

`Refresh progress` means the refresh actually advanced/inserted expected data, not merely that HTTP returned 200.

---

## Repeatability

Record representative runs separately rather than reporting only the best one.

| Scenario | Run | p95 | Errors | Refresh no-progress | Notes |
|---|---:|---:|---:|---:|---|
| TBD | 1 | TBD | TBD | TBD | |
| TBD | 2 | TBD | TBD | TBD | |
| TBD | 3 | TBD | TBD | TBD | |

---

## Detailed observations

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

### Client-timeout persistence / H9

Run against the contributor fake provider over real TCP/Uvicorn, one worker first.

```text
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
State after settle:
  started:
  active:
  completed:
  cancelled:
  failed:
```

Interpretation:

```text
client timeout + active > 0 afterward
→ old server/provider work survived caller deadline in this topology

cancelled ~= started and active quickly 0
→ disconnect cancellation propagated promptly

completed rises only after clients timed out
→ retries/new callers could overlap older work; H9 support
```

Do not assume executor-backed real providers obey the fake asyncio-sleep cancellation behavior exactly.

### Live factor macro

```text
Macro series requested:
Data calls:
Backfills:
Cold single-caller behavior:
Cold concurrent-caller behavior:
Warm-cache behavior:
Macro degradation/failures:
HTTP client/connection observations:
```

#### Macro cache coalescing/stampede check

```text
Concurrent factor callers:
Unique macro cache keys requested:
Actual _fetch_macro_series network/data fetches:
Actual /backfill/bars calls attributable to macro:
Actual /bars calls attributable to macro:
Duplicate-work ratio = actual fetches / unique keys:
Pure diagnostic current-main fetch_count (6 same-key callers):
```

Interpretation:

```text
sequential unique-key ratio ≈ 1
but concurrent cold ratio >> 1
→ H8 evidence
```

Do not count 18 different FRED series as duplicate work. H8 is specifically about repeated fetches for the **same macro cache key** before first population completes.

### Factor panel control

```text
Observed:
Data request fan-out:
Max observed symbol fetch concurrency:
Did any per-symbol backfill occur?:
Failure mode:
```

### Live runner / polling

```text
Run count:
Observed cadence:
Burst synchronization:
Backfill/read request count:
Interaction with factor traffic:
```

### Live runner resume/warmup burst

```text
Persisted running runs resumed:
Timeframe distribution:
Warmup bars setting:
Fresh backfills started during restart:
Peak overlap:
Concurrent factor baseline captures:
Did cold macro requests overlap?:
Data-service effect:
```

This scenario represents a natural current thundering-herd path: startup resumes persisted running runs and each build performs fresh warmup; successful builds can then capture factor baselines from independent runner tasks.

### Same-key backfill duplication check

```text
Caller path:
Unique refresh keys:
Provider calls:
Dashboard coalescing observed?:
Cross-service duplication observed?:
```

### Mixed load

```text
Exact workload:
First resource to degrade:
First error/result class:
Latency curve:
DATA_SERVICE_UNREACHABLE count:
Zero-row/no-progress backfills:
Macro unique keys vs actual calls:
Provider work surviving caller timeouts?:
```

---

## Resource measurements

| Metric | Idle | Representative load | Peak |
|---|---:|---:|---:|
| data CPU | TBD | TBD | TBD |
| data memory | TBD | TBD | TBD |
| factor CPU | TBD | TBD | TBD |
| DB connections checked out / inferred | TBD | TBD | TBD |
| DB `idle in transaction` | TBD | TBD | TBD |
| DB pool waits/timeouts | TBD | TBD | TBD |
| provider calls in flight | TBD | TBD | TBD |
| provider calls cancelled | TBD | TBD | TBD |
| provider queue depth/wait | TBD | TBD | TBD |
| client connections/sockets | TBD | TBD | TBD |
| macro unique keys | TBD | TBD | TBD |
| macro actual fetches | TBD | TBD | TBD |

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
30s client timeout is reached?

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
- [ ] H7: event-loop/thread-pool saturation is primary
- [ ] H8: cold macro cache stampede materially duplicates same-key factor→data work
- [ ] H9: timed-out clients leave older server/provider work active long enough to overlap retries/new requests

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
