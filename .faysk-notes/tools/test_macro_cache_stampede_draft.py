"""Contributor-only diagnostic for issue #107 H8 (macro cache stampede).

This is NOT an upstream regression test yet. It documents current behavior before any
single-flight/coalescing change.

The test never calls data-service or FRED. It replaces FactorEngine._fetch_df with a blocking fake
and checks whether request-scoped engines coalesce the same live macro cache key while the first
fetch is still in flight.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pandas as pd

from inalpha_factor import engine as engine_mod
from inalpha_factor.config import get_factor_settings
from inalpha_factor.engine import FactorEngine


class _SharedFetchState:
    def __init__(self, expected_concurrent: int) -> None:
        self.expected_concurrent = expected_concurrent
        self.fetch_count = 0
        self.all_entered = asyncio.Event()
        self.release = asyncio.Event()


class _BlockingMacroEngine(FactorEngine):
    def __init__(self, state: _SharedFetchState) -> None:
        super().__init__(get_factor_settings())
        self._state = state

    async def _fetch_df(self, **_kwargs: object) -> pd.DataFrame:  # type: ignore[override]
        self._state.fetch_count += 1
        if self._state.fetch_count >= self._state.expected_concurrent:
            self._state.all_entered.set()

        await self._state.release.wait()

        idx = pd.DatetimeIndex(
            [
                datetime(2026, 9, 14, tzinfo=UTC),
                datetime(2026, 9, 15, tzinfo=UTC),
            ]
        )
        return pd.DataFrame({"close": [4.25, 4.20]}, index=idx)


async def test_macro_cache_works_after_population() -> None:
    """Control: sequential request-scoped engines share the populated module cache."""
    engine_mod._panel_cache.clear()
    state = _SharedFetchState(expected_concurrent=1)
    state.release.set()

    now = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    kwargs = {
        "from_ts": now - timedelta(days=30),
        "to_ts": now,
        "fresh": True,
        "timeframe": "1d",
    }

    try:
        first = _BlockingMacroEngine(state)
        second = _BlockingMacroEngine(state)

        await first._fetch_macro_series("DGS10", **kwargs)
        await second._fetch_macro_series("DGS10", **kwargs)

        assert state.fetch_count == 1
    finally:
        engine_mod._panel_cache.clear()


async def test_concurrent_cold_macro_cache_does_not_coalesce_currently() -> None:
    """Diagnostic: simultaneous misses start duplicate same-key fetches on current main.

    If a future single-flight fix is selected, this contributor diagnostic should be replaced by an
    upstream regression asserting the inverse property (one leader fetch, N-1 followers).
    """
    engine_mod._panel_cache.clear()
    callers = 6
    state = _SharedFetchState(expected_concurrent=callers)

    now = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
    kwargs = {
        "from_ts": now - timedelta(days=30),
        "to_ts": now,
        "fresh": True,
        "timeframe": "1d",
    }

    engines = [_BlockingMacroEngine(state) for _ in range(callers)]
    tasks = [
        asyncio.create_task(engine._fetch_macro_series("DGS10", **kwargs))
        for engine in engines
    ]

    try:
        # Current expected behavior: every request sees the cold cache before any caller can put the
        # result, so all six independently enter _fetch_df.
        await asyncio.wait_for(state.all_entered.wait(), timeout=1.0)
        assert state.fetch_count == callers
    finally:
        state.release.set()
        await asyncio.gather(*tasks)
        engine_mod._panel_cache.clear()
