# Stage A baseline — H8/H11 same-key cold-cache duplication

Status: contributor-only runtime evidence for issue #107. No production source changes were made.

## Baseline identity

```text
branch = fix/data-service-saturation
HEAD   = ed01be9056776c107ab76a404c328a4fed19f529
```

The local preparation helper re-fetched the reviewed baseline and the notes branch, then materialized only the expected contributor diagnostics as untracked files. Syntax-only validation passed for all materialized Python and PowerShell helpers.

The factor test environment used CPython 3.12.13 from `services/factor/.venv`, matching the repository's Python 3.12 CI family more closely than the contributor's global Python 3.13.7.

Evidence directory used by the contributor:

```text
G:\Project\inalpha-issue107-results\20260917-204448-baseline-current-main-prechange
```

## H8 — macro same-key cold-cache diagnostic

Command:

```text
uv run pytest -vv -s tests/test_issue107_macro_stampede_local.py
```

Observed:

```text
2 passed in 1.70s
```

Both control properties passed:

```text
test_macro_cache_works_after_population
test_concurrent_cold_macro_cache_does_not_coalesce_currently
```

Interpretation:

- Once populated, the module-level macro cache is shared across request-scoped `FactorEngine` instances and sequential reuse works.
- On a simultaneous cold miss for the same macro key, current main does not coalesce in-flight work: all diagnostic callers can enter the underlying fetch before any result is inserted into the cache.
- This confirms H8 as a real mechanism on current main.
- It does **not** establish H8 as material to the production/representative #107 workload yet.

No data-service, FRED, database, or real provider was contacted by this diagnostic.

## H11 — whole-score same-key cold-cache diagnostic

Command:

```text
uv run pytest -vv -s tests/test_issue107_live_cache_stampede_local.py
```

Observed:

```text
1 passed in 2.77s
```

The passing diagnostic confirms the current expected baseline property:

- simultaneous cold requests for the same live score key do not single-flight/coalesce the in-flight computation,
- all diagnostic callers can independently reach the underlying data fetch,
- after the first wave populates the shared cache, a later same-key request reuses the warm result without entering the fetch probe.

This confirms H11 as a real mechanism on current main, but not yet as the dominant issue-level cause.

## Working-tree safety

After Stage A, `git status --short` contained only the expected untracked contributor tooling materialized by `prepare_issue107_local.ps1`. No tracked production file was modified.

## Decision impact

Stage A result:

```text
H8 mechanism  = confirmed
H11 mechanism = confirmed
materiality   = not established
fix selected  = no
```

Do not implement factor single-flight yet. Continue the runbook in order. Stage B should test H1 independently with the deterministic two-connection data-service pool diagnostic. If H1 is reproduced there, continue into real-Uvicorn capacity and sustained representative workloads before deciding which mechanism is materially responsible for #107.
