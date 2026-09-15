# Issue #107 — Request / Concurrency Flow Map

**Status:** reviewed against current upstream `main`; refine further after local reproduction.  
**Baseline:** `ed01be9056776c107ab76a404c328a4fed19f529`

---

## 1. Primary paths involved

### A. Live/current factor scoring

```text
client / agent
    ↓
factor API
    ↓
FactorEngine.score / snapshot / timing path
    ↓
is_live = true
    ↓
price bars: _fetch_df(... fresh=True)
    ↓
DataClient.get_bars(... fresh=True)
    ↓
POST data:/backfill/bars
    ↓
GET data:/bars
```

For daily/weekly factor requests with macro factors:

```text
_compute_macro
    ↓
required FRED series (1d snapshot can involve ~18)
    ↓
asyncio.gather(*series)
    ↓
_fetch_macro_series(... fresh=True)
    ↓
_fetch_df(venue="fred", ... fresh=True)
    ↓
new factor DataClient / httpx client per fetch path
    ↓
POST data:/backfill/bars
    ↓
GET data:/bars
```

This is still a meaningful fan-out path in current `main`.

Potential multipliers:

- concurrent user/agent factor requests,
- ~18 macro-series gather,
- short-lived factor HTTP clients,
- retries on GET connection failures,
- overlapping live-runner polling.

---

### B. Cross-sectional panel scoring

```text
client / agent
    ↓
factor /panel/score
    ↓
resolve universe
    ↓
Semaphore(_PANEL_FETCH_CONCURRENCY = 16)
    ↓
_fetch_df(... fresh=False)
    ↓
GET data:/bars
    ↓
TimescaleDB
```

Current mitigation:

- fetch concurrency already bounded at 16,
- panel deliberately avoids forced per-symbol backfill.

Treat panel as an important control/current-state workload, but do not assume it is still the main cause described by the older issue text.

---

### C. Paper / live runner

```text
paper live-runner task
    ↓
periodic _fetch_latest_bar / warmup
    ↓
paper DataClient.get_bars(fresh=True)
    ↓
try POST data:/backfill/bars
    ↓
GET data:/bars
```

Paper's `backfill_bars()` itself raises on non-2xx, but `get_bars(fresh=True)` catches refresh exceptions, logs them, and proceeds to read DB bars.

Current default per-account running-run cap is 10. Multiple accounts can still increase aggregate traffic.

Potential multiplier:

- many runs wake on similar timeframe boundaries.

---

### D. Research

```text
orchestrated deep_dive / analyst
    ↓
research DataClient
    ↓
usually fresh=False because orchestration prefetches
    ↓
optional explicit fresh=True
    ↓
best-effort POST /backfill/bars
    ↓
GET /bars
```

Research intentionally allows some degradation to cached DB data rather than failing the whole analyst fan-out.

---

### E. Dashboard bars BFF

```text
browser SWR
    ↓
dashboard GET /api/bars
    ↓
GET data:/bars
    ↓
if empty/stale:
    process-local inflightBackfill Map
    ↓
coalesce identical key
    ↓
POST data:/backfill/bars
    ↓
GET data:/bars again
```

Important existing mitigation:

- dashboard already performs same-key single-flight/coalescing in its own process.
- refresh failure is intentionally best-effort for display; existing cached bars may still be shown.

This means data-side single-flight should only be added if duplicates from **other/cross-service callers** are measured.

---

### F. Orchestration direct client

```text
agent tool / workflow
    ↓
packages/orchestration DataClient
    ↓
POST data:/backfill/bars
```

Explicit tool/client calls should preserve machine-readable error behavior.

---

## 2. The critical data-service resource timeline

Current `/backfill/bars` signature conceptually begins as:

```text
FastAPI resolves db: DBConn
    ↓
DB pool connection checked out
    ↓
route body starts
```

Then the handler performs:

```text
latest_bar_ts(DB)
    ↓
connector.fetch_bars(EXTERNAL I/O)
    ↓
insert_bars(DB + commit)
    ↓
connector.fetch_bars(EXTERNAL I/O)
    ↓
insert_bars(DB + commit)
    ...
    ↓
route returns
    ↓
DBConn dependency releases pool connection
```

Therefore the same DB connection remains checked out while the handler waits on provider/network work.

Shared pool defaults:

```text
min_size = 2
max_size = 10
checkout timeout = 30s
```

Current production compose:

```text
data WORKERS = 2
```

So there is one pool per worker/process, with process-local connector state and process-local locks/semaphores.

### Design consequence

A semaphore placed only inside the handler body can be too late:

```text
request
→ DBConn already checked out
→ waits on semaphore
```

Queued requests would still occupy the resource we are trying to protect.

Admission waiting and DB connection lifetime must be designed together.

---

## 3. Provider-specific queueing that may amplify DB occupancy

### yfinance

Current yfinance `history` path intentionally uses a process-local `_FETCH_LOCK` and minimum interval:

```text
concurrent yfinance requests
    ↓
_FETCH_LOCK
    ↓
only one history fetch in-flight per data worker
```

This protects Yahoo correctness/rate limits.

But for `/backfill/bars`, requests may already hold DB connections before they wait for that lock.

Diagnostic pattern to test:

```text
many yfinance backfills
→ DB pool slots occupied
→ most requests queued behind provider lock
→ unrelated DB-backed data endpoints slow/wait
```

Do not call this the root cause until reproduced.

---

## 4. Current capacity controls

Known:

```text
factor panel fetches             → semaphore 16
factor GET connection failures   → bounded retry/backoff
factor live macro                → concurrent asyncio.gather of required FRED series
web search                       → configurable semaphore + timeout
web fetch                        → configurable concurrency bound
research LLM                     → configurable concurrency bound
paper live runs/account          → default cap 10
DB pool                          → max 10 per worker
production data workers          → 2
Dashboard bars refresh           → same-key process-local coalescing
yfinance history                 → serialized per data worker
```

To verify:

```text
/backfill/bars admission gate?              currently no generic one observed
/backfill cross-service same-key coalescing? no generic one observed
factor shared HTTP transport/pool?           no; short-lived clients are a hypothesis
FRED/provider-specific internal limits?      inspect/measure as needed
actual deployed worker/container topology?   ask maintainer if different from repo compose
```

---

## 5. Resources that may saturate

Do not use "data-service saturation" as if it names one bottleneck.

Candidates:

1. DB pool checkout starvation
2. DB connection held across external I/O
3. provider-side serialization/latency
4. too many simultaneous upstream calls
5. event-loop/thread-pool starvation
6. HTTP client/socket churn
7. retry amplification
8. duplicate cross-service refresh work
9. live-runner wakeup synchronization
10. DB write latency / long transactions

The first benchmark should identify the first resource that degrades.

---

## 6. Caller compatibility matrix for future backpressure

Before returning a new `429`/`503`/`DATA_SERVICE_BUSY`, fill this with evidence:

| Caller | Purpose | Current refresh failure behavior | Can cached/stale display be acceptable? | Freshness-critical? |
|---|---|---|---|---|
| factor | current factor evidence | non-2xx handling needs explicit verification/fix if busy introduced | not if presented as current | yes for live/current |
| paper | backtest/live execution | backfill error logged then bars read | context-dependent | often yes |
| research | analyst enrichment | best-effort degradation | yes if clearly degraded | context-dependent |
| dashboard | chart display | catches refresh failure | yes | lower risk |
| orchestration | explicit tool | should surface explicit error | no silent fake success | depends on tool |

Do not force every caller into identical semantics.

---

## 7. Known benchmark confounder: yfinance empty success

Current yfinance `fetch_bars` can catch provider/network failure and return an empty list. `/backfill/bars` may then finish with HTTP 200 and `bars_fetched=0`.

That behavior is separately tracked upstream (#74).

For #107:

```text
HTTP 200 != necessarily successful refresh
```

Record:

- bars_fetched,
- bars_inserted,
- latest timestamp progress,
- provider warning logs.

Do not accidentally claim a capacity improvement merely because error responses disappeared while refreshes stopped progressing.

---

## 8. Desired trace for one request

Ideal diagnostic chain:

```text
caller trace=A
  ↓
data request trace=A
  ↓
admission wait (if any)
  ↓
DB latest lookup
  ↓
provider wait/fetch
  ↓
DB write
  ↓
response
```

Current middleware supports `X-Trace-Id`; cross-service forwarding still needs verification. Do not expand `_shared` merely for tracing unless required.

---

## 9. Map update checklist

- [x] map current factor macro fan-out
- [x] map panel current mitigation
- [x] map major `/backfill/bars` callers
- [x] map dashboard same-key coalescing
- [x] map paper refresh degradation behavior
- [x] identify current `/backfill/bars` DB connection lifetime
- [x] identify production data worker count in compose
- [x] identify yfinance provider serialization
- [ ] map exact FRED connector concurrency behavior if baseline points there
- [ ] measure DB pool checkout/wait behavior
- [ ] verify trace-id forwarding
- [ ] confirm deployed topology with maintainer if it differs from repository compose
- [ ] update this map from real baseline evidence
