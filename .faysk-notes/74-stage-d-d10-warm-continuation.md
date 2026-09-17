# Stage D D10 — warm-process continuation shows normal-pool health failures

Status: contributor-only runtime evidence for issue #107. This run is useful evidence, but it is **not** the canonical clean-start D10 comparison because the data-service process was not restarted after D08.

## Baseline / harness state

- branch: `fix/data-service-saturation`
- reviewed baseline: `ed01be9056776c107ab76a404c328a4fed19f529`
- production code unchanged
- hardened contributor wrapper on `127.0.0.1:18001`
- one Uvicorn worker
- fake Binance provider, async mode, 5 s delay, 1 fake bar per fetch
- benchmark DB: `inalpha_issue107`
- real OHLCV providers blocked by the wrapper

The same process that had already completed D08 was reused. Before D10 the wrapper state showed:

```text
pid=57784
provider started/completed = 8/8
pool_min/max              = 2/10
pool_size                 = 9
pool_available            = 9
pool_requests_wait_ms     = 528
```

Therefore this run starts from a warm, already-expanded pool and must not be presented as the same cold-start condition as D08.

## D10 workload

Ten concurrent backfills were started against the fake provider. Under load:

```text
provider active          = 10
pool_size                = 10
pool_available           = 0
pool_requests_waiting    = 0 at the sampled instant
pool_requests_num        = 30
pool_requests_queued     = 8
pool_requests_wait_ms    = 544
```

The under-load state sample occurs before the sequential health probe loop, so `pool_requests_waiting=0` at that sample does not mean DB-backed probes never waited afterward.

## Client-observed result

```text
openapi:  10/10 HTTP 200
          p95 ~7 ms

health:   7/10 HTTP 200
          3/10 ReadTimeout at 1 s
          p95 ~1.017 s including timeout observations

backfill: 10/10 HTTP 200
          p95 ~5.113 s
          all 10 returned rows
```

Isolation signal:

```text
health_failures=3
openapi_failures=0
```

Post-run pool counters:

```text
pool_size              = 10
pool_available         = 10
pool_requests_queued   = 12
pool_requests_wait_ms  = 10777
pool_usage_ms          = 91501
```

Relative to the warm pre-state, cumulative pool wait time increased by about 10.25 seconds during this run (`10777 - 528 = 10249 ms`).

## Interpretation

This is strong runtime evidence that the H1 mechanism is **material at the normal per-process pool maximum of 10** even when the pool begins warm and already expanded:

```text
10 provider-blocked backfills
→ all 10 DB leases retained while provider I/O is pending
→ DB-backed /health begins timing out
while
non-DB /openapi.json remains fast and error-free
```

Because the event loop and HTTP server remain responsive, the failure shape is specifically consistent with DB-pool capacity exhaustion rather than generic process starvation.

The warm start actually makes this a conservative observation with respect to pool-growth overhead: the process already had 9 connections before D10, yet health still failed when 10 leases were retained.

## Evidence caveat / next action

Do **not** use this run as the canonical D10 point for before/after comparison because D08 and D10 did not begin from identical process state.

Required next action:

1. restart the contributor data-service process,
2. verify fresh wrapper state (`started=0`, `pool_size≈2`, `pool_available≈2`),
3. rerun D10 as a clean-start confirmation,
4. then run D12 from another fresh process,
5. only after that continue to PostgreSQL-side evidence and candidate selection.

## Decision impact

- H1 mechanism: confirmed earlier in Stage B.
- H1 materiality at normal `max_size=10`: **strongly supported by this warm-process D10 continuation**.
- canonical D10 comparison: still pending clean restart.
- Candidate A: still not applied.
