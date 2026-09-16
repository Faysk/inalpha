"""Contributor-only data-service wrapper for Inalpha issue #107.

Run from ``services/data`` after copying this file there temporarily:

    ISSUE107_PROVIDER_DELAY_S=5 \
      uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 2

The real data-service lifespan still runs (DB pool, normal connector init, etc.), then this wrapper
replaces only the ``binance`` registry entry with a deterministic fake connector that sleeps.
No external market-data provider is contacted by the issue-107 load probes.

The wrapper also adds contributor-only diagnostics:

- ``X-Issue107-Worker-Pid`` on every response, to observe worker distribution;
- ``GET /__issue107/state`` with per-process fake-provider counters;
- explicit start/done/cancel/fail logs around fake provider I/O.

This file is contributor tooling. Do not commit it to the upstream PR as-is.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from inalpha_data.connectors import _base as connectors_base
from inalpha_data.main import app

_logger = logging.getLogger("issue107.slow_provider")
_original_lifespan = app.router.lifespan_context

_provider_active = 0
_provider_started = 0
_provider_completed = 0
_provider_cancelled = 0
_provider_failed = 0


class SlowIssue107Connector:
    """Fake OHLCV connector whose external-I/O phase is a deterministic asyncio sleep."""

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        limit: int = 1000,
    ) -> list[tuple[datetime, float, float, float, float, float]]:
        global _provider_active, _provider_cancelled, _provider_completed, _provider_failed
        global _provider_started

        del limit
        delay_s = float(os.environ.get("ISSUE107_PROVIDER_DELAY_S", "5"))
        pid = os.getpid()

        _provider_started += 1
        _provider_active += 1
        _logger.warning(
            "issue107_fake_provider_start pid=%s symbol=%s timeframe=%s delay_s=%s active=%s started=%s",
            pid,
            symbol,
            timeframe,
            delay_s,
            _provider_active,
            _provider_started,
        )

        try:
            await asyncio.sleep(delay_s)
            ts = since if since.tzinfo is not None else since.replace(tzinfo=UTC)
            _provider_completed += 1
            _logger.warning(
                "issue107_fake_provider_done pid=%s symbol=%s timeframe=%s active=%s completed=%s",
                pid,
                symbol,
                timeframe,
                _provider_active,
                _provider_completed,
            )
            return [(ts, 100.0, 101.0, 99.0, 100.5, 1000.0)]
        except asyncio.CancelledError:
            _provider_cancelled += 1
            _logger.warning(
                "issue107_fake_provider_cancelled pid=%s symbol=%s timeframe=%s active=%s cancelled=%s",
                pid,
                symbol,
                timeframe,
                _provider_active,
                _provider_cancelled,
            )
            raise
        except Exception:
            _provider_failed += 1
            _logger.exception(
                "issue107_fake_provider_failed pid=%s symbol=%s timeframe=%s active=%s failed=%s",
                pid,
                symbol,
                timeframe,
                _provider_active,
                _provider_failed,
            )
            raise
        finally:
            _provider_active -= 1

    async def close(self) -> None:
        return None


@app.middleware("http")
async def _issue107_worker_header(request: Request, call_next: Any) -> Any:
    """Expose the serving PID so two-worker request distribution is observable."""
    response = await call_next(request)
    response.headers["X-Issue107-Worker-Pid"] = str(os.getpid())
    return response


@app.get("/__issue107/state", include_in_schema=False)
async def _issue107_state() -> dict[str, int]:
    """Per-worker fake-provider counters; intentionally DB-free."""
    return {
        "pid": os.getpid(),
        "active": _provider_active,
        "started": _provider_started,
        "completed": _provider_completed,
        "cancelled": _provider_cancelled,
        "failed": _provider_failed,
    }


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
