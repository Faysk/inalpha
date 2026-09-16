# Issue #107 — Things We Should Not Do First

**Purpose:** prevent an attractive but weak “fix” from being implemented before the measured bottleneck is understood.

These are not permanent bans. They are **rejected as first moves** unless evidence changes the decision.

---

## 1. Increase the DB pool size

Tempting reaction:

```text
max_size=10 is filling
→ make it 20/30/50
```

Why not first:

- does not remove the coupling between external provider latency and DB leases;
- can simply allow more slow provider requests to hold more DB connections;
- increases database resource use across each worker;
- changes capacity globally for the service without proving DB execution itself needs more parallelism;
- can hide the symptom until a larger load spike.

Production Postgres currently allows many more connections at the server level, but that does not make a larger application pool automatically correct.

Pool tuning remains valid **after** the request resource lifetime is understood and measured.

---

## 2. Add more Uvicorn workers

Production already uses two data workers.

Adding workers can improve throughput for some independent event-loop blocking, but:

- every worker creates another DB pool;
- every worker duplicates process-local locks/caches/semaphores;
- yfinance's lock becomes one lock per worker, increasing aggregate Yahoo concurrency;
- more workers can shift pressure downstream instead of fixing it;
- issue #107 is a sustained-capacity problem, not automatically a worker-count problem.

Scaling can be a later capacity lever, not our first root-cause fix.

---

## 3. Lower `_PANEL_FETCH_CONCURRENCY` blindly

Current panel path already:

```text
limit = 16
fresh=False
```

So it no longer reproduces the original per-symbol fresh-backfill avalanche described in the June issue.

Changing 16 → 8 or 6 without a current benchmark would optimize an old traffic shape and could just make panel requests slower.

Keep panel as a control workload unless measurements point back to it.

---

## 4. Add a semaphore inside `/backfill/bars` after `DBConn` resolves

This is the most dangerous superficially-correct fix.

Bad order:

```text
FastAPI DBConn checkout
→ request owns DB connection
→ await semaphore
→ provider
```

It limits provider concurrency but lets queued requests consume the DB pool.

That can make the service look more controlled while unrelated DB requests become worse.

Any gate must be before scarce-resource checkout, or DB lifetime must be narrowed first.

---

## 5. Add more client retries

Factor already has bounded transport retries specifically to absorb brief connection blips.

During sustained overload:

```text
timeout
→ retry
→ more pending load
→ timeout
```

More retries can improve a transient-success metric while increasing pressure and total latency.

Issue #107 itself explicitly says existing retries do not solve sustained overload.

---

## 6. Change current analysis to `fresh=False`

This would reduce provider/backfill traffic dramatically but violate a documented business invariant.

Current/live factor timing requires fresh data; stale output without a stale/degradation signal is considered a correctness bug.

Performance improvement obtained by weakening freshness is not an acceptable fix.

---

## 7. Treat HTTP 200 as successful refresh

Some connector paths (notably current yfinance behavior) can turn external failures into empty results.

A benchmark that reports only:

```text
status 200 rate
```

can become greener while no new market data is actually persisted.

Track:

```text
bars_fetched
bars_inserted
latest timestamp progress
provider warnings/errors
```

---

## 8. Add generic data-side single-flight immediately

Duplicate same-key work may be relevant, but:

- dashboard already coalesces its own same-key chart refreshes;
- cross-service duplicate frequency has not been measured;
- window semantics (`from_ts`, `to_ts`) complicate correct coalescing;
- a process-local implementation does not dedupe across two data workers.

Measure first. If duplicates are material after the primary fix, design it separately.

---

## 9. Add Redis/distributed queue/lock

This immediately expands operational and correctness surface:

```text
ownership
TTL
failure recovery
cross-worker coordination
queue semantics
Redis availability
```

Current self-hosted architecture does not justify this complexity for the first #107 fix without evidence that process-local/boundary changes are insufficient.

---

## 10. Add provider-specific limits everywhere

Different providers have different behavior, but current code already contains provider-specific protections in some places (e.g. yfinance serialization).

A matrix of hard-coded provider limits before measurement risks:

- double-throttling some providers;
- arbitrary numbers;
- config sprawl;
- worse latency with no service-level benefit.

Start generic only if generic admission is proven necessary; isolate providers later only if starvation is measured.

---

## 11. Add Prometheus/OpenTelemetry just to solve #107

Better observability is useful, but introducing a new telemetry stack is a separate architectural/operational change.

For the first fix, existing structured logs, trace IDs, deterministic probes, HTTP error subtypes, and benchmark output are enough to establish causality.

If the project later wants ongoing capacity dashboards, propose them separately.

---

## 12. Refactor all DataClients to share HTTP pools immediately

Factor creates many short-lived `httpx.AsyncClient` instances, so connection churn is a valid hypothesis.

But a shared-client refactor raises:

- lifecycle/shutdown questions;
- per-user Authorization isolation;
- multi-tenant safety concerns;
- cross-service scope.

Measure whether connection reuse materially changes latency/errors before touching it.

---

## Decision principle

> Prefer removing a measured pathological coupling before adding capacity, retries, queues, or architecture.

A first fix should make the system healthier for a clear reason, not merely move the saturation threshold farther away.
