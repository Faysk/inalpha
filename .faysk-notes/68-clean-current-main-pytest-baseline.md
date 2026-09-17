# Clean current-main pytest baseline before #107 runtime probes

Status: contributor-only baseline evidence. This records failures already present on the untouched reviewed baseline and must not be mixed into the #107 production fix.

## Baseline state

The contributor-only diagnostics were first removed so the service trees were clean. The repository remained on:

```text
branch = fix/data-service-saturation
HEAD   = ed01be9056776c107ab76a404c328a4fed19f529
```

The recursive Ruff checks for both `services/data` and `services/factor` passed before pytest was started. No production source change was present; final `git status --short` was empty.

## Data service pytest

Observed clean-baseline summary on Windows / CPython 3.12.13:

```text
2 failed, 134 passed, 104 errors in 88.92s
```

Two explicit failures appeared in the summary:

```text
tests/test_connectors.py::test_baostock_ticker_timeout_keeps_lock_until_thread_exits
tests/test_migration_0036.py::test_0036_merges_legacy_symbols_without_deleting_unrelated_rows
```

The migration test uses a hard-coded local database URL for `inalpha_test`; the fresh local Postgres volume used for the #107 benchmark does not contain that database, so that failure is an environment/setup mismatch rather than #107 evidence.

Most of the 104 setup errors are a cascade of:

```text
RuntimeError: DB pool already initialized
```

The current shared DB helper assigns the module-global `_pool` before awaiting `pool.open(wait=True)`. If opening the pool raises, the helper does not restore `_pool = None`; later fixture/lifespan attempts in the same pytest process therefore fail immediately with `DB pool already initialized`. The captured console begins after the first pool failure, so the original trigger for the first pool-open failure is not established by this run and must not be guessed.

This pool-state cascade is useful adjacent reliability evidence, but it is not currently proven to be the production cause of issue #107. Do not patch it as part of #107 without a separate scope decision.

## Factor service pytest

Observed clean-baseline summary:

```text
3 failed, 172 passed, 1 warning in 21.87s
```

All three failures are in `tests/test_candidates.py`:

```text
test_candidates_503_without_db
test_propose_validates_expression_before_db
test_propose_requires_hypothesis
```

Those tests invoke `/candidates` without Authorization and expect the older DB/validation responses (503/400/422). Current `api/candidates.py` declares `Depends(get_current_user)` on the candidate endpoints, so the actual first response is `401 Unauthorized`. This is baseline test/contract drift after the multi-user auth change, not a #107 regression.

## CI context

Current CI runs Ruff (and best-effort mypy) for `data`, `paper`, `research`, `factor`, and `evolver`, but the dedicated Python pytest job covers `paper` and `evolver`; `data` and `factor` pytest are not CI-enforced on this baseline.

That explains how the clean baseline can have green lint while these local data/factor pytest failures remain.

## #107 decision

Do not repair any of these unrelated baseline failures in the saturation PR.

For #107:

1. preserve this clean-baseline evidence,
2. re-materialize contributor-only diagnostics,
3. run Stage A pure factor H8/H11 diagnostics,
4. use the benchmark's own fail-closed target checks before any network load,
5. only select a production candidate after the issue-specific runtime evidence identifies the bottleneck.

Before Stage B data-capacity work, use a fresh-process benchmark target check so a stale pytest `_pool` state cannot contaminate the benchmark process.

## Classification

- #107 root-cause evidence: **no**.
- Current-main lint regression: **no; clean Ruff passed**.
- Current-main local pytest failures: **yes, recorded**.
- Data failure cascade root trigger: **not established**.
- Factor candidate-test drift vs current auth contract: **confirmed statically**.
- Production code changed during this baseline: **no**.
