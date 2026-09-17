# Stage B — H1 deterministic pool-starvation confirmation

Status: contributor-only runtime evidence for issue #107.

## Environment / baseline

- branch: `fix/data-service-saturation`
- reviewed baseline: `ed01be9056776c107ab76a404c328a4fed19f529`
- benchmark DB: `inalpha_issue107`
- Windows / CPython 3.12.13
- production code unchanged; contributor diagnostics remain untracked

The benchmark DB safety helper verified before the run:

```text
benchmark_database=inalpha_issue107
bars_table_ready=True
bars_count_before=0
verify only: no data changed
```

## Windows event-loop prerequisite

The first Stage-B attempt under the default Windows Proactor loop never reached the diagnostic workload because Psycopg async rejected that loop and pool startup timed out. That result is recorded separately in note 70 and is not H1 evidence.

The diagnostic was rerun in a fresh Python process with a process-local `WindowsSelectorEventLoopPolicy`; no project file, OS setting, database configuration, or production code was modified.

## Result

Command shape:

```powershell
uv run python -c "import asyncio,sys; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); import pytest; sys.exit(pytest.main(['-vv','-s','tests/test_issue107_pool_pressure_local.py']))"
```

Result:

```text
1 passed in 2.04s
```

Observed control case (one blocked provider request, pool max_size=2):

```text
GET /health -> 200 in ~15 ms
```

Observed pressure case (two blocked provider requests, pool max_size=2):

```text
GET /openapi.json -> 200 in ~62 ms
GET /health       -> 200 in ~563 ms, only after provider release
both backfills    -> 200 in ~625 ms
```

The provider is the contributor-only deterministic blocking fake. The constituent snapshot scheduler was disabled and no real OHLCV provider was used by the workload.

## Interpretation

H1 is **confirmed as a mechanism on current main**:

```text
/backfill/bars checks out DB capacity
→ waits on external/provider I/O
→ retained DB leases can exhaust a small pool
→ unrelated DB-backed /health waits for provider completion
while
non-DB /openapi.json remains responsive
```

This separates DB-pool starvation from generic event-loop or HTTP-server starvation.

The result does **not** yet establish that H1 is the dominant issue-level bottleneck under the normal pool size and representative agent+runner load. That requires the real-TCP one-worker capacity transition (Stage D), PostgreSQL/pool evidence, and sustained mixed workload evidence before selecting Candidate A.

## Decision

- H1 structural mechanism: **confirmed**.
- H1 production materiality/dominance: **not yet established**.
- Candidate A: **still not applied**.
- Next step: one-worker hardened fake-provider Uvicorn capacity boundary around D08/D10/D12, with exact pool/provider/health/openapi counters captured.
