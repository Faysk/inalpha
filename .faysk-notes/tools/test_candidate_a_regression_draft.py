"""Contributor-only post-fix regression draft for Inalpha issue #107 / Candidate A.

This test is NOT valid for the unmodified baseline: it is intentionally written with the expected
behavior after DB lease narrowing. Keep it on the notes branch until Candidate A is selected and
implemented.

Core property:

    more slow provider calls than the default DB pool size can be in flight
    while an unrelated DB-backed endpoint remains responsive.

No external provider is contacted.
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


async def test_slow_backfills_do_not_hold_db_pool_during_provider_wait(
    app_with_overrides: Any,
    auth_headers: dict[str, str],
) -> None:
    """Candidate A regression: provider waits must not reserve route-long DB connections.

    The shared default pool currently has max_size=10. We start 12 distinct backfills and require
    all 12 to reach the fake provider simultaneously. On the old route-level DBConn implementation,
    only the first 10 can reach provider I/O; the others block waiting for DB checkout, so this test
    fails before the health assertion.
    """
    from inalpha_data.connectors import _base as connectors_base

    count = 12
    connector = _BlockingConnector(expected_in_flight=count)
    connectors_base._REGISTRY["binance"] = connector

    transport = httpx.ASGITransport(app=app_with_overrides)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=5.0,
    ) as client:
        start = datetime(2026, 4, 1, tzinfo=UTC)
        end = start + timedelta(hours=1)
        tasks = [
            asyncio.create_task(
                client.post(
                    "/backfill/bars",
                    headers=auth_headers,
                    json={
                        "venue": "binance",
                        "symbol": f"LEASE-{idx}-{uuid4().hex[:8]}",
                        "timeframe": "1h",
                        "from_ts": start.isoformat(),
                        "to_ts": end.isoformat(),
                    },
                )
            )
            for idx in range(count)
        ]

        try:
            # Stronger than merely probing health: this proves >pool-size requests have already
            # passed their latest_bar_ts DB phase and reached provider I/O.
            await asyncio.wait_for(connector.all_entered.wait(), timeout=2.0)
            assert connector.entered == count

            # Non-DB control remains healthy.
            openapi = await asyncio.wait_for(client.get("/openapi.json"), timeout=0.5)
            assert openapi.status_code == 200

            # Most importantly, a DB-backed endpoint still gets a connection while all 12 provider
            # calls remain deliberately blocked.
            health = await asyncio.wait_for(client.get("/health"), timeout=0.5)
            assert health.status_code == 200
            assert health.json()["db"] == "ok"
        finally:
            connector.release.set()

        responses = await asyncio.gather(*tasks)

    assert all(r.status_code == 200 for r in responses)
