# Stage D — canonical D10 one-worker capacity result

Status: contributor-only runtime evidence for issue #107. No production source changes were made.

## Clean starting state

A fresh one-worker contributor server was started on Windows with an explicit Selector event loop. Before load:

```text
pid=60968
mode=async
fake_venues=binance
snapshot_scheduler_forced_disabled=1
started=0
completed=0
pool_min=2
pool_max=10
pool_size=2
pool_available=2
```

The target was the hardened contributor wrapper on `127.0.0.1:18001`; real OHLCV providers were excluded from the workload.

## Workload

```text
backfills=10
health_probes=10
health_timeout=1.0s
fake provider delay=5s
fake bars/fetch=1
workers=1
```

## Under-load observation

```text
provider active=10
provider started=10
provider completed=0
pool_size=10
pool_available=0
pool_requests_waiting=0 at sampled instant
pool_requests_num=11
pool_requests_queued=8
pool_requests_wait_ms=635
```

The sampled `requests_waiting=0` does not mean the run had no pool contention: aggregate counters and client-side health timeouts show waiting occurred during the workload outside that single state sample.

## Post-load counters

```text
provider active=0
provider started=10
provider completed=10
pool_size=10
pool_available=10
pool_requests_num=21
pool_requests_queued=12
pool_requests_wait_ms=10805
pool_usage_ms=50730
```

The ~50.7 seconds cumulative pool usage for ten ~5-second backfills is consistent with a DB lease being retained for nearly the full provider-wait duration.

## Client-observed result

```text
/openapi.json
  10/10 status 200
  p95 ~= 0.007s

/health
  7/10 status 200
  3/10 ReadTimeout at 1.0s
  p95 ~= 1.017s

/backfill/bars
  10/10 status 200
  p95 ~= 5.232s
  successful_with_rows=10/10
```

Isolation signal:

```text
health_failures=3
openapi_failures=0
```

## Interpretation

This is the first clean-start, normal-pool-size, real-TCP one-worker result that makes H1 materially visible at the current per-process `max_size=10` boundary.

At ten concurrent backfills, the application remains generally responsive and every backfill succeeds, but DB-backed health traffic loses availability while the non-DB OpenAPI control stays fast. This separates DB-pool starvation from generic Uvicorn/event-loop starvation.

The aggregate counters also support the static route-ordering hypothesis: ten provider waits of roughly five seconds consumed roughly fifty seconds of pool usage.

This is strong evidence that H1 is materially relevant to issue #107 under a controlled representative saturation mechanism. It does not by itself establish production dominance across the full agent+runner mixed workload, and it does not justify skipping the remaining D12/PostgreSQL/mixed-workload evidence.

## Working-tree note

`git status --short` remained untracked-only. In addition to the known contributor harness files, `ps1/` is now present because the contributor placed the local benchmark launcher `Start-Issue107-DataBenchmark.ps1` there. This is contributor convenience tooling and must not be included in the production PR.

## Decision impact

- H1 mechanism: confirmed.
- H1 materiality at the normal one-worker pool boundary: strongly supported.
- Candidate A: primary candidate, still not applied.
- Next: D12 from a fresh server, then PostgreSQL-side observation while provider work is blocked.
