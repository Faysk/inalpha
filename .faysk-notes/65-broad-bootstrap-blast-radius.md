# Issue #107 — Broad bootstrap execution / blast-radius record

Status: contributor-only environment note. This is not part of issue #107's production fix and must not be included in the upstream PR unless the maintainer explicitly asks for local reproducibility details.

## What happened

Before narrowing the #107 bootstrap to the minimum required services, a broader dependency-setup block was already executed locally.

The executed setup did all of the following:

- confirmed an explicit CPython 3.12 interpreter was available (`3.12.13`),
- ran orchestration dependency installation with `corepack pnpm@11.1.2 install --frozen-lockfile`,
- ran `uv sync --frozen --python 3.12` in `data`, `paper`, `research`, `factor`, and `evolver`,
- ran the same frozen Python sync in `infra/migrations`,
- created local root `.env` / `infra/.env` from the examples when absent,
- finished with `git status --short` empty.

## What changed locally

The commands populated local ignored/runtime artifacts:

- `packages/orchestration/node_modules` from the existing lockfile,
- per-service `.venv` environments using CPython 3.12.13,
- the migrations `.venv`,
- local `.env` files if they did not already exist.

These are local development/runtime artifacts. They are not production source changes.

## What did *not* change

Evidence from the command output:

- pnpm reported `Lockfile is up to date, resolution step is skipped`,
- every Python sync used `--frozen`,
- final `git status --short` was empty.

Therefore no tracked source file or tracked lockfile was modified by this bootstrap run.

## Risk assessment

The broad bootstrap has a wider **local-environment** blast radius than needed for #107 because it prepares paper/research/evolver/orchestration in addition to data/factor/migrations.

Possible local effects are limited to development environments: an existing service `.venv` could be replaced/synchronized to the repository's locked dependency set, and orchestration `node_modules` is now populated according to the lockfile. Any previously manually installed, untracked packages inside those environments would not be guaranteed to survive a sync.

No evidence currently indicates that this broke project source, dependency locks, or repository state. The empty final Git status is the important guard.

The generated `.env` files can affect later local commands because application startup may read them. Treat them as local configuration, not benchmark evidence, and do not edit them merely to make #107 resets convenient. The dedicated benchmark DB continues to be selected through process-scoped benchmark environment variables.

## Decision for the rest of #107

Do not undo or rebuild the already-prepared environments simply because the bootstrap was broader than necessary. Doing so would add churn without improving the benchmark.

From this point onward, keep the runtime path minimal:

```text
data
factor
infra/migrations
PostgreSQL
Redis
```

Only involve paper/research/evolver/orchestration if a later measured scenario explicitly requires them.

For before/after #107 evidence, reuse the same data/factor Python 3.12 environments and the same locked dependencies so environment drift does not contaminate the comparison.

## Classification

- Production/code defect: no.
- Repository contamination: not observed.
- Local environment change: yes, broader than necessary but controlled/frozen.
- #107 blocker: no.
- Lesson: use the smallest setup blast radius just as we use the smallest justified production change.
