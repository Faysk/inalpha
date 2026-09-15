# Draft upstream PR — Issue #107

> Working draft only. Final PR should be opened from `Faysk:fix/data-service-saturation` to `mirror29:main` for a focused low-risk data-service fix, or to `staging` if the maintainer requests it / scope expands into high-risk paths. This notes branch must never be the PR source.

---

## Proposed title

Do not lock the title until the measured root cause is known.

Possible data-local examples:

```text
fix(data): prevent backfill load from starving data-service
```

or, if the measured fix is specifically DB lifetime:

```text
fix(data): release DB capacity during backfill provider waits
```

Avoid a title that claims admission control if the actual fix is different.

---

## What this PR does

TBD after implementation.

Final shape:

```text
This PR addresses sustained data-service saturation under the representative #107 mixed workload by <actual measured fix>. The change is backed by deterministic regression coverage and before/after measurements using the same topology and workload.

Fixes #107
```

---

## Scope

Fill from actual change:

```text
Affected service: services/data
Additional service(s), only if required: TBD
Current Phase: D-12+ / N/A as appropriate
Type: fix / test / perf as appropriate
Target branch: main or staging (aligned with maintainer if scope is non-local)
```

---

## Problem / baseline

```text
Baseline commit:
Data worker topology:
DB pool configuration:
Exact reproduction:
Observed first saturated resource:
Baseline DATA_SERVICE_UNREACHABLE count:
Baseline p95:
Refresh no-progress count:
Root-cause evidence:
```

Important: distinguish HTTP success from actual refresh progress.

---

## Solution

```text
Actual implementation summary:
Why this layer is the correct boundary:
DB connection lifetime before/after:
Admission/concurrency behavior, if any:
Configuration/defaults:
Backpressure/error semantics, if any:
Caller compatibility impact:
Freshness behavior:
```

If a semaphore is used, state explicitly whether it is per worker/process and what production worker count means for aggregate capacity.

---

## Why this approach

```text
Why the measured bottleneck required this change:
Why simpler alternatives were insufficient:
Why more complex alternatives were deferred:
```

Potential deferred items unless measurements require them:

- per-provider capacity isolation,
- generic data-side single-flight,
- factor HTTP connection pooling,
- live-runner staggering,
- distributed coordination,
- new telemetry infrastructure,
- unrelated yfinance empty-result semantics (#74).

---

## Before / after

| Metric | Before | After |
|---|---:|---:|
| `DATA_SERVICE_UNREACHABLE` | TBD | **0 target** |
| HTTP success rate | TBD | TBD |
| refreshes with real progress | TBD | TBD |
| zero/no-progress backfills | TBD | TBD |
| p50 | TBD | TBD |
| p95 | TBD | TBD |
| p99 | TBD | TBD |
| DB pool pressure | TBD | TBD |
| peak expensive in-flight ops | TBD | TBD |
| intentional backpressure | N/A | TBD |

Add exact mixed-load scenario, worker topology, repeat count, and variability.

---

## Correctness / business invariants

Explicitly state what was verified:

- financial freshness semantics were preserved,
- historical/as-of behavior was not weakened,
- overload does not silently become stale current success,
- provider/refresh failures were not counted as success merely because HTTP returned 200,
- auth/owner boundaries remain unchanged,
- no direct LLM/order-path constraint was touched,
- service import boundaries remain unchanged,
- no private data or production secrets are included.

If research/dashboard best-effort behavior is relevant, state that it remains intentionally unchanged.

---

## Testing

Fill with actual commands/results.

Minimum repository checks expected for a data-local change:

```bash
bash scripts/check-consistency.sh

cd services/data
uv run ruff check .
uv run mypy .
uv run pytest
```

If factor is touched:

```bash
cd services/factor
uv run ruff check .
uv run mypy .
uv run pytest
```

Also run the upstream-required local CI red-line commands from `CONTRIBUTING.md` before the final push, even when our code did not touch those modules.

Include the deterministic regression test and contributor benchmark command/result in the PR description.

The load harness itself does **not** need to be committed upstream unless it is a generally useful project artifact.

---

## Self-review checklist

- [ ] Commit messages use `<type>(<scope>): <desc>` in English.
- [ ] One logical change per commit.
- [ ] PR title/body in English.
- [ ] `Fixes #107` present.
- [ ] Target branch matches project risk rules / maintainer alignment.
- [ ] `bash scripts/check-consistency.sh` passes.
- [ ] Upstream-required local CI red-line commands pass.
- [ ] Relevant service Ruff passes.
- [ ] Relevant service pytest passes.
- [ ] mypy output reviewed.
- [ ] No unnecessary dependency added.
- [ ] No `services/_shared/`, `.mastra/`, or private-doc changes unless explicitly agreed.
- [ ] DB connection/admission lifetime reviewed if backfill concurrency changed.
- [ ] Per-worker vs service-global semantics documented honestly.
- [ ] Freshness behavior verified.
- [ ] Before/after evidence uses the same workload/topology.
- [ ] HTTP 200/no-progress refreshes are not miscounted as success.
- [ ] No secrets/private data in commits, logs, screenshots, fixtures, or notes copied into the PR.

---

## Labels

Issue #107 currently has no label attached. Existing repository labels that may be relevant include:

```text
data
enhancement
```

Do not create or force labels merely for this PR. The maintainer can classify/adjust them.

---

## Review notes / questions for maintainer

Keep this short at PR time.

Possible items only if still unresolved:

```text
- deployed data worker topology differs from repo compose
- target p95 / target concurrency envelope
- target branch if scope expanded beyond data-service local fix
```
