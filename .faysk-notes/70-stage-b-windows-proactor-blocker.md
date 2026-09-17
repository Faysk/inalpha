# Stage B H1 blocked by Windows ProactorEventLoop

Status: contributor-only runtime finding. This is **not** an H1 result and must not be interpreted as a production regression.

## Session state

The dedicated benchmark DB safety check passed before the diagnostic:

```text
benchmark_database=inalpha_issue107
bars_table_ready=True
bars_count_before=0
verify only: no data changed
```

The checkout still contained only the expected untracked contributor diagnostics after the attempt.

## Attempted diagnostic

Stage B command targeted:

```text
services/data/tests/test_issue107_pool_pressure_local.py
```

The diagnostic failed during FastAPI lifespan startup, before any blocked backfill/control/pressure workload could run.

Observed exception:

```text
psycopg_pool.PoolTimeout: pool initialization incomplete after 30.0 sec
```

Psycopg repeatedly logged the actual cause:

```text
Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
Please use a compatible event loop, for instance a SelectorEventLoop.
```

Environment was Windows / CPython 3.12.13 under pytest-asyncio.

## Interpretation

This run is **inconclusive for H1**. The pool never opened, so the test did not reach:

```text
1 blocked provider call -> health control
2 blocked provider calls -> pool pressure
openapi-vs-health separation
```

Do not count the pytest failure as evidence for or against issue #107's DB-lease hypothesis.

This is a local Windows event-loop compatibility problem in the diagnostic execution path. It does not justify changing production code.

A second harness detail was exposed: the diagnostic passes `timeout=2.0` to the shared pool constructor, but `open(wait=True)` still used its own 30-second initialization wait in this failure path. Do not interpret the 30-second duration as application capacity evidence.

## Safe retry strategy

Retry the same contributor-only pytest in a fresh Python process after selecting `asyncio.WindowsSelectorEventLoopPolicy()` **before pytest starts**. Do this through the command wrapper rather than modifying tracked project code or production settings.

If that retry starts the DB pool successfully, only then interpret the control/pressure assertions as Stage B H1 evidence.

## Classification

- dedicated benchmark DB safety: PASS
- external provider contacted: no workload reached provider phase
- H1 confirmed: no
- H1 falsified: no
- Stage B status: BLOCKED / INCONCLUSIVE
- production code changed: no
- next action: rerun Stage B under Windows Selector event-loop policy
