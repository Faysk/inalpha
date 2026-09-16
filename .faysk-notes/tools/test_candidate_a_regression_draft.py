"""Contributor-only post-fix regression draft for Inalpha issue #107 / Candidate A.

This test is NOT valid for the unmodified baseline: it is intentionally written with the expected
behavior after DB lease narrowing. Keep it on the notes branch until Candidate A is selected and
implemented.

Core property:

    more slow provider calls than a deliberately small DB pool can be in flight
    while an unrelated DB-backed endpoint remains responsive.

The test controls its own pool size (2) instead of relying on the repository-wide default (10), so
it will keep detecting a future regression even if the normal pool default is tuned later.

No external provider is contacted. The production constituent snapshot scheduler is also forced
inactive inside this test fixture so contributor/local environment settings cannot create unrelated
background provider traffic.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
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

    async def close(self) -> None:
        return None


@pytest.fixture
async def app_with_two_connection_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Any]:
    """Run real data lifespan with pool max_size=2 and no background provider scheduler.

    The production fix must remain correct independent of ordinary pool-size tuning. A tiny pool
    also makes the before/after property deterministic with only four fake provider requests.
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

    # main.lifespan resolves these module globals at runtime, so patch before entering lifespan.
    monkeypatch.setattr(main_mod, "init_pool", _init_small_pool)
    monkeypatch.setattr(main_mod, "parse_indices", lambda _raw: [])

    connector = _BlockingConnector(expected_in_flight=4)
    async with main_mod.app.router.lifespan_context(main_mod.app):
        connectors_base._REGISTRY["binance"] = connector
        main_mod.app.state.issue107_blocking_connector = connector
        yield main_mod.app

    main_mod.app.dependency_overrides.clear()


async def test_slow_backfills_do_not_hold_db_pool_during_provider_wait(
    app_with_two_connection_pool: Any,
    auth_headers: dict[str, str],
) -> None:
    """Candidate A regression: provider waits must not reserve request-long DB connections.

    Test pool max_size=2. Four distinct backfills must all finish their short latest-bar DB phase and
    reach fake provider I/O simultaneously. On the old route-level DBConn implementation, only the
    first two can reach provider I/O; the other two block on DB checkout, so this test fails at the
    ``all_entered`` wait before the health assertion.
    """
    connector = app_with_two_connection_pool.state.issue107_blocking_connector

    transport = httpx.ASGITransport(app=app_with_two_connection_pool)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=5.0,
    ) as client:
        start = datetime(2026, 4, 1, tzinfo=UTC)
        end = start + timedelta(hours=1)
        count = 4
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
            # Stronger than merely probing health: >pool-size requests have already completed their
            # latest_bar_ts DB phase and reached provider I/O while the provider remains blocked.
            await asyncio.wait_for(connector.all_entered.wait(), timeout=5.0)
            assert connector.entered == count

            # Non-DB control remains healthy.
            openapi = await asyncio.wait_for(client.get("/openapi.json"), timeout=1.0)
            assert openapi.status_code == 200

            # Most importantly, a DB-backed endpoint still gets a connection while all four provider
            # calls remain deliberately blocked.
            health = await asyncio.wait_for(client.get("/health"), timeout=1.0)
            assert health.status_code == 200
            assert health.json()["db"] == "ok"
        finally:
            connector.release.set()

        responses = await asyncio.gather(*tasks)

    assert all(r.status_code == 200 for r in responses)
