"""Contributor-only pure unit diagnostic for issue #107 / H11.

Purpose
-------
Show whether the current module-level live factor cache coalesces *in-flight* misses for the same
score key. It does not contact data-service, a database, FRED, or any market-data provider.

Copy temporarily into ``services/factor/tests/`` and run there. Do not include this draft in the
upstream PR unless H11 becomes material and the final regression is intentionally selected.

The diagnostic disables macro so it isolates the whole-score cache itself. H8 has a separate macro
same-key diagnostic.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from inalpha_factor.config import get_factor_settings
from inalpha_factor.engine import FactorEngine
from inalpha_factor import engine as engine_mod

from .conftest import make_ohlcv


@dataclass
class _FetchProbe:
    expected: int
    entered: int = 0
    all_entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait(self) -> None:
        self.entered += 1
        if self.entered >= self.expected:
            self.all_entered.set()
        await self.release.wait()


class _BlockingEngine(FactorEngine):
    """Per-request engine whose main data fetch blocks on a shared probe."""

    def __init__(self, probe: _FetchProbe) -> None:
        settings = get_factor_settings().model_copy(
            update={
                "macro_enabled": False,
                "cache_ttl_s": 300,
            }
        )
        super().__init__(settings)
        self._probe = probe
        self.fetch_count = 0
        self._df = make_ohlcv(400)

    async def _fetch_df(self, **_kwargs: object) -> pd.DataFrame:  # type: ignore[override]
        self.fetch_count += 1
        await self._probe.wait()
        return self._df


def _kwargs() -> dict[str, object]:
    return {
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "as_of": None,
        "lookback_bars": 300,
        "horizon_bars": 5,
        "quantiles": 5,
        "factor_ids": None,
    }


async def test_concurrent_cold_same_score_key_does_not_coalesce_inflight_work() -> None:
    """Current-main diagnostic: six simultaneous cold callers all enter the data fetch.

    If the cache had in-flight single-flight semantics, only one engine would enter ``_fetch_df`` and
    the other five would await that same work. Current code performs a normal cache get before an
    await and only puts after computation, so all cold callers can miss together.
    """
    engine_mod._panel_cache.clear()

    count = 6
    probe = _FetchProbe(expected=count)
    engines = [_BlockingEngine(probe) for _ in range(count)]

    tasks = [
        asyncio.create_task(engine.score(**_kwargs()))  # type: ignore[arg-type]
        for engine in engines
    ]

    try:
        await asyncio.wait_for(probe.all_entered.wait(), timeout=2.0)
        assert probe.entered == count
        assert sum(engine.fetch_count for engine in engines) == count
    finally:
        probe.release.set()

    results = await asyncio.gather(*tasks)
    assert all(result["bars_used"] > 0 for result in results)

    # After the first wave has populated the shared cache, a new request-scoped engine with the same
    # key should hit it and therefore never enter its probe.
    warm_probe = _FetchProbe(expected=1)
    warm_engine = _BlockingEngine(warm_probe)
    warm_result = await asyncio.wait_for(
        warm_engine.score(**_kwargs()),  # type: ignore[arg-type]
        timeout=2.0,
    )

    assert warm_result["bars_used"] > 0
    assert warm_engine.fetch_count == 0
    assert warm_probe.entered == 0

    engine_mod._panel_cache.clear()
