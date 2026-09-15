# Draft upstream PR — Issue #107

> Working draft only. Final PR should be opened from `Faysk:fix/data-service-saturation` to `mirror29:main` (or `staging` if the maintainer requests it). This notes branch must not be the PR source.

---

## Proposed title

```text
fix(data): bound sustained backfill load
```

Final title may change depending on the actual measured root cause and implementation.

---

## What this PR does

TBD after implementation.

Suggested final shape:

```text
This PR addresses sustained data-service saturation under overlapping factor/backfill/live-runner workloads by <actual measured fix>. It adds deterministic regression coverage and documents before/after measurements against the same mixed-load reproduction.

Fixes #107
```

---

## Scope

- Affected service: `services/data` (plus `services/factor` only if required by measured caller semantics)
- Current phase: D-12+ / N/A as appropriate
- Type: `fix` / `test` / possibly `perf`

---

## Problem / baseline

```text
Commit:
Reproduction:
Observed failure:
Baseline p95:
Baseline error count:
Root cause evidence:
```

Keep this factual. Do not claim a cause that was not reproduced/measured.

---

## Solution

```text
Actual implementation summary:
Why this layer is the correct boundary:
Configuration/defaults:
Backpressure/error semantics:
Freshness behavior:
```

---

## Why this approach

```text
Why simpler alternatives were insufficient:
Why more complex alternatives were deferred:
```

Potential deferred items unless measurements require them:

- per-provider capacity isolation,
- same-key single-flight,
- factor HTTP connection pooling,
- live-runner staggering,
- distributed coordination,
- new telemetry infrastructure.

---

## Before / after

| Metric | Before | After |
|---|---:|---:|
| success rate | TBD | TBD |
| `DATA_SERVICE_UNREACHABLE` | TBD | TBD |
| p50 | TBD | TBD |
| p95 | TBD | TBD |
| p99 | TBD | TBD |
| peak expensive in-flight ops | TBD | TBD |

Add the exact mixed-load scenario used for both sides.

---

## Correctness / business invariants

Explicitly state:

- financial freshness semantics were preserved,
- historical/as-of behavior was not changed,
- provider failure remains distinguishable from valid empty data,
- auth/owner boundaries remain unchanged,
- no direct LLM/order-path constraint was touched,
- no private data or production secrets are included.

---

## Testing

Fill with actual commands/results.

```bash
bash scripts/check-consistency.sh

cd services/data
uv run ruff check .
uv run mypy .
uv run pytest

# if factor touched
cd ../factor
uv run ruff check .
uv run mypy .
uv run pytest
```

Also include the deterministic load/regression harness command.

---

## Self-review checklist

- [ ] Commit messages use `<type>(<scope>): <desc>` in English.
- [ ] One logical change per commit.
- [ ] PR title/body in English.
- [ ] `Fixes #107` present.
- [ ] `bash scripts/check-consistency.sh` passes.
- [ ] Relevant service Ruff passes.
- [ ] Relevant service pytest passes.
- [ ] mypy output reviewed.
- [ ] No unnecessary dependency added.
- [ ] No `services/_shared/`, `.mastra/`, or private-doc changes unless explicitly agreed.
- [ ] Freshness behavior verified.
- [ ] Before/after evidence uses same workload.
- [ ] No secrets/private data in commits, logs, screenshots, or fixtures.

---

## Potential labels

Existing project labels likely relevant to this work:

```text
data
enhancement
```

Do not create new upstream labels just for this PR. Maintainer can apply/adjust labels.

---

## Review notes / questions for maintainer

```text
TBD
```

Only include questions that remain genuinely unresolved at PR time.
