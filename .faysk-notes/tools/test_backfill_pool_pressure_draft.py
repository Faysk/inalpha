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
                        "symbol": f"POOL-{idx}-{uuid4().hex[:8]}",
                        "timeframe": "1h",
                        "from_ts": start.isoformat(),
                        "to_ts": end.isoformat(),
                    },
                )
            )
        )

    await asyncio.wait_for(connector.all_entered.wait(), timeout=5.0)
    return tasks


async def test_nine_blocked_backfills_leave_capacity_for_health(
    app_with_overrides: Any,
    auth_headers: dict[str, str],
) -> None:
    """Control: with 9/10 pool slots occupied, /health should still get one connection."""
    from inalpha_data.connectors import _base as connectors_base

    connector = _BlockingConnector(expected_in_flight=9)
    connectors_base._REGISTRY["binance"] = connector

    transport = httpx.ASGITransport(app=app_with_overrides)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=5.0,
    ) as client:
        tasks = await _start_blocked_backfills(
            client=client,
            connector=connector,
            auth_headers=auth_headers,
            count=9,
        )

        try:
            health = await asyncio.wait_for(client.get("/health"), timeout=1.0)
            assert health.status_code == 200
            assert health.json()["db"] == "ok"
        finally:
            connector.release.set()
            responses = await asyncio.gather(*tasks)

    assert all(r.status_code == 200 for r in responses)


async def test_ten_blocked_backfills_starve_health_until_provider_releases(
    app_with_overrides: Any,
    auth_headers: dict[str, str],
) -> None:
    """Diagnostic: 10 blocked backfills occupy the default 10-connection process pool."""
    from inalpha_data.connectors import _base as connectors_base

    connector = _BlockingConnector(expected_in_flight=10)
    connectors_base._REGISTRY["binance"] = connector

    transport = httpx.ASGITransport(app=app_with_overrides)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=5.0,
    ) as client:
        tasks = await _start_blocked_backfills(
            client=client,
            connector=connector,
            auth_headers=auth_headers,
            count=10,
        )

        health_task = asyncio.create_task(client.get("/health"))
        try:
            # Shield keeps the request alive after the diagnostic timeout. If this times out
            # while nine backfills do not, the behavior is consistent with pool starvation.
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(health_task), timeout=0.5)
        finally:
            connector.release.set()

        responses = await asyncio.gather(*tasks)
        health = await asyncio.wait_for(health_task, timeout=2.0)

    assert all(r.status_code == 200 for r in responses)
    assert health.status_code == 200
    assert health.json()["db"] == "ok"
