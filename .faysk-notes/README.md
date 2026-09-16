# Faysk contributor notes — Inalpha #107

These files are **private working notes in the contributor fork workflow**, not upstream project documentation.

They live only on the `notes/issue-107` branch of `Faysk/inalpha` and must **not** be merged into the contribution branch `fix/data-service-saturation` or included in the upstream PR unless `@mirror29` explicitly asks for them.

> Note: the fork is public, so these notes are publicly readable. Do not put secrets, API keys, private datasets, credentials, internal identifiers, or production-derived data here.

## Working branches

```text
mirror29/inalpha:main
        ↑
        │ future PR
        │
Faysk/inalpha
├── main
├── fix/data-service-saturation   # actual contribution branch
└── notes/issue-107               # our working documentation only
```

## Documents

| File | Purpose |
|---|---|
| `00-project-rules.md` | Project conventions, architecture invariants, business rules, testing/PR patterns |
| `01-issue-107-plan.md` | Technical plan for issue #107 |
| `02-request-flow-map.md` | Exact request/concurrency flow map for factor → data → providers/DB |
| `03-reproduction-plan.md` | Reproducible load-test design and commands |
| `04-baseline-results.md` | Pre-change measurements and observations, including concrete transport-error classification and DB/non-DB isolation controls |
| `05-solution-design.md` | Chosen implementation design after evidence is collected |
| `06-implementation-log.md` | Chronological implementation/debugging log |
| `07-before-after-results.md` | Baseline vs fixed benchmark comparison, including moved-bottleneck/provider-capacity checks |
| `08-pr-draft.md` | Draft upstream PR description/checklist |
| `09-working-principles.md` | Contribution discipline: evidence, invariants, smallest justified change, regression mindset |
| `10-active-investigation.md` | Current confirmed static findings, sharpened hypotheses, and next runtime decision gate |
| `11-local-test-runbook.md` | Exact local setup, baseline checks, diagnostic commands, cleanup, and evidence capture sequence |
| `12-static-capacity-model.md` | Per-worker DB capacity model, exact macro fan-out, timeout cascade, H8/H9/H10 interactions |
| `13-caller-backpressure-matrix.md` | Factor/paper/research/dashboard/orchestration behavior if backfill is busy or fails |
| `14-candidate-fix-a-narrow-db-lease.md` | Prepared minimal candidate that releases DB capacity during external provider I/O; not selected until measured |
| `15-error-classification-and-retry-chain.md` | Why `DATA_SERVICE_UNREACHABLE` can mean read timeout, pool-induced slowness, or real connectivity; retry amplification model |
| `16-two-worker-fake-provider-harness.md` | Production-like 1/2-worker Uvicorn harness with a deterministic fake slow provider and no external API stress |
| `17-candidate-fix-b-bound-macro-fanout.md` | Secondary factor-side candidate if cold macro fan-out remains material after the primary bottleneck is addressed |
| `18-candidate-fix-c-data-admission-control.md` | Secondary data-side admission/queue candidate if external in-flight work still saturates the service |
| `19-do-not-do-first.md` | Explicitly rejected first moves: pool/worker inflation, late semaphore, more retries, freshness downgrade, premature distributed machinery |
| `20-candidate-fix-d-factor-http-pooling.md` | Low-priority connection-reuse candidate with explicit bearer-token isolation requirements |
| `21-adjacent-data-db-lease-audit.md` | Audit of nearby data-service paths that also hold DB capacity across external I/O; explicitly kept out of #107 unless measured |
| `22-h8-macro-cache-stampede.md` | Cold macro-cache same-key stampede hypothesis and decision gate for possible factor-side single-flight |
| `23-candidate-a-deep-review.md` | Candidate A transaction, failure-precedence, idempotency and explicit-connection-lifetime review |
| `24-client-timeout-cancellation.md` | H9 runtime test for whether timed-out clients leave older server/provider work alive and overlapping retries |
| `25-pg-stat-activity-diagnostic.md` | DB-side `pg_stat_activity` evidence plan for open transactions retained during fake provider waits |
| `26-h10-default-executor-contention.md` | Shared `asyncio.to_thread` executor contention hypothesis and async-vs-thread fake-provider experiment |
| `27-exact-macro-fanout.md` | Exact current default macro shape: 26 factor specs backed by 18 unique FRED series |
| `28-candidate-a-capacity-decoupling-risk.md` | Guard against “fix DB, overload provider”: provider-concurrency checks after Candidate A |
| `29-runner-resume-factor-burst-shape.md` | Refined restart burst model: factor baseline fan-out depends on timeframe and lineage rather than every runner always requesting the full macro set |
| `30-cross-service-timeout-budget-mismatch.md` | Nested paper→factor→data timeout-budget mismatch and runtime cancellation questions |
| `31-candidate-a-project-fit-and-contract-review.md` | Candidate A style precedent, testability, checkout-count trade-off and error-precedence review |
| `32-provider-concurrency-matrix.md` | Per-venue concurrency/timeout controls and moved-bottleneck risks after DB decoupling |
| `33-h11-factor-live-cache-stampede.md` | Whole live-score cache same-key stampede, shared LRU eviction nuance and service-level materiality gate |
| `34-original-issue-todo-disposition.md` | Maps every original #107 proposed fix to current `main`, showing what is already mitigated, still absent, or evidence-gated |
| `35-psycopg-pool-stats-diagnostic.md` | Direct `AsyncConnectionPool.get_stats()` measurement plan for pool availability, queueing, wait time and errors |
| `tools/test_backfill_pool_pressure_draft.py` | Contributor-only controlled 2-connection-pool baseline diagnostic; includes non-DB control |
| `tools/test_candidate_a_regression_draft.py` | Post-Candidate-A regression with pool=2 and four simultaneous provider waits |
| `tools/test_macro_cache_stampede_draft.py` | Pure factor-unit diagnostic proving whether concurrent cold same-key macro requests coalesce or duplicate work |
| `tools/test_factor_live_cache_stampede_draft.py` | Pure factor-unit diagnostic proving whether concurrent cold identical live score requests coalesce or duplicate main data fetches |
| `tools/issue107_slow_data_app.py` | Fake provider wrapper with async/thread modes, worker PID header, request counters, sync-thread counters and DB-free state endpoint with pool stats |
| `tools/issue107_load_probe.py` | Concurrent backfill + DB/non-DB probe preserving HTTPX error types, percentiles, worker PID distribution and pool-state samples |
| `tools/issue107_timeout_persistence_probe.py` | Real-TCP timeout experiment distinguishing async request cancellation from underlying sync-thread persistence |
| `tools/candidate_a_narrow_db_lease.patch` | Unapplied patch draft for Candidate A; documentation artifact only until baseline evidence selects it |
| `archive/technical-review-2026-09-07.md` | Original full technical review that led to selecting #107 as the first contribution |

## Working method

For issue #107 we follow:

```text
reproduce
→ measure
→ identify bottleneck
→ smallest justified change
→ run the exact same benchmark
→ compare before/after
→ prepare focused PR
```

Before every production change, ask:

```text
What evidence do we have?
Which invariant could this break?
Is there a smaller change that solves the same measured problem?
```

Maintainer feedback is **not a blocker for non-invasive investigation or baseline preparation**. It remains relevant before finalizing scope and production changes.

Do not optimize away project invariants such as financial freshness, explicit failure semantics, authorization/owner boundaries, auditability, or service boundaries.

## Issue

https://github.com/mirror29/inalpha/issues/107
