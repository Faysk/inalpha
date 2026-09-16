"""Contributor-only diagnostic draft for Inalpha issue #107.

This file lives on the notes branch and is NOT intended to be included in the upstream PR
as-is. Copy it into ``services/data/tests/`` temporarily when running the baseline locally.

Purpose
-------
Prove or falsify one narrow mechanism from static code inspection:

    /backfill/bars checks out DBConn
    -> waits on slow external connector I/O
    -> DB connection remains occupied
    -> enough concurrent backfills can starve unrelated DB-backed endpoints

The connector is fully fake/blocking. No external provider is contacted.

The diagnostic forces the data-service pool to ``max_size=2`` instead of relying on the ordinary
repository default (currently 10). This makes the control/pressure boundary small, deterministic,
and resistant to future pool-size tuning.

It also probes ``/openapi.json`` as a non-DB control. If OpenAPI stays responsive while ``/health``
blocks, that separates DB-pool starvation from generic event-loop/HTTP-server starvation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.integration


class _BlockingConnector:
    """Fake connector that blocks until the test releases all provider calls."""

    def __init__(self, expected_in_flight: int) -> None:
        self.expected_in_flight = expected_in_flight
        self.entered = 0
        self.all_entered = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        limit: int = 1000,
    ) -> list[tuple[datetime, float, float, float, float, float]]:
        del symbol, timeframe, limit
        self.entered += 1
        if self.entered >= self.expected_in_flight:
            self.all_entered.set()

        await self.release.wait()

        ts = since if since.tzinfo is not None else since.replace(tzinfo=UTC)
        return [(ts, 100.0, 101.0, 99.0, 100.5, 1000.0)]

    async def close(self) -> None:
        return None


async def _start_blocked_backfills(
    *,
    client: httpx.AsyncClient,
    connector: _BlockingConnector,
    auth_headers: dict[str, str],
    count: int,
) -> list[asyncio.Task[httpx.Response]]:
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)

    tasks: list[asyncio.Task[httpx.Response]] = []
    for idx in range(count):
        tasks.append(
            asyncio.create_task(
                client.post(
                    "/backfill/bars",
                    headers=auth_headers,
                    json={
                        "venue": "binance",
                        "symbol": f"POOL-{count}-{idx}-{uuid4().hex[:8]}",
                        "timeframe": "1h",
                        "from_ts": start.isoformat(),
                        "to_ts": end.isoformat(),
                    },
                )
            )
        )

    await asyncio.wait_for(connector.all_entered.wait(), timeout=5.0)
    return tasks


async def test_route_scoped_dbconn_starves_small_pool_while_provider_waits(
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """Baseline diagnostic with an explicit two-connection DB pool.

    Control:
        one blocked provider call -> one of two DB leases retained -> /health still succeeds.

    Pressure:
        two blocked provider calls -> both DB leases retained -> /openapi stays responsive while
        /health waits until provider release.
    """
    from inalpha_shared.db import init_pool as shared_init_pool

    from inalpha_data import main as main_mod
    from inalpha_data.connectors import _base as connectors_base

    async def _init_small_pool(database_url: str) -> Any:
        return await shared_init_pool(
            database_url,
            min_size=1,
            max_size=2,
            timeout=2.0,
        )

    monkeypatch.setattr(main_mod, "init_pool", _init_small_pool)

    async with main_mod.app.router.lifespan_context(main_mod.app):
        transport = httpx.ASGITransport(app=main_mod.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=5.0,
        ) as client:
            # Control: 1/2 pool slots held by the slow route; health still gets the other one.
            one = _BlockingConnector(expected_in_flight=1)
            connectors_base._REGISTRY["binance"] = one
            one_tasks = await _start_blocked_backfills(
                client=client,
                connector=one,
                auth_headers=auth_headers,
                count=1,
            )
            try:
                health = await asyncio.wait_for(client.get("/health"), timeout=1.0)
                assert health.status_code == 200
                assert health.json()["db"] == "ok"
            finally:
                one.release.set()
                one_responses = await asyncio.gather(*one_tasks)
            assert all(r.status_code == 200 for r in one_responses)

            # Pressure: 2/2 leases are now retained while both requests await fake provider I/O.
            two = _BlockingConnector(expected_in_flight=2)
            connectors_base._REGISTRY["binance"] = two
            two_tasks = await _start_blocked_backfills(
                client=client,
                connector=two,
                auth_headers=auth_headers,
                count=2,
            )

            openapi = await asyncio.wait_for(client.get("/openapi.json"), timeout=0.5)
            assert openapi.status_code == 200

            health_task = asyncio.create_task(client.get("/health"))
            try:
                # Keep the request alive after our short observation timeout. If it cannot enter
                # while the non-DB control can, the current route ordering is consistent with DB
                # pool starvation rather than generic ASGI/event-loop starvation.
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(health_task), timeout=0.5)
            finally:
                two.release.set()

            two_responses = await asyncio.gather(*two_tasks)
            health = await asyncio.wait_for(health_task, timeout=2.0)

            assert all(r.status_code == 200 for r in two_responses)
            assert health.status_code == 200
            assert health.json()["db"] == "ok"

    main_mod.app.dependency_overrides.clear()
