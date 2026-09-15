# Inalpha Issue #107 — Technical Plan

**Issue:** https://github.com/mirror29/inalpha/issues/107  
**Repository:** https://github.com/mirror29/inalpha  
**Contribution branch:** `fix/data-service-saturation`  
**Notes branch:** `notes/issue-107`  
**Status:** Draft / discovery  
**Last updated:** 2026-09-16

---

## 1. Goal

Resolve the sustained-load failure mode described in #107:

> `data-service` becomes saturated when factor/panel requests, multi-symbol data access, backfills, and live-runner polling overlap, causing latency growth and occasional `DATA_SERVICE_UNREACHABLE` errors.

The goal is **not** to increase concurrency blindly.

The data path should become:

- measurable,
- bounded,
- predictable under load,
- resistant to retry amplification,
- operationally understandable.

The first implementation should remain deliberately small and measurable.

---

## 2. Current-state findings

The issue was opened in June 2026, but some mitigation ideas are already present in current `main`.

### Already present

- `FactorEngine.panel_score()` uses bounded fetch concurrency.
- `_PANEL_FETCH_CONCURRENCY = 16`.
- Multi-symbol custom factor scoring reuses the same limit.
- Cross-sectional panel paths intentionally avoid forced per-symbol fresh backfills.
- `/backfill/bars` performs incremental continuation from the latest persisted bar.
- factor `DataClient.get_bars()` retries connection-level transient failures with bounded backoff.
- structured logging and `trace_id` already exist.
- the codebase already uses `asyncio.Semaphore` and capacity limits elsewhere.

### Hypotheses still to validate

1. `/backfill/bars` may still lack a generic global/per-provider in-flight admission gate.
2. Concurrent identical `(venue, symbol, timeframe)` refreshes may duplicate upstream work.
3. Factor multi-symbol paths may create excessive short-lived `httpx.AsyncClient` instances / connection churn.
4. Live-runner polling may align in bursts and compete with interactive traffic.
5. Retry behavior can amplify sustained overload.
6. There is not yet a reproducible mixed-load baseline for the current code.

These remain hypotheses until measured.

---

## 3. Scope

### In scope

- `services/data`
- `services/factor` only if measurements justify caller/client changes
- reproducible load/reliability tooling
- service-to-service HTTP behavior
- admission control / backpressure
- retry semantics
- observability specifically needed for #107
- regression/load validation
- live-runner scheduling only if measurements show it remains a major contributor

### Out of scope for the first pass

- factor formula changes
- trading strategy changes
- research/debate changes
- whole-system redesign
- distributed queues without evidence
- horizontal scaling as the first solution
- worker-count tuning by guesswork
- large unrelated refactors

---

## 4. Success criteria

Exact numeric targets will be finalized after baseline measurement.

Initial criteria:

- [ ] Reproducible mixed-load scenario exists.
- [ ] Baseline p50/p95/p99 latency recorded.
- [ ] Request/error counts recorded.
- [ ] Expensive in-flight work observable.
- [ ] Backfill concurrency remains bounded.
- [ ] Overload does not create unbounded work.
- [ ] Same-key duplicate work is removed if proven significant.
- [ ] Retry behavior does not create a retry storm.
- [ ] `DATA_SERVICE_UNREACHABLE` is eliminated or materially reduced under representative load.
- [ ] p95 remains bounded/repeatable under the target workload.
- [ ] Existing data/factor correctness tests remain green.
- [ ] Financial freshness semantics are preserved.
- [ ] No financial correctness behavior changes silently.

---

# 5. Implementation strategy

## Phase 0 — Reproduce before changing production code

### Objective

Verify whether current `main` still reproduces the failure class from #107 and locate the real bottleneck.

### Work

- [ ] Start complete local stack.
- [ ] Confirm services healthy.
- [ ] Select representative symbols/venues/data without relying on private production secrets.
- [ ] Build a small deterministic load harness.
- [ ] Run workloads individually.
- [ ] Run mixed workloads.
- [ ] Capture logs, timings, resource symptoms.

### Workload A — factor panel

Representative sizes:

```text
~10 symbols
~50 symbols
up to ~300 symbols where meaningful/supported
```

Measure:

- request duration,
- factor CPU,
- factor→data call count,
- failed symbol fetches,
- data-service latency.

### Workload B — backfill

Concurrent `/backfill/bars` calls across multiple symbols/venues/timeframes.

Ramp gradually:

```text
2
4
8
16 concurrent
```

Do not begin with destructive external-provider stress.

### Workload C — live-runner-like polling

Use actual live runner if practical; otherwise simulate realistic fresh-bar polling patterns first.

### Workload D — mixed

Run A + B + C concurrently.

This is the primary test because #107 is about workload interference, not just one isolated endpoint.

### Baseline fields

```text
scenario
duration
total_requests
successful_requests
failed_requests
DATA_SERVICE_UNREACHABLE count
HTTP 5xx count
timeout count
p50
p95
p99
max latency
peak in-flight work
CPU
memory
DB-pool symptoms
provider-specific errors
```

### Phase exit

Do not tune concurrency until we know where waiting/saturation actually occurs.

---

## Phase 1 — Minimal capacity observability

### Objective

Make saturation understandable using the project's existing logging infrastructure.

Candidate structured fields/events for expensive data operations:

- request start/end
- total duration
- current in-flight count
- admission wait time
- venue/provider
- endpoint
- result class
- timeout/upstream/validation error
- trace ID

Where practical, distinguish:

```text
queue_wait_ms
upstream_fetch_ms
db_write_ms
total_request_ms
```

### Phase exit

For a slow request, we should be able to explain *why* it was slow.

---

## Phase 2 — Server-side admission control around expensive backfills

### Objective

Prevent expensive refresh work from consuming unbounded data-service capacity.

Candidate settings:

```text
DATA_BACKFILL_MAX_CONCURRENCY
DATA_BACKFILL_QUEUE_TIMEOUT_S
```

Likely code area:

```text
services/data/src/inalpha_data/config.py
services/data/src/inalpha_data/api/backfill.py
services/data/tests/test_backfill_router.py
```

Possibly a small local module such as:

```text
services/data/src/inalpha_data/admission.py
```

but only if it improves clarity.

### Basic flow

```text
request
→ validate
→ wait for capacity
→ acquire slot
→ incremental upstream fetch + persistence
→ release slot
```

### Global vs per-provider

Start with the **smallest model justified by measurements**.

A global semaphore is simpler and may be sufficient.

Per-provider isolation should only be added if the baseline shows one provider monopolizes capacity.

Do not hardcode arbitrary provider limits before evidence exists.

---

## Phase 3 — Same-key request coalescing / single-flight

### Objective

Avoid repeated upstream work when several callers request the same refresh simultaneously.

Candidate key:

```text
(venue, canonical_symbol, timeframe)
```

Desired behavior:

```text
A → leader → performs refresh
B → waits
C → waits
A completes
B/C reuse persisted result
```

Instead of three independent provider calls.

Before implementation answer:

- Is same-key duplication actually significant?
- How do different `to_ts` values interact?
- Should followers re-check DB freshness after leader completion?
- How are leader failure/cancellation propagated?
- Is process-local coordination sufficient?

Do not introduce distributed locking without a demonstrated multi-process need.

---

## Phase 4 — Factor→data HTTP client lifetime

### Objective

Determine whether connection churn contributes materially to saturation.

Current concern:

`FactorEngine._fetch_df()` creates a `DataClient` context for individual fetches, and `DataClient` owns its own `httpx.AsyncClient`.

With many symbols this can mean repeated short-lived client instances even though concurrency is bounded.

### Experiment

Compare current behavior with a safe batch/service-lifetime pooling design.

Measure:

- p50/p95,
- connection errors,
- total request duration,
- connection/socket churn where practical,
- resource use.

### Security rule

Do not create a singleton client that stores one user's bearer token.

If connection reuse is introduced, separate shared transport/pool lifetime from per-request Authorization headers.

This is especially important for future multi-tenant behavior.

---

## Phase 5 — Explicit backpressure and retry policy

### Objective

Make sustained overload predictable instead of allowing retry amplification.

Potential policy:

1. wait for bounded capacity,
2. proceed if capacity becomes available,
3. return a stable retryable condition if the wait budget is exceeded,
4. callers distinguish busy vs upstream unavailable vs validation/internal failure.

Potential code concept:

```json
{
  "code": "DATA_SERVICE_BUSY",
  "message": "backfill capacity temporarily exhausted",
  "details": {"retryable": true}
}
```

HTTP status (`429` vs `503`) must align with project semantics and caller behavior; do not choose by preference alone.

### Critical freshness concern

Current factor `fresh=True` behavior performs a best-effort POST backfill and then GETs bars.

If a new busy response is ignored by the client, the system could fall back to cached data while presenting the result as current.

So any new overload response must be designed together with caller semantics.

Avoid:

```text
overload
→ retry
→ more overload
→ retry
→ more overload
```

---

## Phase 6 — Live-runner scheduling/throttling

Only touch this if server-side capacity protection does not sufficiently resolve the mixed-load problem.

Possible improvements if evidence supports them:

- small jitter,
- staggered starts,
- polling concurrency limit,
- market-hours-aware scheduling,
- priority distinction between interactive/background workloads.

Protect the shared data boundary first.

---

## Phase 7 — Validation and regression tests

### Unit/regression coverage

Potential tests:

- [ ] configured concurrency limit is never exceeded
- [ ] gate releases on success
- [ ] gate releases on exception
- [ ] cancellation does not leak capacity
- [ ] queue timeout returns expected error semantics
- [ ] provider failure does not leak slots
- [ ] same-key single-flight success/failure if implemented
- [ ] different keys may proceed independently
- [ ] auth/freshness behavior remains correct

Use fake/delayed connectors rather than real-provider stress.

### Before/after table

| Metric | Baseline | After | Change |
|---|---:|---:|---:|
| Success rate | TBD | TBD | TBD |
| `DATA_SERVICE_UNREACHABLE` | TBD | TBD | TBD |
| p50 | TBD | TBD | TBD |
| p95 | TBD | TBD | TBD |
| p99 | TBD | TBD | TBD |
| Peak in-flight backfills | TBD | TBD | TBD |
| Peak queue wait | TBD | TBD | TBD |
| CPU peak | TBD | TBD | TBD |
| Memory peak | TBD | TBD | TBD |

---

# 6. Likely files involved

Initial likely data-service scope:

```text
services/data/src/inalpha_data/config.py
services/data/src/inalpha_data/api/backfill.py
services/data/tests/test_backfill_router.py
services/data/tests/test_api.py
```

Factor only if measurements justify it:

```text
services/factor/src/inalpha_factor/data_client.py
services/factor/src/inalpha_factor/engine.py
services/factor/src/inalpha_factor/config.py
services/factor/tests/test_data_client.py
```

Paper/live runner only if needed after server-side protection:

```text
services/paper/src/inalpha_paper/live_runner.py
```

Protected/shared infrastructure should remain untouched unless explicitly agreed.

---

# 7. Proposed PR strategy

Avoid one giant PR.

### PR 1 — Measurement + minimum admission control

Target:

- reproducible regression/load harness,
- minimum observability needed,
- configurable backfill capacity gate if confirmed,
- deterministic tests,
- before/after evidence.

### PR 2 — duplicate-work suppression

Only if duplicate same-key refresh is proven meaningful.

### PR 3 — HTTP pooling

Only if connection churn is measured as meaningful.

### PR 4 — background scheduling

Only if live-runner traffic remains a significant bottleneck.

---

# 8. Risks

### Lower concurrency stabilizes service but destroys latency

Mitigation: test multiple values; measure queue wait separately.

### Queueing only moves the problem

Mitigation: bounded wait, explicit overload result, observable wait time.

### Shared HTTP client leaks credentials

Mitigation: never bind a user's Authorization token to a global singleton.

### Single-flight serves stale data

Mitigation: followers re-check persisted freshness and preserve current semantics.

### Provider limits differ

Mitigation: add per-provider isolation only from evidence.

### Load test accidentally harms public providers

Mitigation: fake/delayed connectors first; controlled low-rate integration separately.

---

# 9. Questions for maintainer

Ask when useful, not all at once:

- What deployment topology is representative: one process, multiple Uvicorn workers, multiple containers?
- Is `DATA_SERVICE_UNREACHABLE` still seen on current deployment?
- Which provider is currently the largest operational pain point?
- Do production p95/error-rate observations already exist?
- Expected number of concurrent live runs?
- Which workload should have priority under contention: interactive factor/research or background runners?
- Is process-local admission control sufficient for today's deployment?
- Is there an existing metrics stack, or should PR 1 remain structured-log based?

---

# 10. Decision log

### D-001 — Treat #107 as a problem statement, not a literal implementation spec

Reason: current `main` already contains some concurrency/backfill mitigations added after the issue was written.

### D-002 — Measure before tuning

No concurrency value will be changed solely by intuition.

### D-003 — Protect the shared server boundary first

Prefer data-service admission control before adding more client retry complexity.

### D-004 — Keep PR 1 small

Single-flight, pooling, and live-runner scheduling are follow-up candidates, not automatic parts of the first fix.

### D-005 — Preserve freshness semantics

A reliability fix is invalid if it makes stale data look current.

---

# 11. Work log

## 2026-09-16

- [x] Read issue #107.
- [x] Re-check current `main` behavior around panel concurrency and incremental backfill.
- [x] Review project documentation, contribution rules, business invariants, test style, CI, security boundaries.
- [x] Create contributor fork `Faysk/inalpha`.
- [x] Create contribution branch `fix/data-service-saturation`.
- [x] Create separate notes branch `notes/issue-107`.
- [x] Record project rules and technical plan.
- [ ] Maintainer confirms technical direction.
- [ ] Reconfirm upstream `main` immediately before implementation.
- [ ] Establish runnable local/test environment.
- [ ] Run existing data/factor tests before changes.
- [ ] Build load harness.
- [ ] Capture baseline.

---

# 12. Immediate next steps

Once the direction is confirmed:

1. Reconfirm upstream `main` and sync fork/branch.
2. Build/run the supported local stack without code changes.
3. Run existing `data` and `factor` tests.
4. Create the smallest deterministic mixed-load reproduction.
5. Record baseline in `04-baseline-results.md`.
6. Identify the actual bottleneck.
7. Write the chosen design in `05-solution-design.md`.
8. Implement only the first justified change.
9. Repeat the exact same benchmark.
10. Record before/after evidence.
11. Prepare focused Draft PR linked with `Fixes #107`.

---

## Working principle

> Stabilize by measurement, not by adding retries or changing concurrency blindly.
