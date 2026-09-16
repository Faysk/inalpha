# Issue #107 — Data Provider Concurrency Matrix

**Status:** static mapping for post-H1 interpretation.  
**Purpose:** understand what happens *after* DB capacity is decoupled from external provider waits, so a successful DB fix does not accidentally expose a different provider/thread bottleneck.

This is not a proposal to add one global semaphore.

---

## 1. Why provider behavior matters to Candidate A

Current `/backfill/bars` couples provider latency to one checked-out DB connection.

If Candidate A removes that coupling, more requests can reach provider code concurrently.

That is desirable for DB availability, but the resulting provider-side behavior differs substantially by venue.

A single admission limit chosen without understanding those differences could:

- duplicate controls a connector already has;
- reduce useful throughput unnecessarily;
- fail to protect a connector that has no local bound;
- move saturation into the shared thread executor;
- hide provider-specific rate-limit behavior.

---

## 2. Current connector matrix

| Venue | External-I/O implementation | Current local concurrency/rate control | Timeout/cancellation notes | Candidate A moved-bottleneck risk |
|---|---|---|---|---|
| `binance` | native async CCXT | CCXT `enableRateLimit=True`; no Inalpha semaphore around `fetch_bars()` | external behavior controlled mainly by CCXT/network | medium: more backfills can reach CCXT at once |
| `alpaca` | synchronous alpaca-py via `asyncio.to_thread` | no connector-local semaphore in `fetch_bars()` | no explicit outer `wait_for` in bars path | medium/high: more work can enter default executor/provider simultaneously |
| `baostock` | sync public-source calls through throttled thread wrapper | process-local `_FETCH_LOCK`, minimum interval, 30s lock/worker timeout | on timeout/cancel, lock ownership is handed off until worker actually exits | low for raw provider concurrency; high value from releasing DB while callers queue at lock |
| `yfinance` | sync history on dedicated `ThreadPoolExecutor(max_workers=4)` | process-local `_FETCH_LOCK`, min interval; effectively one history request active per process | 30s wrapper timeout; underlying sync thread may outlive coroutine timeout | low for raw history concurrency; high value from releasing DB while callers queue at lock |
| `fred` | `fredapi` synchronous call via `asyncio.to_thread` | no connector-local semaphore | no explicit connector-level outer timeout | high during cold macro bursts; can use shared default executor |

---

## 3. Binance

Current `BinanceConnector.fetch_bars()` directly awaits CCXT's async `fetch_ohlcv()`.

The exchange is configured with:

```text
enableRateLimit = True
```

This gives CCXT its own request-rate pacing, but Inalpha does not currently wrap backfill OHLCV calls in a service-side semaphore.

Important wording:

```text
CCXT rate limiting != proven Inalpha capacity admission
```

Do not claim that `enableRateLimit=True` makes arbitrary application concurrency safe.

After Candidate A, measure:

- CCXT/provider error rate;
- backfill p95;
- number of simultaneous Binance backfills;
- whether data-service remains healthy while CCXT queues/rate-limits internally.

Do not stress Binance externally for the capacity benchmark; use the fake provider first.

---

## 4. Alpaca

`AlpacaConnector.fetch_bars()` wraps synchronous alpaca-py work with:

```python
await asyncio.to_thread(_fetch_sync)
```

There is currently no connector-local semaphore around bars fetches and no explicit outer `asyncio.wait_for` in that path.

Therefore a large burst can consume shared default-executor capacity and make provider latency visible as thread contention.

This is one reason Candidate A's before/after must include the thread-mode fake provider diagnostic before assuming the only scarce resource was DB.

Do not add Alpaca-specific control unless runtime evidence shows it is relevant to #107.

---

## 5. Baostock / Tencent path

The A-share connector already has comparatively careful overload behavior:

```text
process-local async lock
→ minimum source interval
→ bounded wait for lock
→ sync worker wrapped in timeout
→ if caller times out/cancels while worker lives, lock release is handed to a background task
→ next provider call cannot overlap the orphan worker
```

This means current DB/resource order can be particularly wasteful:

```text
many backfill requests
→ each may own DBConn
→ only one reaches source
→ others wait behind provider lock while still retaining DB capacity
```

Candidate A should help this shape without increasing source concurrency, because the connector itself remains serialized.

This makes Baostock a good conceptual example of why the DB lease should not be used as accidental provider admission control.

---

## 6. yfinance

Yfinance intentionally serializes history calls per process with `_FETCH_LOCK` and `_MIN_FETCH_INTERVAL_S`.

It additionally uses a dedicated four-thread executor because a timed-out synchronous Yahoo request may continue after the asyncio wrapper gives up.

Current shape under burst:

```text
request A owns DB → owns Yahoo lock → worker
request B owns DB → waits Yahoo lock
request C owns DB → waits Yahoo lock
...
```

After Candidate A:

```text
request A short DB lookup → releases DB → owns Yahoo lock
request B short DB lookup → releases DB → waits Yahoo lock
request C short DB lookup → releases DB → waits Yahoo lock
...
```

Provider throughput does not need to increase for DB availability to improve.

This is probably the cleanest example of Candidate A removing cross-resource coupling rather than "making providers faster."

Known adjacent behavior (#74) remains separate: yfinance may convert some failures into an empty result.

---

## 7. FRED

`FredConnector.fetch_bars()` performs the synchronous `Fred.get_series()` through `asyncio.to_thread`.

There is no FRED-specific semaphore in the data connector.

The connector source documents a free-service rate budget of roughly 120 requests/minute. Treat that as provider documentation/context, not a target to approach in testing.

Factor's default daily/weekly macro path currently needs 18 unique FRED series.

So Candidate A could reveal either:

- healthy provider parallelism;
- default-executor contention;
- provider rate limiting;
- caller-side cache-stampede amplification.

Do not use real FRED as a stress target. Reproduce these shapes with fake thread-mode provider work, then do only low-volume integration verification if needed.

---

## 8. Why a single global backfill semaphore may be the wrong second move

Suppose runtime after Candidate A shows:

```text
yfinance queue = safe/serialized
baostock queue = safe/serialized
FRED thread burst = problem
Binance async traffic = fine
```

A low global semaphore around all venues could reduce Binance/other throughput while merely duplicating yfinance/baostock controls.

Conversely, a very high global limit may do nothing for FRED/default-executor pressure.

Therefore Candidate C remains evidence-driven. Possible eventual scopes include:

```text
service-wide expensive-work limit
provider/venue-specific limit
factor-side fan-out/single-flight
or no additional gate at all
```

The benchmark decides.

---

## 9. Before/after metrics by provider shape

When Candidate A is tested, classify the workload/provider shape rather than reporting one aggregate number only.

Record where practical:

```text
provider mode / venue
requests reaching provider
peak provider in-flight
provider wait/queue time
provider failures
thread active / orphan work
DB pool occupancy
/health latency
backfill p95
zero/no-progress refreshes
```

Acceptance is not:

```text
DB waits disappeared
```

It is:

```text
DB waits materially improved
AND
provider/error/freshness behavior did not regress into a new failure mode
```

---

## Current conclusion

The connectors are deliberately heterogeneous.

That strengthens the case for testing Candidate A first if H1 is confirmed: it removes an obviously wrong cross-resource lifetime coupling without prematurely imposing one concurrency policy on every provider.

Only after that isolation is measured should we decide whether any provider/factor-side admission control is actually required.