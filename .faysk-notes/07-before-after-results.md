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
Provider fake delay:
Fake bars/fetch:
Cache state:
Date:
```

The same workload, worker topology and environment should be used for both sides where practical.

---

## Primary comparison

| Metric | Before | After | Difference |
|---|---:|---:|---:|
| factor requests | TBD | TBD | TBD |
| runner polls | TBD | TBD | TBD |
| total data `POST /backfill/bars` | TBD | TBD | TBD |
| total data `GET /bars` | TBD | TBD | TBD |
| HTTP success rate | TBD | TBD | TBD |
| refreshes with real row/timestamp progress | TBD | TBD | TBD |
| zero-row/no-progress backfills | TBD | TBD | TBD |
| failed requests | TBD | TBD | TBD |
| `DATA_SERVICE_UNREACHABLE` | TBD | **target 0** | TBD |
| runner `GET /bars` failures | TBD | **target 0** | TBD |
| health failures under representative load | TBD | TBD | TBD |
| OpenAPI control failures | TBD | TBD | TBD |
| intentional busy/backpressure | N/A | TBD | TBD |
| `BARS_UPSTREAM_UNAVAILABLE` / provider failures | TBD | TBD | TBD |
| factor p50 | TBD | TBD | TBD |
| factor p95 | TBD | TBD | TBD |
| factor p99 | TBD | TBD | TBD |
| runner p50 | TBD | TBD | TBD |
| runner p95 | TBD | TBD | TBD |
| runner p99 | TBD | TBD | TBD |
| health p95 | TBD | TBD | TBD |
| OpenAPI p95 | TBD | TBD | TBD |
| DB pool available minimum | TBD | TBD | TBD |
| DB requests waiting maximum | TBD | TBD | TBD |
| DB queued cumulative delta | TBD | TBD | TBD |
| DB wait ms cumulative delta | TBD | TBD | TBD |
| DB request errors delta | TBD | TBD | TBD |
| DB `idle in transaction` during provider wait | TBD | TBD | TBD |
| peak provider active | TBD | TBD | TBD |
| peak FRED provider active | TBD | TBD | TBD |
| peak Binance provider active | TBD | TBD | TBD |
| peak backfill HTTP in-flight | TBD | TBD | TBD |
| peak bars HTTP in-flight | TBD | TBD | TBD |
| peak underlying sync threads (thread mode) | TBD | TBD | TBD |
| provider work surviving client timeout | TBD | TBD | TBD |
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

| Revision | Scenario | Run | p95 | `DATA_SERVICE_UNREACHABLE` | Runner read failures | Health failures | Provider failures | Pool wait ms | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Before | M1 | 1 | TBD | TBD | TBD | TBD | TBD | TBD | |
| Before | M1 | 2 | TBD | TBD | TBD | TBD | TBD | TBD | |
| Before | M1 | 3 | TBD | TBD | TBD | TBD | TBD | TBD | |
| After | M1 | 1 | TBD | TBD | TBD | TBD | TBD | TBD | |
| After | M1 | 2 | TBD | TBD | TBD | TBD | TBD | TBD | |
| After | M1 | 3 | TBD | TBD | TBD | TBD | TBD | TBD | |

Do not report only the best run.

---

## Concurrency sweep

Use the low-level fake-provider harness first; do not make every mixed test a large sweep.

| Backfill concurrency | Before p95 | After p95 | Before errors | After errors | Before pool waiting | After pool waiting | Before provider active | After provider active |
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

| Mode | Revision | health p95 | openapi p95 | backfill p95 | pool wait | provider peak | thread peak | client timeouts |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| async | Before | TBD | TBD | TBD | TBD | TBD | N/A | TBD |
| async | After | TBD | TBD | TBD | TBD | TBD | N/A | TBD |
| thread | Before | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| thread | After | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

This separates the core DB lease fix from executor/thread behavior.

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

Also record direct Psycopg pool state from the contributor wrapper:

```text
Before pool available minimum:
After pool available minimum:
Before requests waiting maximum:
After requests waiting maximum:
Before queued delta:
After queued delta:
Before wait-ms delta:
After wait-ms delta:
```

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
from
whole live-score same-key duplication = H11
```

Record:

| Revision | Caller shape | Cache | Unique macro keys | Actual FRED provider calls | Binance price calls | p95 | Pool wait | Errors |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Before | 1 caller | cold | 18 expected | TBD | TBD | TBD | TBD | TBD |
| After | 1 caller | cold | 18 expected | TBD | TBD | TBD | TBD | TBD |
| Before | N same symbol | cold | 18 expected shared | TBD | TBD | TBD | TBD | TBD |
| After | N same symbol | cold | 18 expected shared | TBD | TBD | TBD | TBD | TBD |
| Before | N unique symbols | cold | 18 expected shared | TBD | TBD | TBD | TBD | TBD |
| After | N unique symbols | cold | 18 expected shared | TBD | TBD | TBD | TBD | TBD |
| Before | same keys | warm | cached | TBD | TBD | TBD | TBD | TBD |
| After | same keys | warm | cached | TBD | TBD | TBD | TBD | TBD |

If Candidate A is data-only, H8/H11 duplicate ratios should not be expected to improve by themselves. What should improve is the data-service's ability to protect DB-backed traffic from those bursts.

---

## Runner aligned-vs-stagger comparison

Follow `38-runner-poll-harness.md`.

| Revision | Runner count | Stagger | Runner p95 | Pool available min | Pool waiting max | Provider active max | Bars failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| Before | 8 | 0 ms | TBD | TBD | TBD | TBD | TBD |
| Before | 8 | 100 ms | TBD | TBD | TBD | TBD | TBD |
| After | 8 | 0 ms | TBD | TBD | TBD | TBD | TBD |
| After | 8 | 100 ms | TBD | TBD | TBD | TBD | TBD |

Interpretation rule:

```text
If Candidate A makes aligned and staggered runs both healthy,
do not add live-runner jitter to PR1 merely because staggered load is smoother.
```

If the aligned case remains materially worse after the DB-lifetime fix, H6 remains a possible follow-up.

---

## Mixed workload M1/M2/M3

Follow `39-mixed-workload-harness.md`.

Keep these constant across Before/After and across the comparison intended to isolate one hypothesis:

```text
data workers
factor workers
DB pool
fake provider mode
delay
bars-per-fetch
factor concurrency
runner count
factor cold/warm state
health/openapi probe settings
```

### M1 — cold same-symbol factor + aligned runner

```text
factor_symbol_mode = same
runner_stagger_ms = 0
```

| Metric | Before | After |
|---|---:|---:|
| factor failures | TBD | TBD |
| runner bars failures | TBD | TBD |
| `DATA_SERVICE_UNREACHABLE` | TBD | TBD |
| health failures | TBD | TBD |
| openapi failures | TBD | TBD |
| factor p95 | TBD | TBD |
| runner p95 | TBD | TBD |
| health p95 | TBD | TBD |
| pool available min | TBD | TBD |
| pool waiting max | TBD | TBD |
| pool wait ms delta | TBD | TBD |
| provider active max | TBD | TBD |
| FRED active max | TBD | TBD |
| backfill HTTP in-flight max | TBD | TBD |
| bars HTTP in-flight max | TBD | TBD |

M1 is the main issue-level before/after acceptance workload.

### M2 — cold unique factor price keys + aligned runner

```text
factor_symbol_mode = unique
runner_stagger_ms = 0
```

Use the same table as M1.

Purpose:

```text
reduce whole-score same-key H11 overlap
while retaining shared macro/date H8 overlap
```

### M3 — cold same-symbol factor + staggered runner

```text
factor_symbol_mode = same
runner_stagger_ms = 100
```

Use the same table as M1.

Purpose:

```text
isolate runner alignment H6
while keeping the factor burst shape unchanged
```

---

## Mixed-workload decision matrix

### Candidate A sufficient

If after Candidate A:

```text
M1/M2/M3 have zero transport/unreachable failures
runner reads remain healthy
health remains healthy
OpenAPI remains healthy
p95 is controlled for the fixed workload
provider errors do not materially regress
refresh progress remains real
```

then stop PR1 at Candidate A.

### DB fixed, provider becomes first bottleneck

If after Candidate A:

```text
pool waiting collapses / pool stays available
but
provider in-flight/latency/failure becomes the first limit
```

then Candidate C/B may be justified. Do not describe Candidate A as a failure; it may have exposed the next real bottleneck that was previously hidden by DB starvation.

### Same-key factor duplication remains material but service is healthy

If H8/H11 duplication remains but M1 meets #107 acceptance after Candidate A, defer single-flight to a separate optimization issue/PR.

### Runner staggering still materially changes failures after Candidate A

Only then consider live-runner jitter/throttling within #107 scope, with maintainer alignment because it touches paper scheduling behavior.

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

For Candidate A, the expected code-level change is:

```text
Before:
DB lease spans latest lookup + external provider wait + persistence loop

After:
short latest lookup lease
→ no DB lease during provider wait
→ short persistence lease per completed batch
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
- [ ] invalid venue/timeframe/span validation remains deterministic
- [ ] no unexpected serialization across independent keys/providers
- [ ] provider concurrency does not produce a new failure cliff
- [ ] existing data tests pass
- [ ] existing factor tests pass if touched
- [ ] consistency check passes
- [ ] Ruff passes
- [ ] relevant mypy output reviewed
- [ ] OpenAPI contract compared if route dependency shape changed

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
runner GET /bars failures = 0?:
health stays available?:
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
