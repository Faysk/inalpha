# Issue #107 — Before / After Results

**Purpose:** prove whether the implemented change improves the representative #107 workload without weakening correctness or merely replacing one failure mode with fake success.

---

## Compared revisions

```text
Baseline commit:
Fixed commit:
Benchmark harness version:
Environment:
Data worker count:
DB pool config:
Cache state:
Date:
```

The same workload, worker topology and environment should be used for both sides where practical.

---

## Primary comparison

| Metric | Before | After | Difference |
|---|---:|---:|---:|
| total requests | TBD | TBD | TBD |
| HTTP success rate | TBD | TBD | TBD |
| refreshes with real row/timestamp progress | TBD | TBD | TBD |
| zero-row/no-progress backfills | TBD | TBD | TBD |
| failed requests | TBD | TBD | TBD |
| `DATA_SERVICE_UNREACHABLE` | TBD | **target 0** | TBD |
| intentional busy/backpressure | N/A | TBD | TBD |
| upstream failures | TBD | TBD | TBD |
| p50 latency | TBD | TBD | TBD |
| p95 latency | TBD | TBD | TBD |
| p99 latency | TBD | TBD | TBD |
| max latency | TBD | TBD | TBD |
| DB pool wait/timeout symptoms | TBD | TBD | TBD |
| peak expensive in-flight ops | TBD | TBD | TBD |
| peak admission wait | N/A/TBD | TBD | TBD |
| CPU peak | TBD | TBD | TBD |
| memory peak | TBD | TBD | TBD |

---

## Repeatability

| Revision | Run | p95 | `DATA_SERVICE_UNREACHABLE` | No-progress refreshes | Notes |
|---|---:|---:|---:|---:|---|
| Before | 1 | TBD | TBD | TBD | |
| Before | 2 | TBD | TBD | TBD | |
| Before | 3 | TBD | TBD | TBD | |
| After | 1 | TBD | TBD | TBD | |
| After | 2 | TBD | TBD | TBD | |
| After | 3 | TBD | TBD | TBD | |

Do not report only the best run.

---

## Concurrency sweep

| Concurrency | Before p95 | After p95 | Before errors | After errors | Before DB pressure | After DB pressure |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD | TBD |
| 4 | TBD | TBD | TBD | TBD | TBD | TBD |
| 8 | TBD | TBD | TBD | TBD | TBD | TBD |
| 12 | TBD | TBD | TBD | TBD | TBD | TBD |
| 16 | TBD | TBD | TBD | TBD | TBD | TBD |

---

## Mixed workload

Describe the exact workload and topology:

```text
TBD
```

Before:

```text
TBD
```

After:

```text
TBD
```

---

## Resource-lifetime evidence

If the fix changes DB checkout/admission behavior, record evidence explicitly:

```text
Before DB connection lifetime:
After DB connection lifetime:

Before pool occupancy/waits:
After pool occupancy/waits:

Before provider queue behavior:
After provider queue behavior:
```

---

## Correctness checks

Performance improvement is invalid if any of these regress.

- [ ] current/live factor freshness semantics preserved
- [ ] historical/as-of behavior unchanged
- [ ] upstream failure remains distinguishable where existing semantics require it
- [ ] overload does not silently convert to stale current success
- [ ] dashboard/research intentional best-effort degradation is not accidentally broken
- [ ] owner/auth headers remain isolated
- [ ] no unexpected serialization across independent keys/providers
- [ ] existing data tests pass
- [ ] existing factor tests pass if touched
- [ ] consistency check passes
- [ ] Ruff passes
- [ ] relevant mypy output reviewed

---

## Regression test results

```text
services/data:

services/factor:

other affected services:

CI:
```

---

## Outcome

### Did the change meet #107's target?

```text
Target workload:
DATA_SERVICE_UNREACHABLE = 0?:
p95 controlled/bounded?:
```

### What improved?

```text
TBD
```

### What remains unresolved?

```text
TBD
```

### Follow-up work deliberately left out of this PR

```text
TBD
```

---

## PR-ready evidence summary

This section should become a concise paragraph/table for the upstream PR.

```text
TBD
```
