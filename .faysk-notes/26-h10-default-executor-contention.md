# Issue #107 — H10: Shared Default-Executor Contention

**Status:** secondary runtime hypothesis. Do not treat it as the primary #107 root cause without measurement.

---

## 1. Static finding

Several data-service connectors wrap synchronous libraries with `asyncio.to_thread(...)`, including:

- FRED;
- Alpaca;
- web search;
- symbol search;
- portions of web/news parsing;
- Baostock paths.

Repository search finds no `loop.set_default_executor(...)` configuration in the current codebase.

Therefore these `asyncio.to_thread` calls use the event loop's default executor in each worker process unless the underlying connector creates a separate executor itself.

Important exception: yfinance's OHLC history path has its own dedicated executor/lock behavior and should not be lumped blindly into this model.

---

## 2. Why this can interact with #107

Current fresh FRED backfill path is structurally:

```text
HTTP request
→ request-scoped DBConn acquired
→ latest_bar_ts SELECT
→ FredConnector.fetch_bars
→ asyncio.to_thread(sync fredapi call)
```

If many FRED requests arrive together and there are more synchronous jobs than available default-executor threads:

```text
some jobs run in executor threads
other jobs wait in executor queue
```

But under current `/backfill/bars` ordering, **both groups may already own DB connections**.

So DB pressure can be amplified not only by slow provider network latency but also by waiting for a thread slot before the synchronous provider code even starts.

This makes Candidate A conceptually useful even if the measured external delay is partly:

```text
executor queue wait + provider call
```

rather than provider network time alone.

---

## 3. Why we should not guess the thread count

The default executor size depends on Python/runtime/CPU topology and can differ between:

- contributor laptop;
- Docker limits;
- production VPS;
- Python minor versions.

Do not hardcode an assumed value such as `32`, `CPU+4`, or any other formula into #107 reasoning without recording the actual runtime environment.

The important invariant is simpler:

```text
bounded worker-thread capacity exists
and queued to_thread callers should not consume unrelated DB capacity while waiting
```

---

## 4. Prepared fake-provider modes

`tools/issue107_slow_data_app.py` now supports:

```text
ISSUE107_PROVIDER_MODE=async
```

for a cooperative `asyncio.sleep`, and:

```text
ISSUE107_PROVIDER_MODE=thread
```

for `asyncio.to_thread(time.sleep, ...)`.

The latter is not intended to mimic FRED's HTTP behavior exactly. It isolates the resource shape:

```text
async request awaits synchronous worker-thread capacity/work
```

The wrapper exposes both coroutine-level and thread-level counters:

```text
provider active/started/completed/cancelled/failed
thread active/started/completed
```

---

## 5. Cancellation distinction

Thread mode also prevents a common false conclusion.

An asyncio request/provider waiter can be cancelled while an already-running synchronous function in a worker thread continues until it returns.

Possible observation:

```text
provider_cancelled increases
provider_active falls to 0
BUT
thread_active remains > 0
```

That means request/DB capacity may have been released while executor capacity is still occupied.

This is especially relevant when interpreting H9:

```text
“request cancelled” != “all underlying provider work stopped”
```

Connector implementation determines the real behavior.

---

## 6. Experiment

After the normal async fake-provider baseline, repeat one-worker service-level runs with:

```text
ISSUE107_PROVIDER_MODE=thread
```

Use the same:

- provider delay;
- backfill count;
- health/openapi probes;
- client limits.

Record:

```text
provider_started
provider_active peak
thread_started
thread_active peak
health p95/timeouts
openapi p95/timeouts
backfill p95
DB state / idle-in-transaction count
client timeout types
```

Then compare async vs thread mode.

---

## 7. Evidence for H10 materiality

H10 becomes relevant if:

- thread-backed mode shows substantial requests queued before sync work starts;
- DB-backed endpoints degrade while those queued provider waiters retain DB leases;
- non-DB control remains responsive;
- after Candidate A, DB-backed health/read traffic recovers even though thread/provider p95 remains high;
- executor queueing remains a meaningful second bottleneck after DB lease isolation.

If Candidate A solves the issue target and thread queueing only makes individual backfills slower, do not add executor-management work to PR #107.

---

## 8. Do not “fix” H10 first by replacing the global executor

Avoid first moves such as:

```text
set a huge default ThreadPoolExecutor
increase worker threads until symptoms disappear
create a custom executor for every connector
```

without evidence.

Those can move the bottleneck to provider rate limits, CPU, memory, sockets, or DB writes.

If executor capacity really remains the first bottleneck after DB lease correction, choose the smallest connector-specific or admission-control solution supported by measurement.

---

## 9. Relationship to other hypotheses

```text
H1  = DB lease retained across provider/external wait
H8  = duplicate cold same-key macro work multiplies requests
H9  = client timeout may leave older server/provider work alive
H10 = synchronous provider work may queue/continue in shared executor capacity
```

They can coexist, but the first PR should not attempt to solve all four merely because static code allows them.
