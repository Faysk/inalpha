# Issue #107 — Before / After Results

**Purpose:** prove whether the implemented change actually improves the representative #107 workload without weakening correctness.

---

## Compared revisions

```text
Baseline commit:
Fixed commit:
Benchmark harness commit/version:
Environment:
Date:
```

The same workload and environment should be used for both sides where practical.

---

## Primary comparison

| Metric | Before | After | Difference |
|---|---:|---:|---:|
| total requests | TBD | TBD | TBD |
| success rate | TBD | TBD | TBD |
| failed requests | TBD | TBD | TBD |
| `DATA_SERVICE_UNREACHABLE` | TBD | TBD | TBD |
| upstream failures | TBD | TBD | TBD |
| p50 latency | TBD | TBD | TBD |
| p95 latency | TBD | TBD | TBD |
| p99 latency | TBD | TBD | TBD |
| max latency | TBD | TBD | TBD |
| peak expensive in-flight ops | TBD | TBD | TBD |
| peak admission wait | N/A/TBD | TBD | TBD |
| CPU peak | TBD | TBD | TBD |
| memory peak | TBD | TBD | TBD |
| DB pool symptoms | TBD | TBD | TBD |

---

## Concurrency sweep

| Concurrency | Before p95 | After p95 | Before errors | After errors |
|---:|---:|---:|---:|---:|
| 1 | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD |
| 4 | TBD | TBD | TBD | TBD |
| 8 | TBD | TBD | TBD | TBD |
| 16 | TBD | TBD | TBD | TBD |

---

## Mixed workload

Describe exact workload:

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

## Correctness checks

Performance improvement is invalid if any of these regress.

- [ ] current/live requests preserve freshness semantics
- [ ] historical/as-of behavior unchanged
- [ ] upstream failure remains explicit
- [ ] overload does not silently convert to stale success
- [ ] owner/auth headers remain isolated
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
TBD
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
