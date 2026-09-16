# Issue #107 — Active Investigation

**Status:** active while maintainer feedback is pending.  
**Rule:** continue non-invasive investigation and baseline preparation; do not change production behavior before reproducible evidence exists.

---

## 1. Decision

We are **not blocking engineering work on the maintainer reply**.

The maintainer's response can still change scope or priorities, but useful low-risk work continues now:

```text
static code-path verification
→ local environment preparation
→ pre-change tests
→ deterministic reproduction
→ baseline evidence
```

Production behavior remains unchanged until the failure is reproduced and the first constrained resource is identified.

---

## 2. Static findings now confirmed from code

### DB connection lifetime

`DBConn` is implemented as a FastAPI dependency backed by:

```text
_db_dep()
→ get_conn()
→ async with _pool.connection()
→ yield connection
```

Because `/backfill/bars` accepts `db: DBConn`, that checked-out connection remains scoped to the route invocation unless the route is restructured.

Current backfill flow is therefore effectively:

```text
checkout DB connection
→ latest_bar_ts()
→ external connector.fetch_bars()
→ insert_bars()
→ possibly repeat provider fetch/write loop
→ route returns
→ DB connection released
```

This confirms the **lifetime behavior**. It does **not** yet prove that DB-pool pressure is the root cause of #107.

### Current backfill is not one atomic request transaction

`insert_bars()` explicitly commits every persisted batch.

So a multi-batch backfill already has durable per-batch boundaries. Candidate A would change connection lease duration, not split one request-wide transaction that currently exists.

The first `latest_bar_ts()` SELECT does start a transaction under Psycopg's default `autocommit=False`; current code can then await the first provider call while that read-only transaction and the pool lease remain open.

After a batch commit, later provider waits may no longer have an active transaction, but the connection remains reserved to the route until request exit.

Primary issue wording therefore remains:

```text
pool slot retained across external I/O
```

not merely “idle in transaction.”

### Pool size and health path

The shared DB pool defaults to:

```text
min_size = 2
max_size = 10
timeout = 30s
```

`data-service` initializes that pool without overriding the defaults.

`GET /health` itself depends on `DBConn` before running its `SELECT 1`. Therefore a request can be unable to enter the health handler while waiting for a saturated pool.

Current production compose checks `/health` with a **2-second urllib timeout** / 3-second Docker healthcheck timeout and runs `data-service` with **2 workers**.

This creates an important operational hypothesis:

```text
slow backfills retain DB connections
→ one worker exhausts its 10-slot DB pool
→ unrelated /bars and /health requests assigned to that worker wait for DB capacity
→ healthcheck may time out before the pool's own 30s timeout
→ callers may observe latency/timeouts even though the process/event loop is still alive
```

This needs runtime evidence before being described as a production root cause.

### Timeout alignment and potential retry amplification

Factor's `DataClient` uses a 30-second default HTTP timeout for `GET /bars`.

The data DB pool also has a 30-second checkout timeout.

Factor then retries connection/request-level `httpx.RequestError` up to 3 times with short backoff.

So pool starvation has a plausible path to the exact symptom named by #107:

```text
GET /bars accepted by data-service
→ request waits for DBConn
→ caller reaches ~30s HTTP timeout
→ httpx timeout is classified as RequestError
→ factor retries
→ repeated requests add more pressure
→ eventually DATA_SERVICE_UNREACHABLE
```

This is hypothesis **H1b**. It is stronger than the original generic “data-service is saturated” theory because every step is supported by current code, but it still needs runtime reproduction.

Do not yet claim that timed-out server work continues after client disconnect; cancellation behavior must be observed separately.

### Provider serialization can amplify DB retention

The yfinance connector intentionally serializes `history()` calls per process behind `_FETCH_LOCK` and a minimum request interval. It also uses a dedicated bounded thread pool.

That means a burst of yfinance backfills can become:

```text
request A: DBConn + Yahoo lock + provider I/O
request B: DBConn + waits for Yahoo lock
request C: DBConn + waits for Yahoo lock
...
```

The serialization is correct for Yahoo rate-limit/data-quality protection. The #107 concern is the **resource ordering**: requests may own DB capacity while queued behind a provider-level lock.

### FRED fan-out uses external threads without a local data-service gate

FRED `fetch_bars()` runs its synchronous client through `asyncio.to_thread`. There is no FRED-specific semaphore in the connector.

Live/current factor macro calculation can concurrently request roughly 18 FRED series. Each fresh series request can trigger `/backfill/bars`.

This gives us a second deterministic workload shape to reproduce after the synthetic slow-connector test:

```text
factor macro gather (~18)
→ multiple fresh FRED backfills
→ each data request obtains DBConn before external FRED I/O
```

### Cold macro cache can stampede

The factor macro cache is module-level and therefore shared across request-scoped `FactorEngine` instances in the current one-worker factor deployment.

But `_fetch_macro_series()` currently does:

```text
cache get
→ await _fetch_df(... fresh=True)
→ cache put
```

with no per-key in-flight coalescing.

Therefore several concurrent cold requests for the same macro/date key can all miss before the first result is cached and each launch duplicate factor→data work.

The cache is known to work **after population**; existing tests cover that sequential hit path. They do not cover simultaneous same-key misses.

This is now hypothesis **H8**:

```text
cold concurrent live factor calls
→ same macro keys miss simultaneously
→ duplicate same-key FRED/backfill work
→ factor fan-out multiplier larger than “18 series once”
```

A pure factor-unit diagnostic has been prepared and uses no data-service/FRED network.

### Factor client lifetime

`get_engine()` creates a new `FactorEngine` for each factor request.

`FactorEngine._fetch_df()` then does:

```text
async with DataClient(...) as dc
→ DataClient creates httpx.AsyncClient
→ get_bars()
→ client closes
```

Macro factor fan-out calls `_fetch_df()` concurrently for multiple required FRED series.

Therefore short-lived factor→data HTTP clients are real current behavior and remain a measurable connection-churn hypothesis.

### Factor fresh-backfill status behavior

Factor's `_best_effort_backfill()` awaits:

```text
POST /backfill/bars
```

but does not call `raise_for_status()` or otherwise inspect the returned HTTP status.

So a future HTTP `429` / `503` from `/backfill/bars` would not automatically enter the exception path in this helper. The code would continue to `GET /bars` afterward.

This is an important compatibility constraint for any admission-control design.

### Adjacent data-service DB lease findings

`/backfill/bars` is not the only data path where request-scoped DB capacity can overlap external I/O.

`GET /ticker?fresh=true` declares `db: DBConn`, but the fresh branch does not use DB at all; it directly awaits the venue connector's external ticker call. A fresh ticker can therefore reserve a DB connection unnecessarily during provider I/O.

`POST /constituents/snapshot` and the background constituent scheduler also keep a DB connection while awaiting an external constituent fetch before persistence.

These are **adjacent findings, not automatic #107 scope**:

- fresh ticker can overlap real trading/order activity and should be measured if it appears in the representative mixed workload;
- constituent snapshots are low-frequency/config-dependent and should stay out of #107 unless evidence says otherwise.

Do not broaden the first PR just because the same resource-ordering smell exists elsewhere.

### Other caller behavior

Current caller behavior differs by component:

- **paper**: explicit `backfill_bars()` converts non-2xx responses into `DataServiceError`; `get_bars(fresh=True)` catches refresh failure and then continues to read bars.
- **research**: best-effort backfill intentionally degrades to DB-cached data.
- **dashboard**: stale/empty chart refresh is best-effort and already has process-local same-key coalescing.
- **orchestration**: shared TypeScript `HttpClient` throws `HttpClientError` on any non-2xx and preserves upstream error code/status/details.

Therefore a new busy/backpressure response cannot be evaluated only at the data-service route. Caller semantics are part of correctness.

---

## 3. What is confirmed vs still hypothetical

### Confirmed

- route-scoped `DBConn` holds a pool connection across the current `/backfill/bars` handler lifetime;
- current backfill persists/commits per batch rather than as one request-wide transaction;
- pool default is 10 connections per process with 30s checkout timeout;
- `/health` also requires `DBConn` before its handler executes;
- production compose currently configures two data workers and a short `/health` probe timeout;
- yfinance serializes `history()` calls per process;
- FRED calls synchronous provider code through `asyncio.to_thread` without a data-service admission gate;
- factor creates short-lived `httpx.AsyncClient` instances through `_fetch_df()`;
- factor `GET /bars` timeout is also 30s and request-level failures can be retried up to 3 times;
- live macro factor fetches can fan out concurrently;
- macro cache population currently has no same-key in-flight coalescing;
- dashboard already coalesces same-key chart backfills;
- factor/research best-effort backfill semantics differ from orchestration's explicit HTTP-error semantics;
- fresh ticker currently reserves route-level DB capacity despite not using DB in its fresh branch;
- constituent snapshot fetch can also retain DB capacity across external provider I/O.

### Still hypotheses

- DB-pool exhaustion is the first resource that causes #107;
- pool wait + factor timeout/retry is the dominant path to `DATA_SERVICE_UNREACHABLE`;
- shortening DB lifetime alone fixes the representative workload;
- a backfill admission gate is necessary;
- connection pooling in factor materially affects p95/error rate;
- cross-service duplicate backfills are frequent enough to justify data-side single-flight;
- cold macro same-key duplication is frequent/material enough to justify factor-side single-flight;
- live-runner synchronization is still a significant contributor after current mitigations;
- fresh ticker overlap materially contributes to the #107 workload;
- client disconnect leaves timed-out server work alive long enough to amplify pressure.

Do not write PR language that treats any item in the second list as proven until runtime evidence exists.

---

## 4. Deterministic diagnostics prepared

### Backfill / DB pool

```text
.faysk-notes/tools/test_backfill_pool_pressure_draft.py
```

It uses a fully fake connector that blocks provider I/O and performs **no external network calls**.

Control/pressure cases:

```text
9 blocked backfills
→ 9/10 DB pool slots occupied
→ /health should still acquire the remaining connection

10 blocked backfills
→ 10/10 DB pool slots occupied
→ /openapi.json should remain responsive
→ /health should remain blocked until the fake provider releases
```

This does not by itself reproduce the full #107 mixed workload. Its purpose is narrower: prove whether current route/resource ordering can starve an unrelated DB-backed endpoint exactly as static inspection predicts.

### Macro cache stampede

```text
.faysk-notes/tools/test_macro_cache_stampede_draft.py
```

Pure factor-unit diagnostic, no external network:

```text
sequential same-key macro requests
→ expected 1 fetch total after cache population

6 simultaneous cold same-key macro requests
→ expected current-main behavior: 6 independent fetches enter before cache put
```

This proves structural duplicate in-flight work if observed, but not production materiality.

When run locally, preserve results even if they disprove our hypotheses.

---

## 5. Immediate runtime sequence

Once the contributor machine has the repository locally:

```text
1. verify exact upstream commit
2. start unmodified stack / test DB
3. run existing data/factor tests
4. run pure factor macro-stampede diagnostic
5. copy/run the contributor-only DB pool-pressure diagnostic
6. record whether 9-vs-10 behavior matches H1
7. establish one-worker service-level diagnostic run
8. reproduce slow-provider/backfill pressure over real HTTP
9. inspect DB-pool behavior and request latency
10. repeat with production-like data WORKERS=2
11. exercise live factor + macro fan-out (cold single, cold concurrent, warm)
12. add runner/resume-like traffic only after isolated scenarios are understood
13. include fresh ticker only if representative workflow actually reaches it materially
14. record baseline before any production change
```

---

## 6. First decision gate

After the initial deterministic reproduction, choose **one** first intervention based on evidence:

```text
DB connection retained across slow I/O is material
→ investigate shortening DB checkout lifetime (Candidate A)

expensive provider work itself saturates first
→ investigate bounded admission before scarce-resource checkout (Candidate C)

cold macro duplicate same-key work is material
→ investigate factor-side single-flight and/or bounded fan-out only after primary data behavior is understood

caller connection churn is material
→ investigate safe HTTP connection reuse

none of the above explains failure
→ keep investigating; do not force the planned solution
```

Candidate A remains the least contract-changing first fix **if H1 is measured**. H8 does not automatically mean factor should be changed in the same PR.

---

## 7. Current stance

We continue working while feedback is pending, but we separate:

```text
work that improves understanding / reproduction
from
work that changes upstream production behavior
```

The first category proceeds now. The second requires evidence and still remains subject to maintainer feedback before the PR is finalized.
