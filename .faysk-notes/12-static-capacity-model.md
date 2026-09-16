# Issue #107 — Static Capacity Model

**Status:** pre-runtime model.  
**Purpose:** convert the current code paths into testable capacity predictions before running the contributor baseline.

> This document is not a root-cause claim. It records what the current code makes possible and what the runtime tests must prove or falsify.

---

## 1. Verified capacity constants

### data-service process model

Repository production compose currently runs:

```text
data-service workers = 2
```

Each worker initializes its own process-local shared DB pool with the current defaults:

```text
min_size = 2
max_size = 10
checkout timeout = 30 s
```

Therefore the compose topology has **up to 10 checked-out DB connections per data worker** (roughly 20 total across the container), but load distribution across the two workers is not guaranteed to be perfectly even.

A process-local semaphore/cache/lock is also duplicated per worker.

### current `/backfill/bars` resource lifetime

The route receives `db: DBConn` as a FastAPI dependency.

Current effective sequence:

```text
request accepted
→ DB pool checkout
→ latest_bar_ts()
→ external connector.fetch_bars()
→ insert_bars()
→ possibly repeat fetch/write batches
→ response
→ DB connection returned to pool
```

So the scarce DB lease spans external provider I/O.

### transaction nuance

`latest_bar_ts()` executes a SELECT before the first provider call. The shared pool only configures `row_factory`; it does not enable autocommit.

Psycopg 3 defaults `autocommit=False`, and its documentation states that any database operation starts a transaction by default. The pool connection context commits/rolls back on context exit.

That means the first external provider wait can occur while the connection is not only reserved from the pool, but also has an open transaction started by `latest_bar_ts()`.

Reference:

- https://www.psycopg.org/psycopg3/docs/basic/transactions.html
- https://www.psycopg.org/psycopg3/docs/api/pool.html

After `insert_bars()` explicitly commits a batch, later provider waits in the same request can still retain the connection even when no transaction is active.

Do **not** overstate this as the root cause; it is a verified resource-lifetime property.

---

## 2. Agent/factor concurrency that can reach data-service

### panel path — partially mitigated already

Current panel code:

```text
_PANEL_FETCH_CONCURRENCY = 16
fresh = False
```

So current `panel_score` still produces concurrent GET traffic, but deliberately does not create one fresh backfill per symbol.

This is materially different from the original June wording of #107.

### live macro path — still a burst source

For current/live factor scoring:

```text
as_of=None or near-now
→ is_live=True
→ price fetch fresh=True
→ macro computation fresh=True
```

`_compute_macro()` gets all required FRED series with unbounded `asyncio.gather` for that request. The code comment documents a daily snapshot with roughly **18 macro series**.

Each macro series eventually goes through `_fetch_df()`, which creates a fresh factor `DataClient`, and each `DataClient` creates its own `httpx.AsyncClient`.

On a macro-cache miss, one factor request can therefore produce a burst approximately shaped as:

```text
~18 FRED series
→ ~18 factor DataClients
→ concurrent fresh backfill + bars reads
```

Important qualifier: macro live cache TTL is 1 hour, so this path is **bursty rather than permanently sustained** after the cache is warm. It remains especially relevant after factor restart, cache expiration, or a new uncached series/date combination.

---

## 3. Live-runner concurrency that can reach data-service

Each running strategy has its own long-lived asyncio task.

Current settings allow, by default:

```text
up to 10 simultaneously running live runs per account
```

Each loop derives its polling interval from timeframe (or the global override), then calls `_fetch_latest_bar()`.

`_fetch_latest_bar()` uses:

```text
DataClient.get_bars(... fresh=True)
```

which means:

```text
POST /backfill/bars
→ GET /bars
```

for each poll.

There is currently no randomized jitter in the main polling loop. Runs with the same timeframe, especially runs resumed/startup together, can therefore align into request bursts.

This does not prove that they are synchronized in production; it gives us a runtime condition to measure.

---

## 4. Static load arithmetic

### Scenario A — cold/live macro burst only

Approximate request burst:

```text
18 fresh macro series
2 data workers
≈ 9 requests/worker if perfectly balanced
```

Pool capacity is 10 per worker.

Even under ideal balance, this is already close to the worker pool ceiling **if each request retains its DB connection while waiting for the external provider**.

It leaves very little headroom for:

- the main price-series backfill/read,
- live-runner polls,
- dashboard reads,
- `/health`,
- research/orchestration traffic.

### Scenario B — macro + modest live overlap

Illustrative only:

```text
18 macro backfills
+ 4 live-runner fresh polls
= 22 concurrent backfill-shaped requests
```

Perfectly balanced across 2 workers would be ~11 per worker, already above `max_size=10`.

The actual distribution may be uneven, so one worker can queue before the container-wide theoretical 20-connection total is reached.

### Scenario C — yfinance serialization

Within each data worker, yfinance history calls are protected by a process-local `_FETCH_LOCK`.

This protects Yahoo from burst rate-limits, but current route resource order can look like:

```text
request A: owns DB connection → owns Yahoo lock → provider I/O
request B: owns DB connection → waits Yahoo lock
request C: owns DB connection → waits Yahoo lock
...
```

So **provider concurrency can be 1 while DB occupancy is much higher**.

This is exactly why limiting only provider calls after DB checkout can move the bottleneck instead of removing it.

---

## 5. Timeout cascade hypothesis

Verified timeout values relevant to the chain:

```text
DB pool checkout timeout         30 s
factor GET /bars client timeout  30 s
factor fresh backfill timeout    60 s
```

Factor GETs retry connection-level `httpx.RequestError` up to 3 attempts with short backoff.

A plausible saturation chain is therefore:

```text
slow/queued backfills retain DB connections
→ unrelated GET /bars waits for DBConn
→ request approaches/exceeds factor's 30 s HTTP deadline
→ httpx timeout is classified as RequestError
→ factor retries
→ additional request pressure
→ eventual DATA_SERVICE_UNREACHABLE
```

This is **H1b**, not yet a measured sequence.

The baseline should collect timing evidence showing whether the client deadline is actually reached because of DB checkout wait.

---

## 6. `/health` is a useful canary — with an important caveat

`GET /health` itself receives `db: DBConn` before its handler executes.

Inside the handler it catches errors from `SELECT 1`, but **pool checkout happens in dependency resolution before that try/except block**.

Therefore under full pool exhaustion:

```text
/health request
→ waits for DBConn before handler
→ may never reach the handler's db_status="error" fallback
```

If the pool checkout itself times out, the generic service error handler sees an unexpected exception and can return `500 INTERNAL_ERROR`.

Production compose probes `/health` every 10 seconds with a short healthcheck timeout. So health latency/status is a useful saturation signal, but it is not a pure process-liveness measurement.

This is adjacent design debt, not automatically part of the #107 fix.

---

## 7. Why the original issue may be harder to reproduce now

The June issue describes:

```text
multi-symbol concurrent backfill
+ live-runner polling
```

Current `main` has already changed important pieces:

- panel fetches are bounded to 16;
- panel uses `fresh=False`, avoiding per-symbol backfills;
- backfill is incremental;
- factor GET retries absorb short connection blips;
- macro values use a one-hour live cache after successful fetch.

So we should not expect the historical trigger to reproduce identically.

Our runtime goal is to reproduce the **capacity failure class**, not to force obsolete traffic behavior back into the system.

---

## 8. Runtime predictions

### Prediction P1 — DB lease mechanism

With a fake connector that blocks externally:

```text
9 concurrent blocked backfills
→ /health still obtains the 10th pool connection

10 concurrent blocked backfills
→ /health waits until a backfill releases capacity
```

The contributor diagnostic `tools/test_backfill_pool_pressure_draft.py` is built specifically to test this.

### Prediction P2 — candidate DB-lifetime fix

If DB checkout is narrowed so provider I/O happens without holding a connection:

```text
10 blocked provider calls
→ /health should remain responsive
```

This prediction gives us a clean before/after regression if H1 is confirmed.

### Prediction P3 — admission gate after DB checkout is insufficient

If a semaphore is added *inside* the current handler after the `DBConn` dependency has already resolved:

```text
waiting requests can still reserve DB pool slots
```

The 10-request diagnostic may continue to starve `/health` even though external provider concurrency is bounded.

### Prediction P4 — gate before DB checkout

If admission control is ultimately required, it must occur before long-lived scarce-resource checkout (or DB lifetime must first be narrowed).

This matches an existing project pattern in Evolver: its dispatcher acquires a semaphore before entering `async with get_conn()`.

---

## 9. What would falsify H1 as the primary bottleneck

H1 is weakened if runtime testing shows one or more of the following:

- 10 blocked provider calls do **not** starve unrelated DB-backed endpoints;
- pool wait remains negligible while client timeouts occur elsewhere;
- event-loop lag/CPU rises first while pool capacity remains available;
- requests are rejected before reaching DB dependency resolution;
- connection churn/socket exhaustion occurs independently of DB pressure;
- a production-like mixed workload fails with plenty of free DB capacity.

If that happens, we move to the next measured constraint rather than forcing a DB-lifetime patch.

---

## Current strongest static hypothesis

> `/backfill/bars` currently couples external-provider latency to DB-pool occupancy. Under concurrent fresh traffic, that coupling can consume per-worker DB capacity and delay unrelated reads until callers time out and retry.

The mechanism is strongly supported by code inspection. Its **magnitude and causal role in #107 remain runtime questions**.
