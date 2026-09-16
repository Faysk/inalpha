# Issue #107 — Error Classification and Retry Chain

**Status:** static error-path analysis.  
**Purpose:** avoid treating `DATA_SERVICE_UNREACHABLE` as proof of a literal TCP connection refusal.

---

## 1. Important correction to how we read the issue

Issue #107 describes failures such as:

```text
failed to reach data-service
DATA_SERVICE_UNREACHABLE
```

In current factor code, this code is produced for **any `httpx.RequestError`** after the bounded GET retry loop is exhausted.

HTTPX's exception hierarchy places all of these under `RequestError`:

```text
ConnectTimeout
ReadTimeout
WriteTimeout
PoolTimeout
ConnectError
ReadError
WriteError
RemoteProtocolError
...
```

Official HTTPX reference:

- https://www.python-httpx.org/exceptions/
- https://www.python-httpx.org/advanced/timeouts/

Therefore:

> `DATA_SERVICE_UNREACHABLE` means “the factor client could not complete the HTTP request at transport level after retries,” not necessarily “the OS refused the TCP connection.”

This matters a lot for root-cause work.

---

## 2. Why server slowness can look like “unreachable”

Current factor GET path:

```text
httpx.AsyncClient(timeout=30s)
→ GET /bars
→ catch httpx.RequestError
→ retry up to 3 attempts
→ final DataServiceError(code=DATA_SERVICE_UNREACHABLE)
```

If the TCP connection succeeds but the data service waits too long for a DB connection, the client can raise `ReadTimeout` while waiting for response bytes.

`ReadTimeout` is a `RequestError`.

So this sequence is possible:

```text
TCP connect succeeds
→ server request waits on internal capacity
→ no response bytes for ~30s
→ client ReadTimeout
→ factor says DATA_SERVICE_UNREACHABLE
```

The wording “unreachable” therefore collapses server saturation and actual network/connectivity problems into the same machine code.

---

## 3. 30-second race: DB pool timeout vs HTTP read timeout

Current values are unusually close:

```text
psycopg pool checkout timeout = 30 s
factor GET client timeout      = 30 s
```

Under DB-pool starvation, two clocks race:

### Outcome A — server pool timeout wins

```text
DB dependency waits ~30s
→ psycopg_pool.PoolTimeout
→ dependency fails before route handler
→ shared generic exception handler
→ HTTP 500 INTERNAL_ERROR
→ factor receives HTTP response
→ no transport retry
→ DataServiceError(code=INTERNAL_ERROR)
```

### Outcome B — client read timeout wins

```text
DB dependency waits
→ factor sees no response bytes for ~30s
→ httpx.ReadTimeout
→ RequestError retry
→ eventually DATA_SERVICE_UNREACHABLE
```

Small scheduler/network timing differences can therefore produce different observed error classes from the same underlying capacity condition.

### Baseline requirement

Do not aggregate these together as simply “failures.” Record separately:

```text
ConnectError
ConnectTimeout
ReadTimeout
HTTP 500 INTERNAL_ERROR
HTTP 502
HTTP 429/503 if introduced later
```

---

## 4. Fresh backfill path has a different timeout

Factor fresh flow:

```text
POST /backfill/bars timeout=60s
→ GET /bars default timeout=30s
```

The POST helper does not inspect non-2xx status.

Under pool saturation:

```text
POST backfill waits for DB pool
→ server may return 500 after pool timeout
→ factor does not inspect the 500
→ proceeds to GET /bars
→ GET also competes for the same pool
→ GET can hit 30s ReadTimeout
→ retry
```

This can make the original capacity problem look like a GET connectivity problem even though the pressure began in backfill.

This is a key reason to correlate POST + GET + DB capacity in the same scenario.

---

## 5. Retry amplification

Factor GET retries only `RequestError`, not HTTP 4xx/5xx.

That is correct for brief transport blips, but during sustained latency saturation:

```text
request waits until timeout
→ retry shortly after
→ same saturated service receives another request
→ request waits until timeout
→ retry
```

The retries are bounded, so this is not an infinite storm, but they can still amplify the number of pending requests during a sustained capacity event.

The issue itself explicitly notes this distinction: retries absorb transient blips but cannot solve sustained overload.

### Benchmark metric

For each logical factor read, record if practical:

```text
logical operation count
physical HTTP attempt count
```

If physical attempts rise significantly during saturation, retry amplification is confirmed as a secondary effect.

---

## 6. Live-runner error semantics are different

Paper's client converts non-2xx backfill responses into `DataServiceError`, but `get_bars(fresh=True)` catches the refresh error and proceeds to cached `/bars`.

Transport failure on the final GET still raises.

The live runner then classifies `InalphaError` by status:

```text
4xx → deterministic / non-retryable
5xx → retryable
other network/unknown → retryable
```

This is relevant if we later introduce an explicit busy error:

- a `429` could be interpreted as non-retryable in a path where temporary capacity should probably be retried;
- a `503` fits current retry classification better, but could still cause synchronized retry if not bounded/staggered.

No status choice is approved yet.

---

## 7. Restart/resume can create a natural burst

Paper service startup currently:

```text
list all running strategy runs
→ for run in running: manager.start(run)
→ each start immediately creates an asyncio task
```

Each task's build path includes live warmup, and warmup calls:

```text
get_bars(... fresh=True)
```

So after a paper-service restart, multiple residual running strategies can rebuild/warm up concurrently.

This creates a natural **resume thundering-herd** scenario independent of normal steady-state poll alignment.

It is a useful later mixed-load test because it comes directly from real current behavior, but changing resume scheduling is not automatically part of #107.

---

## 8. What to log/measure locally

Our contributor load client should preserve concrete exception type instead of immediately mapping everything to `DATA_SERVICE_UNREACHABLE`.

Suggested categories:

```text
ok_2xx
http_4xx
http_5xx
connect_timeout
read_timeout
write_timeout
client_pool_timeout
connect_error
read_error
protocol_error
other_request_error
```

For HTTP error responses, also retain:

```text
upstream code
status
trace id
latency
```

For successful backfill responses retain:

```text
bars_fetched
bars_inserted
latest timestamp progress
```

---

## 9. PR wording rule

Do not write:

```text
data-service refused connections because the DB pool was exhausted
```

unless runtime evidence proves actual connect refusal and causal attribution.

Prefer evidence-specific wording, for example:

```text
Under the reproduced workload, DB-backed requests waited behind backfills holding all
10 worker pool connections. Factor GETs then reached their HTTP read timeout and were
reported as DATA_SERVICE_UNREACHABLE.
```

That statement should only be used if the baseline actually shows that sequence.

---

## Working principle

> Error codes are observations from one layer, not root causes.

For #107, preserve the original exception subtype long enough to identify where time was actually spent.
