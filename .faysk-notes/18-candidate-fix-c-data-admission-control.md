# Issue #107 — Candidate Fix C: Data-Side Backfill Admission Control

**Status:** secondary candidate. Do not implement unless runtime evidence shows that narrowing DB lease is insufficient and external backfill work itself still saturates data-service/provider capacity.

---

## 1. Problem this candidate addresses

Candidate A removes the coupling:

```text
slow provider I/O ↔ scarce DB connection lease
```

But it deliberately does **not** limit the number of provider calls that may be in flight.

If, after Candidate A (or if H1 is falsified), the representative workload still shows:

```text
excessive external in-flight work
→ provider/API saturation
→ event-loop/thread/executor pressure
→ unstable p95 / transport failures
```

then data-service needs a generic admission boundary for expensive backfill work.

---

## 2. Placement rule

The most important rule is:

> A request must not wait for backfill admission while already holding a scarce DB connection.

Therefore Candidate C is only safe if either:

1. DB lifetime has already been narrowed as in Candidate A; or
2. admission happens in a dependency/boundary that executes before any DB checkout.

Do **not** implement:

```text
DBConn dependency resolves
→ request owns DB connection
→ await semaphore
```

That would bound provider concurrency while still allowing the wait queue to consume the DB pool.

---

## 3. Smallest process-local model

A first implementation, if justified, should be process-local and explicit about that fact.

Possible setting:

```text
DATA_BACKFILL_MAX_CONCURRENCY
```

Possible state:

```python
_backfill_sem = asyncio.Semaphore(settings.data_backfill_max_concurrency)
```

Per production worker:

```text
limit N
× 2 data workers
→ effective container upper bound up to ~2N
```

Actual aggregate concurrency can be lower/uneven depending on worker request distribution.

Never call this a “global” limit.

---

## 4. Queueing policy choices

### Model C1 — wait indefinitely for a slot

```text
request
→ await semaphore
→ provider work
```

Simple, but dangerous:

- queue latency can grow without bound;
- client may time out before admission;
- timed-out clients can leave useless queued work/cancellation complexity;
- overload remains implicit.

Not preferred without strong reason.

### Model C2 — bounded wait, then explicit busy response

```text
request
→ wait up to queue budget
→ slot available: continue
→ budget exhausted: return stable temporary-capacity error
```

Operationally clearer, but changes the HTTP contract and therefore invokes the caller compatibility matrix.

Potential config:

```text
DATA_BACKFILL_QUEUE_TIMEOUT_S
```

No default is selected yet.

### Model C3 — no queue, immediate rejection when full

Fast feedback and no server queue, but may be too aggressive for short provider operations and can push retry pressure into callers.

Not preferred by default.

---

## 5. HTTP status/code is deliberately undecided

Potential machine code:

```text
DATA_SERVICE_BUSY
```

Possible statuses:

```text
429 Too Many Requests
503 Service Unavailable
```

But current caller semantics make this non-trivial:

- factor's best-effort POST does not inspect a plain non-2xx response;
- paper parses it, but `get_bars(fresh=True)` degrades to cache;
- live runner treats 4xx and 5xx differently in retry classification;
- orchestration surfaces non-2xx explicitly.

Therefore Candidate C must not choose a status until the affected caller path is defined.

If Candidate A makes the service stable enough, avoiding this contract change is preferable.

---

## 6. Global vs per-provider capacity

### First option: one generic per-worker limit

Advantages:

- smallest code/config surface;
- protects the service regardless of caller;
- easy to test;
- matches the issue's shared data-service capacity concern.

Risk:

- a slow provider can occupy all slots and delay unrelated providers.

### Later option: global + per-provider limits

Conceptually:

```text
global gate N
+ provider gates
  yfinance Y
  fred F
  binance B
  ...
```

This gives isolation but adds significant tuning/configuration surface.

Do not add provider-specific limits unless the benchmark shows provider monopolization/starvation.

Yfinance already serializes its own history calls per process, so blindly adding another yfinance semaphore may be redundant.

---

## 7. Configuration default must be measured

Issue #107 mentions numbers such as 6–8 as examples.

Those are not implementation requirements.

A default must balance:

```text
throughput
provider behavior
queue latency
CPU/thread/executor pressure
DB write pressure
2-worker effective aggregate concurrency
```

Candidate values should be benchmarked against the exact same workload.

Do not commit a magic number because it “sounds safe.”

---

## 8. Observability if Candidate C is selected

Use existing structured logging before adding a telemetry platform.

Minimum useful fields/events:

```text
backfill_admission_wait_ms
backfill_admission_acquired
backfill_admission_timeout
backfill_in_flight (process-local)
venue
symbol/timeframe where safe/useful
trace_id (already middleware context)
provider_fetch_ms
total_request_ms
```

Do not log secrets/tokens.

A process-local in-flight count must be labeled/documented as process-local under two-worker production topology.

---

## 9. Cancellation correctness

Any semaphore implementation must guarantee slot release under:

```text
success
provider exception
DB exception
client disconnect/cancellation
unexpected exception
```

Prefer structured context-manager semantics:

```python
async with limiter:
    ...
```

or an equally clear `try/finally`.

A leaked slot converts a temporary error into permanent capacity loss until worker restart.

---

## 10. Historical reads should remain independent

The gate should protect expensive **backfill/provider work**, not ordinary cached reads.

Desired isolation:

```text
backfill saturated
≠
GET /bars(fresh cache read) unavailable solely because it shares the gate
```

Historical `fresh=False` consumers should continue to read persisted data without waiting for provider capacity whenever DB capacity exists.

This is one of the main architectural reasons to gate the backfill boundary rather than the entire data service.

---

## 11. Deterministic test plan if selected

Tests should use fake blocking connectors.

At minimum:

- [ ] provider peak concurrency never exceeds configured per-worker limit;
- [ ] queued work does not own DB connections while waiting;
- [ ] ordinary DB-backed `/bars`/health remains responsive within expected DB capacity;
- [ ] slot released on provider exception;
- [ ] slot released on DB write exception;
- [ ] slot released on cancellation;
- [ ] bounded wait produces the selected stable error;
- [ ] selected error is compatible with factor/paper/orchestration callers;
- [ ] different providers are not unintentionally serialized if generic capacity is available;
- [ ] two-worker test documents aggregate/process-local behavior.

---

## 12. Before/after success criteria

Candidate C should only survive review if it improves the representative workload, not merely lowers a concurrency counter.

Compare:

```text
DATA_SERVICE_UNREACHABLE
concrete HTTPX timeout/error classes
p50 / p95 / p99
queue/admission wait
provider peak in-flight
successful data progress
historical read latency
CPU/memory/thread behavior
```

If a lower concurrency limit simply turns transport timeouts into long queue waits beyond caller deadlines, it is not a useful fix.

---

## 13. Why not start with Candidate C

Static review already found a simpler resource-ordering problem candidate: `/backfill/bars` holds DB capacity across provider waits.

If that is the dominant mechanism, adding an admission gate first risks masking the underlying coupling and introduces new queue/error semantics.

Preferred sequence:

```text
baseline
→ prove/falsify H1
→ Candidate A if justified
→ rerun identical mixed workload
→ Candidate C only if provider/in-flight saturation remains
```

---

## Selection gate

Choose Candidate C only if measurements show all of the following:

1. external backfill concurrency itself remains a material saturation source;
2. the problem is not solved sufficiently by narrowing DB resource lifetime;
3. a bounded concurrency experiment improves p95/error behavior;
4. the chosen limit does not create unacceptable queue latency;
5. caller behavior for any explicit overload response is intentionally handled.

Until then, this is a prepared fallback rather than part of PR 1.
