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
| `11-local-test-runbook.md` | Authoritative local setup/baseline/safety/decision sequence, now including sustained O-stage acceptance |
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
| `28-candidate-a-capacity-decoupling-risk.md` | Guard against “fix DB, overload provider” plus same-key completion-order/final-candle correctness checks after Candidate A |
| `29-runner-resume-factor-burst-shape.md` | Refined restart burst model: factor baseline fan-out depends on timeframe and lineage rather than every runner always requesting the full macro set |
| `30-cross-service-timeout-budget-mismatch.md` | Nested paper→factor→data timeout-budget mismatch and runtime cancellation questions |
| `31-candidate-a-project-fit-and-contract-review.md` | Candidate A style precedent, testability, checkout-count trade-off and error-precedence review |
| `32-provider-concurrency-matrix.md` | Per-venue concurrency/timeout controls and moved-bottleneck risks after DB decoupling |
| `33-h11-factor-live-cache-stampede.md` | Whole live-score cache same-key stampede, shared LRU eviction nuance and service-level materiality gate |
| `34-original-issue-todo-disposition.md` | Maps every original #107 proposed fix to current `main`, showing what is already mitigated, still absent, or evidence-gated |
| `35-psycopg-pool-stats-diagnostic.md` | Direct `AsyncConnectionPool.get_stats()` measurement plan for pool availability, queueing, wait time and errors |
| `36-safe-full-stack-macro-harness.md` | Real factor→data local-HTTP macro benchmark with fake Binance/FRED providers and cold/warm/same/unique-key controls; where older startup snippets conflict, follow `49-runtime-safety-order.md` |
| `37-existing-db-http-separation-precedent.md` | Existing live-runner M-1 rule and implementation: short DB read → external HTTP → short DB write, directly matching Candidate A's intended resource ordering |
| `38-runner-poll-harness.md` | Live-runner-like fresh poll harness, aligned-vs-stagger control and in-flight DB/provider sampling |
| `39-mixed-workload-harness.md` | Combined cold factor/macro + runner polling + health/openapi workload used for the issue-level before/after decision gate; factor startup safety is governed by `49-runtime-safety-order.md` |
| `40-local-preflight-helper.md` | Safe branch/SHA/clean-tree checks plus hardened contributor diagnostics/safety-helper materialization and cleanup workflow |
| `41-benchmark-db-state-determinism.md` | Dedicated resettable `inalpha_issue107` database and factor-cache/DB-cache discipline so cold/warm and before/after runs are comparable |
| `42-runtime-readiness-static-validation.md` | Static check that diagnostics match current pytest, auth, schemas, venue/timeframe support, environment loading and Candidate A correctness caveats before runtime |
| `43-candidate-a-overlap-write-correctness.md` | Explicit guard against overstating UPSERT safety; same-key mutable-candle completion inversion is tested only if H4 proves material overlap |
| `44-runtime-execution-manifest.md` | Stable A–O runtime scenario names, controlled inputs, result filenames and baseline→candidate comparison discipline |
| `45-evidence-capture-helper.md` | Windows evidence-session workflow that records revision/tool/host metadata outside the Git working tree without dumping secrets |
| `46-data-regression-ci-enforcement-gap.md` | Current CI runs data Ruff/mypy but not data pytest; records options without automatically broadening #107 into a CI-policy change |
| `47-benchmark-reset-safety.md` | Fail-closed dedicated-DB reset workflow so cold-state benchmarks cannot silently truncate the ordinary development database |
| `48-factor-target-fail-closed.md` | Fail-closed factor wrapper so factor/mixed load cannot silently route to the ordinary data-service instead of the fake benchmark target |
| `49-runtime-safety-order.md` | Authoritative pre-load chain including scheduler isolation, fake/blocked OHLCV routing, factor pinning and no-load verification |
| `50-sustained-load-acceptance.md` | Separates short mechanism probes from sustained p95 evidence and defines O1 cross-sectional, O2 same-key stress and optional O3 stagger acceptance scenarios |
| `51-sustained-results-template.md` | Three-run sustained evidence template with separate latency/error/backlog/provider/pool signals, scheduler-lag accounting and before→after wording guard |
| `52-provider-isolation-and-soak-hardening.md` | Harness review that disables startup constituent scheduling, blocks non-fake OHLCV venues, avoids schedule catch-up bursts and adds provider/pool counter deltas |
| `53-candidate-a-current-main-revalidation.md` | Revalidates the unapplied narrow DB-lease candidate against current route/storage/shared-DB/test semantics and records what would and would not change |
| `54-sustained-child-task-cancellation.md` | Acceptance-harness guard that explicitly cancels/drains spawned request tasks so settle-timeout evidence is not contaminated by orphan local load |
| `tools/test_backfill_pool_pressure_draft.py` | Contributor-only controlled 2-connection-pool baseline diagnostic; includes non-DB control |
| `tools/test_candidate_a_regression_draft.py` | Post-Candidate-A property regression with pool=2, four simultaneous provider waits and background scheduler isolation |
| `tools/test_macro_cache_stampede_draft.py` | Pure factor-unit diagnostic proving whether concurrent cold same-key macro requests coalesce or duplicate work |
| `tools/test_factor_live_cache_stampede_draft.py` | Pure factor-unit diagnostic proving whether concurrent cold identical live score requests coalesce or duplicate main data fetches |
| `tools/issue107_slow_data_app.py` | Hardened fake provider wrapper: requested OHLCV venues deterministic, other registered OHLCV venues fail closed, startup constituent scheduler forced off, provider/HTTP/thread/pool state exposed |
| `tools/issue107_load_probe.py` | Concurrent backfill + DB/non-DB probe preserving HTTPX error types, percentiles, worker PID distribution and pool-state samples; fails closed unless Binance is fake |
| `tools/issue107_timeout_persistence_probe.py` | Real-TCP timeout experiment distinguishing async request cancellation from underlying sync-thread persistence |
| `tools/issue107_factor_app.py` | Contributor-only factor wrapper that refuses startup unless its configured data-service URL matches the expected local fake target |
| `tools/issue107_target_check.py` | No-load verifier for fake venues, blocked/fake consistency, scheduler isolation and factor→data routing before macro/mixed capacity load |
| `tools/issue107_factor_macro_probe.py` | Safe full-stack cold/warm factor macro probe with factor→data HTTP, fake-provider and pool-counter deltas |
| `tools/issue107_runner_poll_probe.py` | Live-runner-like fresh poll probe with aligned/staggered scheduling and peak in-flight pool/provider sampling |
| `tools/issue107_mixed_workload_probe.py` | Combined factor macro + runner fresh polling + DB/non-DB control workload for issue-level reproduction |
| `tools/issue107_sustained_mixed_probe.py` | Base bounded soak helper; same-key-heavy by design and retained as H11 stress machinery |
| `tools/issue107_sustained_acceptance_probe.py` | Acceptance-oriented bounded soak using unique cross-sectional factor symbols by default, explicit same-key control, missed-slot accounting, child-task draining, partial backlog evidence and one-worker provider/pool counter deltas |
| `tools/prepare_issue107_local.ps1` | Windows PowerShell preflight/materialization helper; refuses dirty/drifted/tracked destinations and never applies production changes |
| `tools/prepare_issue107_local.sh` | Bash/WSL/Linux equivalent of the safe preflight/materialization helper |
| `tools/issue107_capture_env.ps1` | Creates a local baseline/candidate evidence directory and records non-secret revision/tool/host metadata; never uploads results |
| `tools/issue107_benchmark_db.ps1` | PowerShell verify/reset helper hard-coded to the dedicated `inalpha_issue107` DB; resets only `public.bars` after safety checks |
| `tools/issue107_benchmark_db.sh` | Bash/WSL equivalent of the dedicated benchmark DB verify/reset helper |
| `tools/candidate_a_narrow_db_lease.patch` | Unapplied patch draft for Candidate A; wording explicitly keeps same-key completion ordering as a separate correctness question |
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
