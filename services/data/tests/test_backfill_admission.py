"""Backfill concurrency and DB-lease regression tests."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from inalpha_data.api import backfill as backfill_api
from inalpha_data.schemas import BackfillRequest


class _Settings:
    backfill_max_concurrency = 2


@pytest.fixture(autouse=True)
def _reset_backfill_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backfill_api, "_BACKFILL_GATE", None)
    monkeypatch.setattr(backfill_api, "_BACKFILL_GATE_LIMIT", None)
    backfill_api._BACKFILL_FETCH_TASKS.clear()


def _request(symbol: str) -> BackfillRequest:
    start = datetime(2026, 9, 18, tzinfo=UTC)
    return BackfillRequest(
        venue="binance",
        symbol=symbol,
        timeframe="1d",
        from_ts=start,
        to_ts=start + timedelta(hours=12),
    )


@pytest.mark.asyncio
async def test_backfill_releases_db_connection_during_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_depth = [0]
    events: list[str] = []
    fake_conn = object()

    @asynccontextmanager
    async def fake_get_conn() -> AsyncIterator[Any]:
        assert lease_depth[0] == 0
        lease_depth[0] += 1
        events.append("db_enter")
        try:
            yield fake_conn
        finally:
            lease_depth[0] -= 1
            events.append("db_exit")

    async def fake_latest_bar_ts(*args: Any, **kwargs: Any) -> None:
        del kwargs
        assert args[0] is fake_conn
        assert lease_depth[0] == 1
        events.append("latest")
        return None

    async def fake_insert_bars(*args: Any, **kwargs: Any) -> int:
        del kwargs
        assert args[0] is fake_conn
        assert lease_depth[0] == 1
        events.append("insert")
        return len(args[-1])

    class Connector:
        async def fetch_bars(
            self,
            symbol: str,
            timeframe: str,
            since: datetime,
            limit: int = 1000,
        ) -> list[tuple[datetime, float, float, float, float, float]]:
            del symbol, timeframe, limit
            assert lease_depth[0] == 0
            events.append("provider")
            return [(since, 100.0, 101.0, 99.0, 100.5, 1000.0)]

    monkeypatch.setattr(backfill_api, "get_data_settings", lambda: _Settings())
    monkeypatch.setattr(backfill_api, "get_conn", fake_get_conn)
    monkeypatch.setattr(backfill_api, "latest_bar_ts", fake_latest_bar_ts)
    monkeypatch.setattr(backfill_api, "insert_bars", fake_insert_bars)
    monkeypatch.setattr(backfill_api, "get_connector_for_venue", lambda _venue: Connector())

    response = await backfill_api.backfill_bars(
        _request("LEASE/USDT"),
        _user=object(),  # type: ignore[arg-type]
    )

    assert response.bars_fetched == 1
    assert response.bars_inserted == 1
    assert lease_depth[0] == 0
    assert events == [
        "db_enter",
        "latest",
        "db_exit",
        "provider",
        "db_enter",
        "insert",
        "db_exit",
    ]


@pytest.mark.asyncio
async def test_backfill_gate_caps_provider_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = object()
    active = 0
    max_active = 0

    @asynccontextmanager
    async def fake_get_conn() -> AsyncIterator[Any]:
        yield fake_conn

    async def fake_latest_bar_ts(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    async def fake_insert_bars(*args: Any, **kwargs: Any) -> int:
        del kwargs
        return len(args[-1])

    class Connector:
        async def fetch_bars(
            self,
            symbol: str,
            timeframe: str,
            since: datetime,
            limit: int = 1000,
        ) -> list[tuple[datetime, float, float, float, float, float]]:
            nonlocal active, max_active
            del symbol, timeframe, limit
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.03)
                return [(since, 100.0, 101.0, 99.0, 100.5, 1000.0)]
            finally:
                active -= 1

    connector = Connector()
    monkeypatch.setattr(backfill_api, "get_data_settings", lambda: _Settings())
    monkeypatch.setattr(backfill_api, "get_conn", fake_get_conn)
    monkeypatch.setattr(backfill_api, "latest_bar_ts", fake_latest_bar_ts)
    monkeypatch.setattr(backfill_api, "insert_bars", fake_insert_bars)
    monkeypatch.setattr(backfill_api, "get_connector_for_venue", lambda _venue: connector)

    responses = await asyncio.gather(
        *[
            backfill_api.backfill_bars(
                _request(f"CAP-{i}/USDT"),
                _user=object(),  # type: ignore[arg-type]
            )
            for i in range(8)
        ]
    )

    assert max_active == 2
    assert all(response.bars_fetched == 1 for response in responses)


@pytest.mark.asyncio
async def test_backfill_gate_keeps_permit_until_thread_work_finishes_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = object()
    release = threading.Event()
    lock = threading.Lock()
    thread_active = 0
    thread_started = 0
    thread_max = 0

    @asynccontextmanager
    async def fake_get_conn() -> AsyncIterator[Any]:
        yield fake_conn

    async def fake_latest_bar_ts(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    async def fake_insert_bars(*args: Any, **kwargs: Any) -> int:
        del kwargs
        return len(args[-1])

    def blocking_fetch() -> None:
        nonlocal thread_active, thread_started, thread_max
        with lock:
            thread_active += 1
            thread_started += 1
            thread_max = max(thread_max, thread_active)
        try:
            release.wait(timeout=2)
        finally:
            with lock:
                thread_active -= 1

    class Connector:
        async def fetch_bars(
            self,
            symbol: str,
            timeframe: str,
            since: datetime,
            limit: int = 1000,
        ) -> list[tuple[datetime, float, float, float, float, float]]:
            del symbol, timeframe, limit
            await asyncio.to_thread(blocking_fetch)
            return [(since, 100.0, 101.0, 99.0, 100.5, 1000.0)]

    connector = Connector()
    monkeypatch.setattr(backfill_api, "get_data_settings", lambda: _Settings())
    monkeypatch.setattr(backfill_api, "get_conn", fake_get_conn)
    monkeypatch.setattr(backfill_api, "latest_bar_ts", fake_latest_bar_ts)
    monkeypatch.setattr(backfill_api, "insert_bars", fake_insert_bars)
    monkeypatch.setattr(backfill_api, "get_connector_for_venue", lambda _venue: connector)

    first = [
        asyncio.create_task(
            backfill_api.backfill_bars(
                _request(f"CANCEL-A-{i}/USDT"),
                _user=object(),  # type: ignore[arg-type]
            )
        )
        for i in range(2)
    ]

    deadline = asyncio.get_running_loop().time() + 1
    while True:
        with lock:
            started = thread_started
        if started == 2:
            break
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"first wave did not start two threads; started={started}")
        await asyncio.sleep(0.01)

    for task in first:
        task.cancel()
    await asyncio.gather(*first, return_exceptions=True)

    second = [
        asyncio.create_task(
            backfill_api.backfill_bars(
                _request(f"CANCEL-B-{i}/USDT"),
                _user=object(),  # type: ignore[arg-type]
            )
        )
        for i in range(2)
    ]

    await asyncio.sleep(0.05)
    with lock:
        assert thread_started == 2
        assert thread_max == 2

    release.set()
    responses = await asyncio.gather(*second)
    assert all(response.bars_fetched == 1 for response in responses)
    assert thread_max == 2


@pytest.mark.asyncio
async def test_cancelled_request_waiting_for_gate_does_not_run_provider_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = object()
    release = asyncio.Event()
    started: list[str] = []

    @asynccontextmanager
    async def fake_get_conn() -> AsyncIterator[Any]:
        yield fake_conn

    async def fake_latest_bar_ts(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    async def fake_insert_bars(*args: Any, **kwargs: Any) -> int:
        del kwargs
        return len(args[-1])

    class Connector:
        async def fetch_bars(
            self,
            symbol: str,
            timeframe: str,
            since: datetime,
            limit: int = 1000,
        ) -> list[tuple[datetime, float, float, float, float, float]]:
            del timeframe, limit
            started.append(symbol)
            await release.wait()
            return [(since, 100.0, 101.0, 99.0, 100.5, 1000.0)]

    connector = Connector()
    monkeypatch.setattr(backfill_api, "get_data_settings", lambda: _Settings())
    monkeypatch.setattr(backfill_api, "get_conn", fake_get_conn)
    monkeypatch.setattr(backfill_api, "latest_bar_ts", fake_latest_bar_ts)
    monkeypatch.setattr(backfill_api, "insert_bars", fake_insert_bars)
    monkeypatch.setattr(backfill_api, "get_connector_for_venue", lambda _venue: connector)

    holders = [
        asyncio.create_task(
            backfill_api.backfill_bars(
                _request(f"HOLDER-{i}/USDT"),
                _user=object(),  # type: ignore[arg-type]
            )
        )
        for i in range(2)
    ]

    deadline = asyncio.get_running_loop().time() + 1
    while len(started) < 2:
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"holders did not acquire gate; started={started}")
        await asyncio.sleep(0.01)

    queued = asyncio.create_task(
        backfill_api.backfill_bars(
            _request("QUEUED-CANCEL/USDT"),
            _user=object(),  # type: ignore[arg-type]
        )
    )
    await asyncio.sleep(0.03)
    queued.cancel()
    await asyncio.gather(queued, return_exceptions=True)

    release.set()
    await asyncio.gather(*holders)
    await asyncio.sleep(0.05)

    assert "QUEUED-CANCEL/USDT" not in started


@pytest.mark.asyncio
async def test_backfill_provider_failure_does_not_leave_db_lease_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_depth = [0]
    fake_conn = object()

    @asynccontextmanager
    async def fake_get_conn() -> AsyncIterator[Any]:
        lease_depth[0] += 1
        try:
            yield fake_conn
        finally:
            lease_depth[0] -= 1

    async def fake_latest_bar_ts(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    class FailingConnector:
        async def fetch_bars(
            self,
            symbol: str,
            timeframe: str,
            since: datetime,
            limit: int = 1000,
        ) -> list[tuple[datetime, float, float, float, float, float]]:
            del symbol, timeframe, since, limit
            assert lease_depth[0] == 0
            raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(backfill_api, "get_data_settings", lambda: _Settings())
    monkeypatch.setattr(backfill_api, "get_conn", fake_get_conn)
    monkeypatch.setattr(backfill_api, "latest_bar_ts", fake_latest_bar_ts)
    monkeypatch.setattr(
        backfill_api,
        "get_connector_for_venue",
        lambda _venue: FailingConnector(),
    )

    with pytest.raises(backfill_api.BarsUpstreamUnavailableError):
        await backfill_api.backfill_bars(
            _request("FAIL/USDT"),
            _user=object(),  # type: ignore[arg-type]
        )

    assert lease_depth[0] == 0
