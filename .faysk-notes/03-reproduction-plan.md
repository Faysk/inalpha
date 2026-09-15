# Issue #107 — Reproduction Plan

**Goal:** reproduce the current sustained-load failure class before modifying production code, and identify the first saturated resource rather than assuming the old issue text still describes the current bottleneck exactly.

**Upstream baseline:** `ed01be9056776c107ab76a404c328a4fed19f529`

---

## 1. Preconditions

- [ ] Fork/main synced with upstream.
- [ ] Contribution branch based on current upstream `main`.
- [ ] Supported local stack starts cleanly.
- [ ] Relevant `/health` endpoints are green.
- [ ] Existing `services/data` tests pass before changes.
- [ ] Existing `services/factor` tests pass before changes.
- [ ] No production secrets/private datasets used.
- [ ] Exact worker topology recorded.

Record:

```bash
git rev-parse HEAD
```

Also record whether the run is:

```text
single-process diagnostic
or
production-like data WORKERS=2
```

Do not use `--reload` as the representative sustained-load topology.

---

## 2. Test philosophy

First reproduction should be deterministic and safe.

Prefer:

- fake/delayed connectors,
- controlled local Timescale/Postgres,
- known test symbols,
- bounded concurrency ramps,
- existing Python/httpx tooling instead of adding a benchmark dependency to the project.

Do not use public market providers as stress-test targets.

Real-provider integration checks, if needed, must be low-volume and separate from the capacity benchmark.

The benchmark harness is contributor tooling by default. Only commit it upstream if it is clearly reusable and wanted by the maintainer.

---

## 3. Benchmark discipline

For deterministic scenarios:

- perform a warm-up when useful,
- use a fixed request count or fixed duration,
- collect enough samples for p95 to be meaningful,
- repeat representative runs 3 times where practical,
- record variability/range,
- keep hardware, worker count, config and commit fixed before/after,
- change one major variable at a time.

Never compare a 1-worker baseline against a 2-worker fixed result and call that the code improvement.

---

## 4. Scenario A — slow backfill / DB-pool diagnostic

### Purpose

Test the newly identified structural hypothesis:

```text
/backfill route checks out DBConn
→ waits on slow provider
→ pool slots remain occupied
→ unrelated DB-backed data requests wait/timeout
```

### Setup

Use a fake connector whose `fetch_bars()` sleeps for a controlled duration before returning deterministic bars.

Suggested delays:

```text
250 ms
1 s
3 s
```

### Concurrency ramp

```text
1
2
4
8
12
16
```

For single-worker diagnostics, the pool default `max_size=10` makes the 8→12 transition particularly informative.

For production-like testing, repeat with `data WORKERS=2`; remember each worker owns its own pool and process-local connector/gate state.

### Parallel probe

While slow backfills are in flight, continuously probe a lightweight DB-backed endpoint such as `/health` and/or a known `/bars` query.

Collect:

- backfill latency distribution,
- probe latency distribution,
- DB checkout/wait symptoms,
- connection pool timeout/errors,
- `pg_stat_activity` if accessible,
- number of provider calls in flight,
- `DATA_SERVICE_UNREACHABLE` seen by a caller client.

### Result interpretation

Evidence for DB-pool starvation includes:

- latency/error cliff near pool occupancy,
- DB-backed probes slow while requests wait on fake provider work,
- pool wait/timeout evidence,
- provider concurrency itself remains controlled.

Do not declare it from code inspection alone.

---

## 5. Scenario B — live factor macro fan-out

### Purpose

Represent the still-current factor path that can fan out many data calls.

Use a current/live daily or weekly factor request with macro factors enabled so `_compute_macro()` requests its required FRED series concurrently.

Current code can gather roughly 18 FRED series for a 1d snapshot.

Collect:

- factor request latency,
- number of data-service calls,
- number of `/backfill/bars` calls,
- number of short-lived factor HTTP clients/connections where practical,
- macro fetch successes/degradations,
- data-service p50/p95/p99,
- DB-pool pressure,
- connection errors/timeouts.

Run once with macro cache cold and again with cache warm; label them separately.

---

## 6. Scenario C — factor panel control

### Purpose

Confirm the current partial mitigation is actually working and quantify its load.

Representative panel sizes:

```text
10 symbols
50 symbols
300 symbols where supported
```

Verify:

- symbol fetch concurrency does not exceed 16,
- panel does not trigger per-symbol fresh backfills,
- data request count matches expected DB-read behavior.

Collect:

- factor latency,
- data request count,
- failed symbol fetches,
- data-service p95,
- CPU/memory.

If panel is no longer a meaningful saturation contributor, record that explicitly instead of forcing it into the fix.

---

## 7. Scenario D — live-runner-like polling

### Purpose

Measure the background load named in #107.

Prefer actual live-runner tasks if setup is practical. Otherwise emulate the same fresh-bar cadence.

Representative concurrency:

```text
1 run
4 runs
10 runs/account where practical
```

Record:

- polling cadence,
- whether wakeups cluster,
- backfill/read requests per cycle,
- retry/error behavior,
- effect on data-service latency while factor traffic is present.

Do not alter live-runner code during the reproduction phase.

---

## 8. Scenario E — mixed workload

This is the acceptance scenario for #107.

Construct it from the workloads actually shown by baseline evidence to matter, likely:

```text
live factor / macro fan-out
+ concurrent expensive refresh/backfill
+ live-runner polling
```

Panel may be included as a read-load control but should not be assumed to generate backfill storms in current `main`.

Record the exact workload so it can be repeated byte-for-byte/config-for-config after the fix.

---

## 9. Scenario F — same-key duplication check

### Purpose

Decide whether generic data-side single-flight is justified.

Generate overlapping requests for the same:

```text
venue
symbol
timeframe
window
```

Test separately through:

- dashboard path,
- direct data/factor/paper-style clients where practical.

Expected current behavior:

- dashboard same-key requests should coalesce process-locally;
- cross-service direct requests may still duplicate work.

Measure provider-call count vs unique refresh keys.

Do not implement data-side single-flight if duplication is negligible.

---

## 10. Metrics to capture

For every scenario:

```text
commit SHA
topology / data worker count
scenario name
start/end time
duration
concurrency/request count
successful HTTP responses
refreshes with actual timestamp/row progress
zero-row/no-progress backfills
failed requests
DATA_SERVICE_UNREACHABLE count
intentional backpressure count (after a gate exists)
HTTP 429 count
HTTP 5xx count
timeout count
p50
p95
p99
max latency
peak expensive in-flight operations
DB pool checked-out / wait / timeout symptoms
provider queue/wait behavior
CPU peak
memory peak
client connection/socket observations
```

Where possible separate:

```text
admission_wait_ms
DB checkout wait
latest_bar_ts query
provider wait/fetch
db_write
GET /bars
total request
```

---

## 11. Known confounders

### yfinance can return empty on provider failure

Current yfinance behavior can convert some provider/network failures into empty bars, allowing `/backfill/bars` to return HTTP 200 with `bars_fetched=0`.

Therefore:

```text
HTTP 200 != successful refresh
```

Record provider warnings and actual latest-bar progress.

This belongs to upstream issue #74 and should not be silently folded into #107 scope.

### Process-local behavior with two workers

A process-local semaphore/lock/cache is duplicated across the two production data workers.

Do not describe a per-process measurement as a service-global guarantee.

### Caches

Separate cold-cache and warm-cache runs. Factor macro caching can radically change request fan-out.

---

## 12. Hypotheses to test

### H1 — DB connections held across provider I/O are a major saturation multiplier

Evidence for:

- pool wait grows while provider calls are slow/serialized,
- unrelated DB-backed endpoints degrade,
- shortening DB connection lifetime materially improves the same workload.

### H2 — excessive expensive backfill concurrency is independently a bottleneck

Evidence for:

- failures/latency track in-flight backfills even when DB connection lifetime is controlled,
- bounded admission improves stability.

### H3 — factor HTTP client connection churn is material

Evidence for:

- large number of short-lived connections,
- reuse materially lowers p95/errors without changing provider work.

### H4 — duplicate same-key work is material outside the dashboard coalescing path

Evidence for:

- provider calls materially exceed unique refresh keys,
- coalescing changes the benchmark.

### H5 — one provider monopolizes capacity

Evidence for:

- slow provider consumes most slots and unrelated venues degrade.

### H6 — live-runner synchronization materially contributes

Evidence for:

- failures/latency appear mainly when runner polling overlaps factor traffic,
- removing/staggering runner load materially changes results.

### H7 — event-loop/thread-pool saturation is primary

Evidence for:

- service latency degrades even when DB pool/provider concurrency is not saturated,
- CPU/thread-pool/event-loop symptoms correlate first.

---

## 13. Stop conditions

Stop/ramp down if:

- the local stack becomes unstable beyond useful measurement,
- unexpected external-provider traffic occurs,
- the harness starts unbounded/destructive work,
- DB state/correctness becomes contaminated,
- results are dominated by an unrelated provider outage.

---

## 14. Baseline acceptance

The reproduction phase is complete when we can answer:

1. Can current `main` reproduce the #107 failure class?
2. Under what exact topology/workload/concurrency?
3. What resource saturates first?
4. Does `/backfill/bars` holding `DBConn` across provider I/O materially contribute?
5. Does live macro fan-out still reproduce the original pressure pattern?
6. What error/result mode appears first?
7. Is same-key duplication meaningful outside dashboard coalescing?
8. Is the problem sustained overload rather than reload/startup blips?
9. What is the smallest intervention likely to eliminate `DATA_SERVICE_UNREACHABLE` in the representative mixed workload?

Results go into `04-baseline-results.md`.
