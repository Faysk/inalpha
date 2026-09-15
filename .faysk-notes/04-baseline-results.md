# Issue #107 — Baseline Results

**Status:** waiting for reproduction run.  
**Purpose:** record pre-change evidence against current upstream behavior.

---

## Environment

```text
Date:
Commit SHA:
OS:
Python:
Docker:
CPU:
RAM:
Data worker count:
Other service worker counts:
DB pool config observed:
Deployment topology:
Relevant env overrides:
Cache state (cold/warm):
```

Do not record secrets.

---

## Existing tests before reproduction

```text
services/data pytest:
services/factor pytest:
ruff:
mypy notes:
check-consistency:
```

---

## Scenario summary

| Scenario | Topology / concurrency | Requests | HTTP success | Refresh progress | Fail | p50 | p95 | p99 | `DATA_SERVICE_UNREACHABLE` |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Slow backfill / pool diagnostic | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Live macro cold cache | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Live macro warm cache | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 10 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 50 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 300 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Runner-like | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Mixed | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

`Refresh progress` means the refresh actually advanced/inserted expected data, not merely that HTTP returned 200.

---

## Repeatability

Record representative runs separately rather than reporting only the best one.

| Scenario | Run | p95 | Errors | Refresh no-progress | Notes |
|---|---:|---:|---:|---:|---|
| TBD | 1 | TBD | TBD | TBD | |
| TBD | 2 | TBD | TBD | TBD | |
| TBD | 3 | TBD | TBD | TBD | |

---

## Detailed observations

### Slow backfill / DB-pool diagnostic

```text
Fake provider delay:
Concurrency:
DB pool checked-out/wait symptoms:
pg_stat_activity observations:
Probe endpoint latency:
Provider in-flight/queue behavior:
First failure mode:
```

Question to answer:

```text
Does holding route-level DBConn across provider I/O materially contribute to saturation?
```

### Live factor macro

```text
Macro series requested:
Data calls:
Backfills:
Cold-cache behavior:
Warm-cache behavior:
Macro degradation/failures:
HTTP client/connection observations:
```

### Factor panel control

```text
Observed:
Data request fan-out:
Max observed symbol fetch concurrency:
Did any per-symbol backfill occur?:
Failure mode:
```

### Live runner / polling

```text
Run count:
Observed cadence:
Burst synchronization:
Backfill/read request count:
Interaction with factor traffic:
```

### Same-key duplication check

```text
Caller path:
Unique refresh keys:
Provider calls:
Dashboard coalescing observed?:
Cross-service duplication observed?:
```

### Mixed load

```text
Exact workload:
First resource to degrade:
First error/result class:
Latency curve:
DATA_SERVICE_UNREACHABLE count:
Zero-row/no-progress backfills:
```

---

## Resource measurements

| Metric | Idle | Representative load | Peak |
|---|---:|---:|---:|
| data CPU | TBD | TBD | TBD |
| data memory | TBD | TBD | TBD |
| factor CPU | TBD | TBD | TBD |
| DB connections checked out | TBD | TBD | TBD |
| DB pool waits/timeouts | TBD | TBD | TBD |
| provider calls in flight | TBD | TBD | TBD |
| provider queue depth/wait | TBD | TBD | TBD |
| client connections/sockets | TBD | TBD | TBD |

---

## Error / result classification

| Error/result | Count | Scenario | Retryable? | Notes |
|---|---:|---|---|---|
| `DATA_SERVICE_UNREACHABLE` | TBD | TBD | yes/transient? | TBD |
| `BARS_UPSTREAM_UNAVAILABLE` | TBD | TBD | provider-dependent | TBD |
| HTTP 200 + zero/no progress | TBD | TBD | not necessarily success | watch yfinance/#74 |
| timeout | TBD | TBD | TBD | TBD |
| HTTP 5xx | TBD | TBD | TBD | TBD |

---

## Hypothesis results

- [ ] H1: DB connection lifetime across provider I/O is a major saturation multiplier
- [ ] H2: expensive backfill concurrency is independently a bottleneck
- [ ] H3: factor HTTP connection churn is material
- [ ] H4: duplicate same-key work outside dashboard is material
- [ ] H5: one provider monopolizes capacity
- [ ] H6: live-runner synchronization materially contributes
- [ ] H7: event-loop/thread-pool saturation is primary

Evidence:

```text
TBD
```

---

## What was ruled out

```text
TBD
```

Record negative evidence. It prevents us from re-adding unnecessary fixes to the PR later.

---

## Baseline conclusion

```text
Strongest root-cause evidence:

Contributing factors:

What is NOT the bottleneck:

Smallest justified next intervention:

Why that intervention is at the correct service boundary:

Risks/correctness constraints:

Does the intended fix remain data-service-local?:
```

No production implementation should begin until this section has enough evidence to justify the first change.
