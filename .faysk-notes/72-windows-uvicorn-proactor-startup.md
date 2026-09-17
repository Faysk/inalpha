# Stage D Windows/Uvicorn startup blocker — Proactor loop still selected

Status: contributor-only runtime finding. Not issue #107 root-cause evidence and not a production-code change.

## Observation

The first real-TCP Stage D attempt failed closed before any load was generated. The load probe could not reach `/__issue107/state` because the contributor data wrapper never completed startup.

Server command attempted to set `asyncio.WindowsSelectorEventLoopPolicy()` before calling `uvicorn.run(...)`, but the Uvicorn server process still ran the data-service lifespan on a Windows Proactor event loop. Psycopg async pool initialization repeatedly logged:

```text
Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
```

and startup ended with:

```text
psycopg_pool.PoolTimeout: pool initialization incomplete after 30.0 sec
ERROR: Application startup failed. Exiting.
```

The subsequent `issue107_load_probe.py` invocation behaved correctly: its strict pre-load target check timed out on `/__issue107/state` and raised `unsafe load-probe target` before creating any backfill load.

## Interpretation

Setting the Windows selector policy before `uvicorn.run()` is not sufficient in this local Uvicorn execution path because Uvicorn owns/creates the event loop used by the server. The Stage B pytest workaround succeeded because pytest ran inside the explicitly selected loop, while the real-Uvicorn path re-established a Proactor loop.

This is a Windows contributor-runtime compatibility issue, not evidence for or against H1 and not a reason to change Inalpha production behavior.

## Next local-only workaround

Construct `uvicorn.Server` directly and run `server.serve()` under an explicit Python 3.12 `asyncio.run(..., loop_factory=...)` using `asyncio.SelectorEventLoop(selectors.SelectSelector())`. This keeps the compatibility workaround outside tracked source and avoids relying on process-global policy behavior.

Do not proceed to D08 until the server prints successful application startup and the contributor `/__issue107/state` endpoint is reachable.
