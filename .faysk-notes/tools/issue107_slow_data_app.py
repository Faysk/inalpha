"""Contributor-only data-service wrapper for Inalpha issue #107.

Run from ``services/data`` after copying this file there temporarily:

    ISSUE107_PROVIDER_DELAY_S=5 \
      uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 2

The real data-service lifespan still runs (DB pool, normal connector init, etc.), then this wrapper
replaces only the ``binance`` registry entry with a deterministic fake connector that sleeps.
No external market-data provider is contacted by the issue-107 load probe.

This file is contributor tooling. Do not commit it to the upstream PR as-is.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from inalpha_data.connectors import _base as connectors_base
from inalpha_data.main import app

_logger = logging.getLogger("issue107.slow_provider")
_original_lifespan = app.router.lifespan_context


class SlowIssue107Connector:
    """Fake OHLCV connector whose external-I/O phase is a deterministic asyncio sleep."""

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        limit: int = 1000,
    ) -> list[tuple[datetime, float, float, float, float, float]]:
        del limit
        delay_s = float(os.environ.get("ISSUE107_PROVIDER_DELAY_S", "5"))
        pid = os.getpid()
        _logger.warning(
            "issue107_fake_provider_start pid=%s symbol=%s timeframe=%s delay_s=%s",
            pid,
            symbol,
            timeframe,
            delay_s,
        )
        await asyncio.sleep(delay_s)
        ts = since if since.tzinfo is not None else since.replace(tzinfo=UTC)
        _logger.warning(
            "issue107_fake_provider_done pid=%s symbol=%s timeframe=%s",
            pid,
            symbol,
            timeframe,
        )
        return [(ts, 100.0, 101.0, 99.0, 100.5, 1000.0)]

    async def close(self) -> None:
        return None


@asynccontextmanager
async def _issue107_lifespan(app_obj: Any):  # type: ignore[no-untyped-def]
    """Run normal service startup, then swap binance for the deterministic local fake."""
    async with _original_lifespan(app_obj):
        connectors_base._REGISTRY["binance"] = SlowIssue107Connector()
        _logger.warning(
            "issue107_fake_provider_installed pid=%s delay_s=%s",
            os.getpid(),
            os.environ.get("ISSUE107_PROVIDER_DELAY_S", "5"),
        )
        yield


app.router.lifespan_context = _issue107_lifespan
