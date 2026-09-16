# Issue #107 — Before / After Results

**Purpose:** prove whether the implemented change improves the representative #107 workload without weakening correctness, hiding failed refreshes, or merely moving saturation from DB capacity to providers/executors.

---

## Compared revisions

```text
Baseline commit:
Fixed commit:
Benchmark harness version:
Environment:
Data worker count:
Factor worker count:
DB pool config:
Provider fake mode (async/thread):
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
| `BARS_UPSTREAM_UNAVAILABLE` / provider failures | TBD | TBD | TBD |
| p50 latency | TBD | TBD | TBD |
| p95 latency | TBD | TBD | TBD |
| p99 latency | TBD | TBD | TBD |
| max latency | TBD | TBD | TBD |
| DB pool wait/timeout symptoms | TBD | TBD | TBD |
| DB `idle in transaction` during provider wait | TBD | TBD | TBD |
| peak provider waiters | TBD | TBD | TBD |
| peak underlying sync threads (thread mode) | TBD | TBD | TBD |
| provider work surviving client timeout | TBD | TBD | TBD |
| peak admission wait | N/A/TBD | TBD | TBD |
| CPU peak | TBD | TBD | TBD |
| memory peak | TBD | TBD | TBD |

A drop in `DATA_SERVICE_UNREACHABLE` is not sufficient if provider errors/no-progress refreshes increase materially.

---

## Controlled mechanism regression

If Candidate A is selected, run the dedicated small-pool regression before broad load tests.

Test configuration:

```text
DB pool max_size = 2
fake provider calls = 4
provider waits blocked
```

Expected **before**:

```text
only 2 requests can reach provider I/O because each owns DBConn
remaining requests wait for DB pool
```

Expected **after**:

```text
all 4 requests complete short DB lookup and reach provider I/O
/health still gets DB capacity while all 4 provider waits remain blocked
```

Record:

```text
Before provider entered count before release:
After provider entered count before release:
Before /health while blocked:
After /health while blocked:
Before /openapi while blocked:
After /openapi while blocked:
```

This proves the intended resource-lifetime property separately from end-to-end performance.

---

## Repeatability

| Revision | Run | p95 | `DATA_SERVICE_UNREACHABLE` | Provider failures | No-progress refreshes | Notes |
|---|---:|---:|---:|---:|---:|---|
| Before | 1 | TBD | TBD | TBD | TBD | |
| Before | 2 | TBD | TBD | TBD | TBD | |
| Before | 3 | TBD | TBD | TBD | TBD | |
| After | 1 | TBD | TBD | TBD | TBD | |
| After | 2 | TBD | TBD | TBD | TBD | |
| After | 3 | TBD | TBD | TBD | TBD | |

Do not report only the best run.

---

## Concurrency sweep

| Concurrency | Before p95 | After p95 | Before errors | After errors | Before DB pressure | After DB pressure | Before provider active | After provider active |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 4 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 8 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 12 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 16 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

For Candidate A, provider-active count may intentionally increase because DB pool is no longer the accidental provider queue. That is not automatically bad, but provider failures/queue health must be checked.

---

## Async-wait vs thread-backed fake provider

Use both contributor fake modes if Candidate A is selected:

```text
ISSUE107_PROVIDER_MODE=async
ISSUE107_PROVIDER_MODE=thread
```

Record:

| Mode | Revision | health p95 | openapi p95 | backfill p95 | provider peak | thread peak | client timeouts |
|---|---|---:|---:|---:|---:|---:|---:|
| async | Before | TBD | TBD | TBD | TBD | N/A | TBD |
| async | After | TBD | TBD | TBD | TBD | N/A | TBD |
| thread | Before | TBD | TBD | TBD | TBD | TBD | TBD |
| thread | After | TBD | TBD | TBD | TBD | TBD | TBD |

This separates the core DB lease fix from default-executor/thread behavior.

---

## DB-side resource evidence

Follow `25-pg-stat-activity-diagnostic.md` using the same blocked **first provider fetch** phase.

```text
Before:
  idle in transaction count:
  oldest transaction age:
  last query sample:

After:
  idle in transaction count:
  oldest transaction age:
  last query sample:
```

Expected Candidate A direction:

```text
provider waits no longer correspond one-for-one with open read transactions / retained DB leases
```

Do not use plain PostgreSQL `idle` state alone as proof of pool availability.

---

## Client-timeout / retry-overlap evidence

Follow `24-client-timeout-cancellation.md` before/after only if H9 matters to the observed failure chain.

```text
Provider mode:
Client timeout:
Provider delay:
Attempts:

Before timeout-state delta:
After timeout-state delta:

Before underlying thread persistence (thread mode):
After underlying thread persistence:
```

Candidate A is not expected to magically stop synchronous provider threads. Its goal is to keep their latency from monopolizing DB capacity.

---

## Macro workload comparison

Current full default live daily/weekly macro set is:

```text
26 factor specs
18 unique FRED series
```

Distinguish:

```text
legitimate unique fan-out = 18 keys
from
duplicate cold same-key work = H8
```

Record:

| Revision | Callers | Cache state | Unique macro keys | Actual macro fetches | Duplicate ratio | p95 | Errors |
|---|---:|---|---:|---:|---:|---:|---:|
| Before | 1 | cold | 18 expected | TBD | TBD | TBD | TBD |
| After | 1 | cold | 18 expected | TBD | TBD | TBD | TBD |
| Before | N | cold | 18 expected | TBD | TBD | TBD | TBD |
| After | N | cold | 18 expected | TBD | TBD | TBD | TBD |
| Before | 1 | warm | 18 cached | TBD | TBD | TBD | TBD |
| After | 1 | warm | 18 cached | TBD | TBD | TBD | TBD |

If Candidate A is data-only, H8 duplicate ratio should not be expected to improve by itself. What should improve is the data-service's ability to protect DB-backed traffic from the burst.

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

Before worker distribution:
After worker distribution:
```

---

## Correctness checks

Performance improvement is invalid if any of these regress.

- [ ] current/live factor freshness semantics preserved
- [ ] historical/as-of behavior unchanged
- [ ] upstream failure remains distinguishable where existing semantics require it
- [ ] overload does not silently convert to stale current success
- [ ] real data/timestamp progress is not replaced by HTTP-only “success”
- [ ] dashboard/research intentional best-effort degradation is not accidentally broken
- [ ] owner/auth headers remain isolated
- [ ] existing incremental backfill semantics remain correct
- [ ] provider failure still returns explicit existing error semantics
- [ ] no unexpected serialization across independent keys/providers
- [ ] provider concurrency does not produce a new failure cliff
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
provider/upstream failures did not materially regress?:
refresh progress preserved?:
```

### What improved?

```text
TBD
```

### What remains unresolved?

```text
TBD
```

### Did we move the bottleneck?

```text
DB → provider?:
DB → executor?:
DB → client sockets?:
No meaningful new bottleneck observed?:
Evidence:
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
