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
Deployment topology:
Relevant env overrides:
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

| Scenario | Concurrency / size | Requests | Success | Fail | p50 | p95 | p99 | `DATA_SERVICE_UNREACHABLE` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Backfill only | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 10 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 50 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Panel 300 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Live factor | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Runner-like | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Mixed | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

---

## Detailed observations

### Backfill-only

```text
Observed:
Bottleneck signs:
Provider behavior:
DB behavior:
Connection behavior:
```

### Factor panel

```text
Observed:
Data request fan-out:
Semaphore behavior:
Failure mode:
```

### Current/live factor

```text
Observed refresh behavior:
Refresh failure visibility:
Freshness behavior after failure:
```

### Live runner / polling

```text
Observed cadence:
Burst synchronization:
Interaction with data-service:
```

### Mixed load

```text
Observed:
First resource to degrade:
First error class:
Latency curve:
```

---

## Resource measurements

| Metric | Idle | Under representative load | Peak |
|---|---:|---:|---:|
| data CPU | TBD | TBD | TBD |
| data memory | TBD | TBD | TBD |
| factor CPU | TBD | TBD | TBD |
| DB connections | TBD | TBD | TBD |
| in-flight provider calls | TBD | TBD | TBD |
| client connections/sockets | TBD | TBD | TBD |

---

## Error classification

| Error/code | Count | Scenario | Retryable? | Notes |
|---|---:|---|---|---|
| `DATA_SERVICE_UNREACHABLE` | TBD | TBD | yes/transient? | TBD |
| `BARS_UPSTREAM_UNAVAILABLE` | TBD | TBD | provider-dependent | TBD |
| timeout | TBD | TBD | TBD | TBD |
| HTTP 5xx | TBD | TBD | TBD | TBD |

---

## Hypothesis results

- [ ] H1: expensive backfill concurrency is primary bottleneck
- [ ] H2: HTTP client connection churn is material
- [ ] H3: duplicate same-key work is material
- [ ] H4: one provider monopolizes capacity
- [ ] H5: live-runner synchronization materially contributes
- [ ] H6: DB pool is primary bottleneck

Evidence:

```text
TBD
```

---

## Baseline conclusion

```text
Root cause / strongest evidence:

What is NOT the bottleneck:

Smallest justified next intervention:

Risks/correctness constraints:
```

No implementation should begin until this section has enough evidence to justify the first change.
