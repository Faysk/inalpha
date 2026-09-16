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
| `04-baseline-results.md` | Pre-change measurements and observations |
| `05-solution-design.md` | Chosen implementation design after evidence is collected |
| `06-implementation-log.md` | Chronological implementation/debugging log |
| `07-before-after-results.md` | Baseline vs fixed benchmark comparison |
| `08-pr-draft.md` | Draft upstream PR description/checklist |
| `09-working-principles.md` | Contribution discipline: evidence, invariants, smallest justified change, regression mindset |
| `10-active-investigation.md` | Current confirmed static findings, sharpened hypotheses, and next runtime decision gate |
| `11-local-test-runbook.md` | Exact local setup, baseline checks, diagnostic commands, cleanup, and evidence capture sequence |
| `tools/test_backfill_pool_pressure_draft.py` | Contributor-only deterministic diagnostic for DB-pool starvation while provider I/O is blocked |
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
