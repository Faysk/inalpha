# Issue #107 — Minimal benchmark environment scope

Status: contributor-only process note. Not intended for the upstream #107 PR unless the maintainer asks about benchmark methodology.

## Why this note exists

During local bootstrap we noticed that a broad dependency-sync step would touch environments for services outside the immediate #107 fault path (`paper`, `research`, `evolver`, and orchestration), even though the first runtime stages exercise primarily `data`, `factor`, PostgreSQL, Redis, and the migration environment.

The broad sync would not modify tracked production source when run with frozen locks, but it could still recreate or replace local virtual environments and package-manager state for unrelated parts of the checkout. That is unnecessary blast radius for a focused contribution.

## Rule

For the initial #107 baseline, prepare only the dependencies required by the measured path:

```text
services/data
services/factor
infra/migrations
PostgreSQL / Redis infrastructure
```

Do **not** sync orchestration, paper, research, or evolver merely as a bootstrap ritual. Add one of those environments only when a specific measured scenario actually requires it.

## Python version

Use Python 3.12 for the benchmark service environments to align with the project's lint/type-check semantics and CI reference, while leaving the machine-wide Python installation untouched.

A `uv sync --frozen --python 3.12` changes the selected project's local environment, not tracked dependency declarations or the lockfile. Still, it should be limited to the projects actually under test.

## pnpm

The initial #107 data/factor benchmark path does not require orchestration. Therefore there is no reason to invoke pnpm at all before those stages. If a later scenario genuinely requires orchestration, invoke the repository's expected pnpm major explicitly and use the frozen lockfile rather than changing the user's global pnpm installation.

## Safety principle

Prefer the smallest local-environment blast radius just as we prefer the smallest production-code change:

```text
required for measured path -> prepare it
not required yet           -> leave it alone
```

This is a benchmark/reproducibility refinement, not an Inalpha product bug.
