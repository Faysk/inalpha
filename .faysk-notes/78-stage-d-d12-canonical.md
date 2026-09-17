# Stage D — canonical D12 one-worker capacity result

Status: contributor-only runtime evidence for issue #107. No production source changes were made.

## Clean start

The one-worker data benchmark was restarted clean before this run.

Observed pre-load state:

```text
pid=61860
provider mode=async
fake venues=binance
started=0
completed=0
pool min=2
pool max=10
pool size=2
pool available=2
pool waiting=0
```

The startup constituent scheduler remained forced disabled and non-fake OHLCV venues remained fail-closed.

## Workload

```text
12 concurrent /backfill/bars
fake Binance provider delay = 5s
health probes = 10
health timeout = 1.0s
one Uvicorn worker
normal pool max_size = 10
```

## Under-load state

```text
provider active=10
provider started=10
provider completed=0
pool size=10
pool available=0
pool requests waiting=2
pool requests num=13
pool requests queued=10
pool requests wait ms=617
```

The two requests above pool capacity had not yet reached provider I/O at the captured under-load snapshot.

## Post-load state

```text
provider started=12
provider completed=12
provider failed=0
provider cancelled=0
pool size=10
pool available=10
pool requests waiting=0
pool requests queued=14
pool requests wait ms=21112
pool usage ms=60742
```

## Client-visible results

```text
/openapi.json
  10/10 -> 200
  p95 ~0.006s

/health
  7/10 -> 200
  3/10 -> ReadTimeout
  p95 ~1.015s

/backfill/bars
  12/12 -> 200
  p50 ~5.169s
  p95 ~10.185s
  max ~10.185s
```

All 12 backfills made data progress.

## Interpretation

D12 confirms the one-worker capacity boundary around the normal pool max of 10:

```text
10 backfills occupy all 10 DB leases during the 5s provider wait
+ 2 additional backfills queue for DB capacity
→ only 10 provider calls are active in the first wave
→ the remaining 2 backfills start provider work only after a lease is released
→ their latency doubles to ~10s
```

At the same time:

```text
/openapi remains fast and error-free
while
DB-backed /health experiences ReadTimeout
```

This again separates DB-pool starvation from generic ASGI/event-loop starvation.

The pool usage total (~60.7s) is consistent with DB capacity being retained across provider waits, while pool wait time (~21.1s) shows the additional queueing cost once concurrency exceeds max_size=10.

## Stage-D boundary summary

```text
D08: no client-visible failures, pressure visible internally
D10: /health degradation begins at the normal pool ceiling
D12: 2 requests queue before provider I/O; backfill p95 grows to ~10s; /health remains degraded
```

This is strong evidence that H1 is materially relevant at the current one-worker pool boundary. It still does not by itself prove the complete representative agent+runner issue path or eliminate other amplifiers such as H8/H11.

## Next step

Stage E: capture PostgreSQL `pg_stat_activity` during the deterministic provider wait, together with application pool state. Specifically verify whether data-service sessions remain `idle in transaction` after `latest_bar_ts()` while provider work is waiting.

Candidate A remains unapplied until the remaining baseline decision gate is satisfied.
