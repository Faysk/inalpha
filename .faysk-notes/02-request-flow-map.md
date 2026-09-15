# Issue #107 — Request / Concurrency Flow Map

**Status:** working map; refine after local reproduction.

---

## 1. Primary paths involved

### Live/current factor scoring

```text
client / agent
    ↓
factor API
    ↓
FactorEngine.score / timing
    ↓
_is_live = true
    ↓
FactorEngine._fetch_df(... fresh=True)
    ↓
DataClient.get_bars(... fresh=True)
    ↓
POST data:/backfill/bars   # best-effort refresh
    ↓
provider fetch + DB persistence
    ↓
GET data:/bars
    ↓
TimescaleDB query
    ↓
factor computation / effectiveness
```

Potential load multipliers:

- multiple simultaneous factor requests,
- macro series fan-out,
- multi-symbol requests,
- retries after connection-level failures.

### Cross-sectional panel scoring

```text
client / agent
    ↓
factor /panel/score
    ↓
resolve symbol universe
    ↓
async symbol fetches
    ↓
Semaphore(_PANEL_FETCH_CONCURRENCY = 16)
    ↓
GET data:/bars with historical/cache semantics
    ↓
TimescaleDB
```

Important current mitigation:

- concurrency already bounded,
- panel path intentionally avoids forcing a fresh backfill for every symbol.

### Live runner

```text
paper live runner tasks
    ↓
periodic fresh bar polling
    ↓
paper DataClient / data-service
    ↓
backfill/read path
    ↓
provider + DB
```

Potential issue:

Many runs can wake around similar timeframe boundaries and compete with interactive factor/research workloads.

### Direct/other backfill callers

```text
caller
    ↓
POST /backfill/bars
    ↓
validate venue/timeframe/window
    ↓
resolve connector
    ↓
fetch external provider
    ↓
write bars to DB
```

This is the expensive shared boundary we currently suspect should receive server-side admission control.

---

## 2. Existing capacity controls

Known existing controls:

```text
factor panel                    → semaphore = 16
factor connection failures      → bounded GET retry/backoff
web search                      → configurable semaphore + overall timeout
research LLM                    → configurable semaphore
live runner                     → run/account limits + retry classification
DB                              → async connection pool
```

Unknown / to confirm:

```text
/backfill/bars global in-flight gate?
/backfill/bars per-provider gate?
same-key coalescing?
shared factor→data HTTP connection pool?
provider-specific connector locks/serialization?
```

---

## 3. Resources that may saturate

Do not assume "data-service saturated" means one thing.

Possible bottlenecks:

1. Uvicorn/event-loop scheduling
2. synchronous provider libraries wrapped in threads
3. external provider latency/rate limiting
4. too many simultaneous upstream calls
5. DB connection pool exhaustion
6. slow DB writes/transactions
7. HTTP client/socket churn from callers
8. retries multiplying load
9. duplicate same-key refreshes
10. live-runner burst synchronization

We need measurements that separate these.

---

## 4. Desired trace for one request

Ideal debugging path:

```text
factor request trace_id=A
  ↓
factor data call trace_id=A
  ↓
data backfill trace_id=A
  ↓
capacity wait
  ↓
provider fetch
  ↓
DB write
  ↓
GET /bars
  ↓
response
```

Current request middleware supports `X-Trace-Id`, but cross-service forwarding needs verification.

---

## 5. Important correctness boundary

Current live factor flow may refresh best-effort and then read cached DB bars.

If admission control returns a non-2xx result that a caller does not interpret correctly, the caller may continue using stale DB data.

Therefore the flow to verify is:

```text
POST /backfill/bars fails/busy
        ↓
Does caller know refresh failed?
        ↓
Does response expose degraded freshness?
        ↓
Can stale data accidentally appear current?
```

This must be answered before finalizing overload semantics.

---

## 6. Map update checklist

- [ ] map exact factor API endpoints involved in #107
- [ ] map macro fan-out implementation
- [ ] map all callers of `/backfill/bars`
- [ ] map paper live-runner data client
- [ ] identify connector-specific semaphores/locks
- [ ] identify where DB connections are acquired/released
- [ ] identify HTTP client lifetime per service
- [ ] identify all retries/timeouts in the path
- [ ] identify trace-id propagation gaps
- [ ] confirm production worker/container topology
