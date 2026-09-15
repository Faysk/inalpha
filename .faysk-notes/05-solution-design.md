# Issue #107 — Solution Design

**Status:** intentionally undecided until baseline evidence exists.

This document records the implementation we actually choose after reproducing #107. It is not a wishlist of every possible reliability improvement.

---

## 1. Evidence that justifies this design

```text
Baseline commit:
Topology / worker count:
Reproduction scenario:
Observed first saturated resource:
Measured evidence:
Contributing factors:
What was ruled out:
Why this is the smallest useful intervention:
```

---

## 2. Chosen design

```text
TBD after baseline
```

### Intended behavior

```text
request
→ validation
→ capacity / DB checkout behavior
→ external work
→ persistence/read
→ response
```

The design must explicitly state **when DB connections are acquired and released**.

---

## 3. DB connection lifetime

Current `/backfill/bars` checks out `DBConn` as a route dependency before entering the handler and retains it across provider/network work.

If baseline confirms this matters, document the new lifecycle precisely:

```text
latest-bar DB checkout:
released before provider wait?:
provider fetch:
insert DB checkout:
transaction / commit behavior:
loop behavior for multiple batches:
```

### Hard review rule

Do not add an admission semaphore that makes requests wait while they already hold `DBConn`.

If using a gate, either:

- admission must occur before scarce DB checkout, or
- DB acquisition must be moved/scoped so waiting requests do not consume the pool.

Any transaction-semantics change must have regression coverage.

---

## 4. Admission/concurrency model

If a capacity gate is justified:

```text
Gate location:
Per-worker limit:
Production worker count assumption:
Effective aggregate capacity:
Queue/wait policy:
Queue timeout:
Cancellation behavior:
Slot release guarantees:
Provider-specific isolation?:
```

Current repository production compose uses two data workers, so a normal `asyncio.Semaphore(N)` is **process-local**, not service-global.

Do not use the word "global" unless the implementation really coordinates across workers.

---

## 5. Configuration

New/changed settings, if any:

| Setting | Default | Meaning | Evidence for default |
|---|---:|---|---|
| TBD | TBD | TBD | TBD |

Rules:

- safe default,
- environment-configurable only where operationally useful,
- no unexplained magic values,
- default justified by benchmark and production topology,
- operator-facing config documented in the appropriate service README/example env if needed.

---

## 6. Error / backpressure semantics

Document any new/changed error:

```json
{
  "code": "TBD",
  "message": "TBD",
  "details": {}
}
```

Questions:

- Is it retryable?
- Which HTTP status matches project semantics?
- Is `Retry-After` useful/appropriate?
- Which callers consume it?
- Could any caller silently continue with cached data?
- Does current/live factor evidence remain freshness-correct?
- Does paper live behavior remain safe?
- Is research/dashboard best-effort degradation intentionally preserved?

### Caller compatibility matrix

Must be filled before finalizing a new busy response:

| Caller | Current behavior | Desired behavior under overload | Code change? |
|---|---|---|---|
| factor | TBD | TBD | TBD |
| paper | TBD | TBD | TBD |
| research | TBD | TBD | TBD |
| dashboard | TBD | TBD | TBD |
| orchestration | TBD | TBD | TBD |

Do not force all callers into the same degradation policy.

---

## 7. Same-key coalescing

Only include if baseline shows duplicate cross-service refresh work is meaningful.

Remember:

- dashboard already performs process-local same-key backfill coalescing;
- a data-side single-flight mechanism must define window semantics (`from_ts`/`to_ts`), leader failure, follower cancellation and multi-worker limitations.

If not measured as material, reject/defer it explicitly.

---

## 8. HTTP client reuse

Only include if connection churn is measured as material.

If factor/client reuse is introduced:

- never keep one user's bearer token on a global singleton client,
- preserve per-request auth isolation,
- document lifecycle/shutdown,
- prove the improvement independently of provider concurrency changes.

---

## 9. Observability

Prefer existing `structlog` + request trace infrastructure.

Add only fields needed to prove/operate the chosen fix:

```text
TBD
```

Possible examples if justified:

```text
backfill_wait_ms
backfill_in_flight
provider_fetch_ms
db_checkout_wait_ms
db_write_ms
```

Do not introduce a telemetry platform in this PR by default.

---

## 10. Files to change

```text
TBD
```

For every file, state why it changes.

Default preference: keep PR 1 data-service-local.

Avoid touching:

```text
services/_shared/
services/paper/live_runner.py
packages/orchestration/
```

unless evidence requires it and maintainer alignment is renewed.

---

## 11. Tests

Choose tests that correspond to the actual implementation.

Potential deterministic coverage:

- [ ] slow provider does not consume DB pool incorrectly
- [ ] DB connection released before provider wait if lifecycle changed
- [ ] capacity never exceeds configured per-worker limit
- [ ] success releases capacity
- [ ] exception releases capacity
- [ ] cancellation releases capacity
- [ ] queue timeout semantics correct
- [ ] upstream error semantics preserved
- [ ] current/live freshness semantics preserved
- [ ] auth remains isolated
- [ ] same-key behavior if single-flight included
- [ ] independent keys/providers are not accidentally serialized unless intended

---

## 12. Benchmark / acceptance

Use the exact same representative workload and topology before/after.

Primary issue target:

```text
DATA_SERVICE_UNREACHABLE after fix = 0
p95 = controlled/bounded for the agreed target workload
```

Also report:

- intentional backpressure separately,
- refresh progress (not only HTTP success),
- DB pool pressure,
- p50/p95/p99,
- variability across repeated runs.

---

## 13. Rejected/deferred alternatives

For each alternative record why it was not chosen.

### Increase Uvicorn workers

```text
Decision: TBD
Reason: production already uses 2 data workers; changing worker count is not a root-cause fix by default.
```

### Lower factor panel concurrency only

```text
Decision: likely defer unless evidence points there
Reason: panel already bounded at 16 and avoids per-symbol fresh backfills.
```

### Add factor macro semaphore only

```text
Decision: TBD
Reason: macro fan-out is still relevant, but client-only throttling may hide a shared data-service capacity flaw. Measure first.
```

### Per-provider semaphores immediately

```text
Decision: defer unless provider starvation is measured.
```

### Distributed queue / Redis lock

```text
Decision: defer unless process-local controls are proven insufficient.
```

### Generic data-side single-flight

```text
Decision: defer unless cross-service duplicate work is measured; dashboard already coalesces its own same-key refreshes.
```

### More client retries

```text
Decision: reject as primary sustained-overload solution; retries can amplify saturation.
```

### New telemetry stack

```text
Decision: defer; use existing logging/benchmark evidence first.
```

---

## 14. Rollback

```text
How to disable/revert behavior:
Config rollback:
Code rollback:
Any data migration involved?: ideally no for PR 1
Does rollback restore exact previous semantics?:
```

---

## 15. PR risk / target branch

```text
Data-service-local bugfix only:
  likely direct PR → main

Cross-service caller semantics or live-runner change:
  pause and ask maintainer; staging likely appropriate
```

This follows upstream `CONTRIBUTING.md` rather than choosing a branch route by convenience.

---

## 16. Maintainer alignment

```text
Date:
Maintainer feedback:
Scope agreed:
Target branch agreed if non-trivial:
Open questions:
```
