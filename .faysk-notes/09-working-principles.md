# Issue #107 — Working Principles

**Purpose:** keep the contribution disciplined while investigating and fixing #107.

These are contributor-side working rules, not upstream project policy.

---

## Core rule

> Resolve #107 without moving the problem somewhere else in the system.

A change is not successful merely because one endpoint becomes faster or stops returning a specific error. It must improve the representative workload without creating a new bottleneck, weakening correctness, or hiding degradation.

Examples of false fixes:

```text
reduce data freshness to lower load
→ availability improves
→ financial correctness regresses

add a semaphore after DB checkout
→ provider concurrency falls
→ queued requests keep scarce DB connections
→ pool contention gets worse

add more retries
→ transient success may improve
→ sustained overload gets amplified

return HTTP 200 with no useful data progress
→ error count looks better
→ underlying refresh still failed
```

---

## Three questions before every production change

Before changing production code, answer:

1. **What evidence do we have?**
   - What did we reproduce?
   - Which resource saturates first?
   - Is the behavior repeatable?
   - Are we separating provider failure from application saturation?

2. **Which invariant could this break?**
   - financial freshness,
   - explicit failure semantics,
   - service boundaries,
   - owner/auth isolation,
   - auditability,
   - point-in-time correctness,
   - operational behavior under multiple workers.

3. **Is there a smaller change that solves the same measured problem?**
   - prefer one justified boundary change over a broad reliability rewrite,
   - defer queues, distributed locks, new telemetry stacks, caller rewrites, or scheduling changes unless evidence requires them.

If one of these questions cannot be answered, keep investigating before changing production behavior.

---

## Contribution objective

The goal is not to demonstrate sophistication.

The preferred result is a change the maintainer can read and conclude:

```text
this addresses the reproduced problem
this fits the existing architecture
this preserves the project's business rules
this has regression coverage
this is maintainable after the contributor leaves
```

If the correct solution is 20 lines plus two focused tests, that is better than a more elaborate subsystem that solves the same problem with more operational surface area.

---

## Investigation flow

```text
understand current code
→ reproduce current failure
→ establish baseline
→ identify the first constrained resource
→ form a narrow hypothesis
→ test the hypothesis
→ implement the smallest justified change
→ run the identical benchmark
→ verify correctness invariants
→ document before/after evidence
→ prepare focused PR
```

Do not reverse this into:

```text
pick a favorite solution
→ implement it
→ search for evidence that it helped
```

---

## Regression mindset

For every improvement, ask what became worse.

Performance comparison should include more than latency/error rate where relevant:

```text
p50 / p95 / p99
transport errors
intentional backpressure
DB-pool pressure
provider calls
actual data progress
freshness/cutoff behavior
CPU / memory
caller degradation semantics
```

A lower `DATA_SERVICE_UNREACHABLE` count is not sufficient if the system silently returns stale or incomplete data instead.

---

## Root-cause discipline

Use language carefully in notes and PRs:

```text
hypothesis
observed correlation
reproduced bottleneck
measured root cause
```

Do not promote a hypothesis to root cause because it looks plausible from code inspection.

Examples currently under investigation for #107 include:

- DB connection lifetime across slow provider I/O,
- unbounded/insufficiently bounded expensive backfills,
- provider serialization and queueing,
- live/current factor macro fan-out,
- connection churn,
- duplicate same-key work,
- live-runner burst overlap.

Measurements decide which of these matter.

---

## Scope discipline

The first PR should solve the reproduced #107 problem, not every reliability concern discovered nearby.

When adjacent debt is found:

```text
relevant to root cause / required for correctness
→ include if necessary and explain why

useful but independent
→ document / propose follow-up
```

Do not turn #107 into a drive-by refactor.

---

## Maintainer-first review test

Before marking the PR ready, read the diff as if we were the maintainer and ask:

- Why does each changed file need to change?
- Could one of these changes be removed without losing the fix?
- Are defaults justified by evidence rather than intuition?
- Are failure modes understandable?
- Is rollback straightforward?
- Will another contributor understand this six months from now?
- Does the PR prove the fix using the same workload that reproduced the problem?

If the diff is difficult to explain concisely, the scope may be too large.

---

## Final principle

> Help the project become more reliable, not merely make the benchmark greener.

For #107, a valid solution must improve capacity behavior **and** preserve the meaning of a successful result.
