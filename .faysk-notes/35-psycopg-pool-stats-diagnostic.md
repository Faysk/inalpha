# Issue #107 — Direct Psycopg Pool Stats Diagnostic

**Status:** contributor-only observability for the baseline harness.  
**Purpose:** measure DB-pool pressure directly instead of inferring it only from `/health` latency.

Official Psycopg pool documentation exposes `get_stats()` / `pop_stats()` for exactly this kind of pool-usage observation:

- https://www.psycopg.org/psycopg3/docs/advanced/pool.html#pool-stats
- https://www.psycopg.org/psycopg3/docs/api/pool.html

The docs also confirm that `pool.connection()` queues callers when no connection is immediately available and raises `PoolTimeout` after the configured timeout.

---

## 1. Why this improves the #107 evidence

Our earlier isolation signal was:

```text
/openapi.json fast
/health slow or timed out
```

That is useful, but still indirect.

The contributor wrapper now exposes the current process's Psycopg pool stats through the DB-free diagnostic endpoint:

```text
GET /__issue107/state
```

The endpoint does **not** acquire a DB connection to read those counters, so it remains observable while the pool itself is saturated.

This uses the private shared `_pool` only in contributor tooling. Production code must not depend on that private symbol.

---

## 2. Metrics that matter most

Psycopg documents these pool counters/state values:

```text
pool_min
pool_max
pool_size
pool_available
requests_waiting
usage_ms
requests_num
requests_queued
requests_wait_ms
requests_errors
connections_num
connections_ms
connections_errors
connections_lost
returns_bad
```

The wrapper prefixes them with `pool_`, so examples become:

```text
pool_pool_max
pool_pool_available
pool_requests_waiting
pool_requests_queued
pool_requests_wait_ms
pool_requests_errors
pool_usage_ms
```

Keys whose value is zero may be omitted by Psycopg, so absence is not automatically an instrumentation bug.

---

## 3. Strong H1 signature

With one data worker and a fake provider delay, current route-level `DBConn` predicts a pattern like:

```text
provider active rises toward pool_max
pool_available falls toward 0
requests_waiting rises above 0
requests_queued increases
requests_wait_ms accumulates
/openapi.json remains responsive
/health stalls or times out
```

That is substantially stronger evidence than `/health` latency alone.

The exact numbers are runtime evidence; do not hard-code them into the conclusion before running.

---

## 4. Candidate A prediction

If Candidate A is selected and works as intended, while the same fake provider calls are sleeping we expect roughly:

```text
provider active can exceed pool_max
BUT
pool_available should recover after each short latest_bar_ts lookup
requests_waiting should remain much lower / near zero during provider wait
/health should stay responsive
```

During persistence after the fake provider releases, short-lived DB contention can still occur.

That is acceptable: the goal is not "DB is never busy." The goal is:

```text
external provider latency no longer reserves DB capacity for its full duration
```

---

## 5. Why `usage_ms` needs careful interpretation

`usage_ms` is cumulative connection usage time outside the pool.

Current baseline can inflate it because each slow backfill holds a connection during external I/O.

Candidate A should reduce that coupling, but raw cumulative values depend on request count and run duration.

Compare either:

```text
same workload before vs after
```

or derive a normalized value such as:

```text
usage_ms / completed backfill
```

Do not compare unrelated run durations.

---

## 6. Queue counters vs instantaneous state

Distinguish:

```text
pool_available / requests_waiting
→ instantaneous state at sample time

requests_queued / requests_wait_ms / requests_num
→ cumulative history since pool creation or stats reset
```

Our wrapper uses `get_stats()`, not `pop_stats()`, so it does not reset counters.

This is intentional because the baseline probe samples:

```text
pre-load
under-load
post-load
```

and can compare deltas.

---

## 7. Multi-worker caveat

Each Uvicorn worker owns its own process-local pool.

Therefore `/__issue107/state` reports only the worker that served that diagnostic request.

The load probe makes several fresh DB-free state requests and groups the observations by PID, but worker selection is not guaranteed.

Correct wording:

```text
observed worker pool states
```

not:

```text
complete container-wide pool state
```

If only one PID is sampled in a two-worker run, preserve that fact rather than pretending the other worker had the same counters.

---

## 8. Pair with `pg_stat_activity`, not replace it

Pool stats answer:

```text
Are application callers queued for DB connections?
How much pool capacity is available?
```

`pg_stat_activity` answers a different question:

```text
What are the checked-out PostgreSQL sessions doing?
Are they idle in transaction while application code waits on provider I/O?
```

The strongest baseline combines both:

```text
Psycopg pool queue/availability
+
Postgres session state
+
HTTP isolation signal
+
provider in-flight counters
```

---

## 9. Baseline capture fields

For each representative phase record, per observed PID where practical:

```text
pool_max
pool_size
pool_available
requests_waiting
requests_queued delta
requests_wait_ms delta
requests_errors delta
usage_ms delta
provider active
thread active
health latency/error
openapi latency/error
```

This should make the H1 decision substantially less subjective.

---

## Current conclusion

We no longer need to infer DB-pool saturation from symptoms alone.

The contributor harness can now measure the application's own pool queue and availability directly while provider work is blocked, without modifying upstream production code or adding a telemetry dependency.