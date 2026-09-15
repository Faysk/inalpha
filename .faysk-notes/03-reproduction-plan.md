# Issue #107 — Reproduction Plan

**Goal:** reproduce the current sustained-load failure class before modifying production code.

---

## 1. Preconditions

- [ ] Fork/main synced with upstream.
- [ ] Contribution branch based on current upstream `main`.
- [ ] Supported local stack starts cleanly.
- [ ] `/health` for relevant services is green.
- [ ] Existing `services/data` tests pass before our changes.
- [ ] Existing `services/factor` tests pass before our changes.
- [ ] No production secrets/private datasets used.

Record the exact commit:

```bash
git rev-parse HEAD
```

---

## 2. Test philosophy

First reproduction should be deterministic and safe.

Prefer:

- fake/delayed connectors,
- controlled local DB,
- known test symbols,
- bounded concurrency ramps.

Do not use public market providers as stress-test targets.

External integration checks can be performed separately at low volume after the local behavior is understood.

---

## 3. Scenarios

### Scenario A — data-service backfill only

Purpose: determine how `/backfill/bars` behaves as expensive requests overlap.

Concurrency ramp:

```text
1
2
4
8
16
```

Collect:

- total duration,
- per-request latency,
- p50/p95/p99,
- success/error counts,
- peak concurrent provider calls,
- DB pool symptoms,
- process CPU/memory.

### Scenario B — factor panel only

Run representative panel requests with approximately:

```text
10 symbols
50 symbols
300 symbols where supported
```

Collect:

- factor request latency,
- number of data-service requests,
- failed symbol fetches,
- data-service p95,
- CPU/memory.

### Scenario C — current/live factor requests

Run current-time factor scoring that uses freshness semantics.

Verify:

- backfill frequency,
- retry behavior,
- whether refresh failures are visible,
- whether stale fallback can occur silently.

### Scenario D — live-runner-like polling

Use real runner tasks if setup is practical. Otherwise emulate the same fresh-data request cadence.

Test several concurrent runners/symbols and note whether wakeups cluster.

### Scenario E — mixed workload

Run:

```text
factor/panel activity
+ backfills
+ live-runner-like polling
```

This is the key scenario for #107.

---

## 4. Metrics to capture

For every scenario record:

```text
commit SHA
scenario name
start/end time
duration
concurrency
request count
success count
failure count
DATA_SERVICE_UNREACHABLE count
HTTP 429 count
HTTP 5xx count
timeout count
p50 latency
p95 latency
p99 latency
max latency
peak in-flight backfills
peak admission wait (after a gate exists)
CPU peak
memory peak
DB pool wait/errors
provider/error classification
```

If possible separate:

```text
queue/admission wait
provider fetch duration
DB write duration
GET /bars duration
```

---

## 5. Hypotheses to test

### H1 — unbounded expensive backfills are the primary bottleneck

Evidence for:

- in-flight backfills rise with failures/latency,
- bounded backfill concurrency stabilizes the system.

### H2 — caller-side connection churn is significant

Evidence for:

- many short-lived HTTP clients/connections,
- reuse materially lowers p95/errors without changing provider work.

### H3 — duplicate same-key work is significant

Evidence for:

- identical symbol/timeframe refreshes overlap,
- provider calls exceed unique refresh keys.

### H4 — one provider monopolizes capacity

Evidence for:

- slow provider occupies most expensive slots and degrades unrelated venues.

### H5 — live-runner synchronization materially contributes

Evidence for:

- failures/latency appear mainly when runner polling overlaps factor workloads,
- staggering/removing runner load changes results materially.

### H6 — DB pool is the actual bottleneck

Evidence for:

- significant pool wait/timeouts,
- upstream calls are not the dominant duration.

---

## 6. Stop conditions

Stop/ramp down a test if:

- local system becomes unstable beyond useful measurement,
- unexpected external-provider traffic becomes high,
- test starts producing destructive/unbounded work,
- a correctness issue appears that could contaminate results.

---

## 7. Baseline acceptance

The reproduction phase is complete when we can answer:

1. Can the current code reproduce #107?
2. Under which workload/concurrency?
3. What resource is saturated first?
4. What error mode appears first?
5. Is the problem sustained overload or only transient startup/reload blips?
6. Which single smallest intervention is most likely to improve the mixed workload?

Results go into `04-baseline-results.md`.
