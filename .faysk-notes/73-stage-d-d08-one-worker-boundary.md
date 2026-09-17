# Stage D — D08 one-worker real-TCP baseline

Status: contributor-only runtime evidence for issue #107.

## Environment / target safety

- branch: `fix/data-service-saturation`
- reviewed baseline: `ed01be9056776c107ab76a404c328a4fed19f529`
- benchmark DB: `inalpha_issue107`
- one data worker, PID 57784
- hardened contributor wrapper on `127.0.0.1:18001`
- provider mode: async
- fake venues: binance
- blocked venues: baostock,yfinance
- constituent snapshot scheduler forced disabled
- fake bars/fetch: 1
- provider delay: 5s
- production code unchanged

The Windows Uvicorn process was started with an explicit SelectorEventLoop factory so Psycopg async could initialize correctly. A pre-load call to `/__issue107/state` confirmed:

```text
mode=async
fake_venues=binance
snapshot_scheduler_forced_disabled=1
pool_min=2
pool_max=10
pool_size=2
pool_available=2
pool_requests_waiting=0
```

No real market-data provider was used by this workload.

## D08 workload

```text
backfills=8
health_probes=10
health_timeout=1.0s
```

All 8 backfills were unique-symbol requests and all completed with rows.

### Under-load state

Observed while all eight fake provider calls were waiting:

```text
provider active=8
provider started=8
provider completed=0
pool_size=8
pool_available=0
pool_requests_waiting=0
pool_requests_num=9
pool_requests_queued=6
pool_requests_wait_ms=496
```

This is consistent with the current backfill route retaining DB leases across provider I/O: the eight concurrent provider waits consumed all currently-created pool connections. The pool had not yet reached its configured max_size=10 and there were no clients currently waiting at the sampled instant.

### Client-visible results

```text
/openapi.json
  10/10 -> 200
  p50=0.003s
  p95=0.004s
  max=0.004s

/health
  10/10 -> 200
  p50=0.004s
  p95=0.032s
  max=0.032s

/backfill/bars
  8/8 -> 200
  p50=5.138s
  p95=5.246s
  max=5.246s
  successful_with_rows=8/8
```

Isolation signal:

```text
health_failures=0
openapi_failures=0
```

### Post-load state

```text
provider active=0
started=8
completed=8
cancelled=0
failed=0
pool_size=9
pool_available=9
pool_requests_waiting=0
pool_requests_num=19
pool_requests_queued=7
pool_requests_wait_ms=528
pool_usage_ms=40619
```

## Interpretation

D08 is below the client-visible failure boundary on this one-worker baseline:

- H1 pressure is visible internally: all eight provider waits consume the eight connections that existed at the under-load sample.
- The pool can still grow toward max_size=10, so DB-backed `/health` remains responsive at this load point.
- `/openapi.json` staying fast confirms no generic event-loop/HTTP-server degradation.
- All backfills make progress and no provider failures/cancellations occur.

Therefore D08 does **not** reproduce the issue-level failure, but it places the service close to the DB-pool boundary and supports testing the next adjacent point around the configured max size.

## Measurement caveat

The process pool grew from the initial min_size=2 to size 9 during D08. If D10/D12 are run in the same process, they begin with a warmer/larger pool than D08. Preserve that state in evidence or restart the contributor server before each capacity point if strict cold-pool comparability is desired. Do not silently compare a cold D08 against a warm D10 as if startup state were identical.

## Decision

- H1 mechanism: confirmed from Stage B and reinforced by D08 internal pool consumption.
- D08 client-visible degradation: no.
- production fix selected: no.
- next capacity point: D10, with pool-start state explicitly recorded before load.
