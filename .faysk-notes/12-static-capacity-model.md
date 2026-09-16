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

Psycopg 3 defaults `autocommit=False`, and its pool context finalizes a transaction when the connection context exits. The first external provider wait can therefore occur while the connection is not only reserved from the pool, but also has a read transaction opened by `latest_bar_ts()`.

`insert_bars()` explicitly commits every batch, so current backfill is not one request-wide transaction. After a batch commit, later provider waits can still retain the connection even when no transaction is active.

Do **not** overstate transaction age as the root cause; the verified resource-lifetime property is broader:

```text
request-long DB lease spans external provider wait
```

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

### live macro path — exact default fan-out is 18 unique series

For current/live factor scoring:

```text
as_of=None or near-now
→ is_live=True
→ price fetch fresh=True
→ macro computation fresh=True
```

`MacroAdapter` currently exposes 26 macro factor specs backed by **18 unique FRED series**:

```text
8 daily
10 monthly
= 18 unique series
```

For a default live `1d`/`1wk` score or snapshot with `factor_ids=None`, `_computable_ids()` includes the available macro specs and `required_series()` resolves those exact 18 unique series.

`_compute_macro()` then launches them concurrently with `asyncio.gather`.

One cold default request is therefore shaped as:

```text
18 unique FRED series
→ 18 factor DataClients / _fetch_df operations
→ up to 18 concurrent fresh backfill + bars paths
```

This is the legitimate per-request fan-out. It should not be confused with duplicate work.

Macro live cache TTL is 1 hour, so this path is **bursty rather than permanently sustained** after successful cache population.

### H8 — concurrent cold callers can multiply the 18-series burst

The macro cache performs:

```text
cache lookup
→ await fetch
→ cache put
```

with no per-key in-flight coalescing.

Therefore `N` simultaneous cold default requests can theoretically produce up to:

```text
18 unique macro keys × N callers
```

actual fetch attempts before first population completes.

The unique work set is still only 18 keys; the excess is duplicate same-key work.

This multiplier is H8 and requires service-level measurement before any factor-side fix is justified.

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

Paper startup also resumes persisted `running` runs by launching their tasks. Each build performs fresh warmup, and successful builds then capture a factor baseline. That gives us a natural current startup burst to test rather than inventing arbitrary runner synchronization.

This does not prove the burst is large enough to cause #107; it gives a concrete workload to measure.

---

## 4. Static load arithmetic

### Scenario A — one cold/live default macro burst

Exact distinct macro requests:

```text
18 fresh macro series
2 data workers
≈ 9 requests/worker only if perfectly balanced
```

Pool capacity is 10 per worker.

Even under ideal balance, this is close to the worker pool ceiling **if each request retains its DB connection while waiting for the external provider**.

It leaves little headroom for:

- the main price-series backfill/read;
- live-runner polls;
- dashboard reads;
- `/health`;
- research/orchestration traffic.

But worker distribution is not deterministic, so do not claim a guaranteed 9/9 split.

### Scenario B — one macro request + modest live overlap

Illustrative only:

```text
18 macro backfills
+ 4 live-runner fresh polls
= 22 concurrent backfill-shaped requests
```

Perfectly balanced across 2 workers would be 11 per worker, already above `max_size=10`.

Actual distribution can be uneven, so one worker can queue earlier.

### Scenario C — several simultaneous cold macro callers

If H8 manifests strongly:

```text
2 cold default macro callers → up to 36 macro fetch attempts
3 cold default macro callers → up to 54 macro fetch attempts
```

Again, the unique macro key set remains 18. Actual duplicate ratio must be measured.

### Scenario D — yfinance serialization

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

### Scenario E — shared default-executor queueing

FRED and several other data connectors wrap synchronous libraries with `asyncio.to_thread`. Current repo search finds no custom `set_default_executor` configuration.

If synchronous provider jobs exceed the runtime's available default-executor threads, some backfill requests can wait in the executor queue.

Under current route ordering those queued requests may already own DB connections:

```text
DBConn acquired
→ latest_bar_ts
→ to_thread job queued / running
→ DB lease retained the whole time
```

This is H10. Runtime thread capacity depends on Python/CPU/deployment and must be measured, not guessed.

---

## 5. Timeout cascade hypothesis

Verified timeout values relevant to the chain:

```text
DB pool checkout timeout         30 s
factor GET /bars client timeout  30 s
factor fresh backfill timeout    60 s
```

Factor GETs retry connection/request-level `httpx.RequestError` up to 3 attempts with short backoff.

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

Whether the retry overlaps older server work is a separate H9 runtime question. A client timeout does not by itself prove that the server/provider task stopped or continued.

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

If the pool checkout itself times out, the generic service error handler can return `500 INTERNAL_ERROR`.

Production compose probes `/health` every 10 seconds with a short timeout. Health latency/status is a useful saturation signal, but it is not a pure process-liveness measurement.

Use `/openapi.json` as a non-DB control in the contributor harness:

```text
openapi fast + health blocked
→ stronger evidence of DB-backed capacity starvation
```

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

At the same time, current code still has:

- exact 18-series default cold macro fan-out;
- no in-flight coalescing for same macro cache key;
- fresh runner warmups/polls;
- request-long DB leases across backfill provider waits.

So we should not expect the historical trigger to reproduce identically.

Our runtime goal is to reproduce the **capacity failure class**, not to force obsolete traffic behavior back into the system.

---

## 8. Runtime predictions

### Prediction P1 — controlled DB lease mechanism

The in-process contributor diagnostic overrides DB pool max size to 2.

Current-main prediction:

```text
1 blocked fake-provider backfill
→ one DB lease retained
→ /health still works

2 blocked fake-provider backfills
→ both DB leases retained
→ /openapi.json still works
→ /health waits until provider release
```

This avoids coupling the diagnostic to the ordinary `max_size=10` default.

### Prediction P2 — Candidate A DB-lifetime fix

Post-fix regression uses the same 2-connection test pool but starts 4 fake-provider waits:

```text
4 requests > 2 pool slots
→ all four complete short latest_bar_ts DB phases
→ all four reach blocked provider I/O
→ /health still acquires DB
```

On current route-level `DBConn`, only the first two can reach provider I/O.

### Prediction P3 — DB-side state

During current-main **first provider wait** after `latest_bar_ts()`:

```text
pg_stat_activity may show one idle-in-transaction session per retained request
```

After Candidate A, that per-request open transaction should no longer persist during provider wait.

Plain `idle` sessions are less diagnostic because PostgreSQL cannot tell us from state alone whether an idle connection is currently checked out vs sitting available in the client pool.

### Prediction P4 — admission gate after DB checkout is insufficient

If a semaphore is added *inside* the current handler after the `DBConn` dependency has already resolved:

```text
waiting requests can still reserve DB pool slots
```

The endpoint-level pool diagnostic can still fail even though external provider concurrency is bounded.

### Prediction P5 — gate before DB checkout

If admission control is ultimately required, it must occur before long-lived scarce-resource checkout (or DB lifetime must first be narrowed).

This matches an existing project pattern in Evolver: its dispatcher acquires a semaphore before entering `async with get_conn()`.

### Prediction P6 — async vs thread-backed fake provider

If H1 is mainly about lease ordering, both fake modes should show DB-backed starvation on current code:

```text
asyncio.sleep provider wait
and
asyncio.to_thread(sync sleep) provider wait
```

Thread mode may additionally show executor queueing or sync work surviving coroutine cancellation, which helps separate H9/H10 from H1.

---

## 9. What would falsify H1 as the primary bottleneck

H1 is weakened if runtime testing shows one or more of the following:

- a fully occupied controlled test pool does **not** starve unrelated DB-backed endpoints;
- pool wait remains negligible while client timeouts occur elsewhere;
- non-DB control degrades first alongside DB-backed endpoints;
- event-loop lag/CPU rises first while pool capacity remains available;
- connection churn/socket exhaustion occurs independently of DB pressure;
- a production-like mixed workload fails with plenty of available DB capacity;
- narrowing DB lease does not improve the exact same workload.

If that happens, we move to the next measured constraint rather than forcing a DB-lifetime patch.

---

## Current strongest static hypothesis

> `/backfill/bars` currently couples external-provider/executor latency to DB-pool occupancy. Under concurrent fresh traffic, that coupling can consume per-worker DB capacity and delay unrelated reads until callers time out and retry.

The mechanism is strongly supported by code inspection. Its **magnitude and causal role in #107 remain runtime questions**.
