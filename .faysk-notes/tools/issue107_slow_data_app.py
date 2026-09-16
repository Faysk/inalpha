"""Contributor-only data-service wrapper for Inalpha issue #107.

Run from ``services/data`` after copying this file there temporarily.

Simple backfill/DB isolation run (fake Binance only):

    ISSUE107_FAKE_VENUES=binance ISSUE107_PROVIDER_MODE=async ISSUE107_PROVIDER_DELAY_S=5 \
      uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 2

Safe factor-macro run (fake both the main price venue and FRED; no provider traffic):

    ISSUE107_FAKE_VENUES=binance,fred ISSUE107_FAKE_BARS_PER_FETCH=1000 \
      ISSUE107_PROVIDER_MODE=async ISSUE107_PROVIDER_DELAY_S=0.25 \
      uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 2

Thread-backed fake provider (models connectors that wrap a synchronous SDK with ``to_thread``):

    ISSUE107_PROVIDER_MODE=thread ISSUE107_PROVIDER_DELAY_S=5 \
      uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 1

The real data-service lifespan still runs (DB pool, normal connector init, etc.), then this wrapper
replaces only the venues listed in ``ISSUE107_FAKE_VENUES`` with deterministic local connectors.
The default is ``binance``. A listed venue is installed even when its real connector was skipped at
startup (for example ``fred`` without an API key), so macro-capacity tests never require real keys.

No external market-data provider is contacted for a venue that has been replaced by the fake.

The wrapper also adds contributor-only diagnostics:

- ``X-Issue107-Worker-Pid`` on every response, to observe worker distribution;
- ``GET /__issue107/state`` with per-process fake-provider counters;
- Psycopg pool ``get_stats()`` values flattened into the DB-free state response;
- explicit start/done/cancel/fail logs around the async provider waiter;
- separate sync-thread counters in ``thread`` mode, so cancellation of the asyncio waiter is not
  confused with stopping an already-running synchronous worker function.

This file is contributor tooling. Do not commit it to the upstream PR as-is.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
import inalpha_shared.db as shared_db

from inalpha_data.connectors import _base as connectors_base
from inalpha_data.main import app

_logger = logging.getLogger("issue107.slow_provider")
_original_lifespan = app.router.lifespan_context

_provider_active = 0
_provider_started = 0
_provider_completed = 0
_provider_cancelled = 0
_provider_failed = 0

_thread_lock = threading.Lock()
_thread_active = 0
_thread_started = 0
_thread_completed = 0

# Enough for the venues/scenarios exercised by the issue-107 harness. The production route still
# validates each venue's real supported timeframe table before this fake is called.
_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
    "1wk": 604800,
    "1mo": 2_592_000,
    "1q": 7_776_000,
    "1y": 31_536_000,
}


def _fake_venues() -> list[str]:
    raw = os.environ.get("ISSUE107_FAKE_VENUES", "binance")
    seen: set[str] = set()
    out: list[str] = []
    for item in raw.split(","):
        venue = item.strip().lower()
        if venue and venue not in seen:
            seen.add(venue)
            out.append(venue)
    return out or ["binance"]


def _sync_sleep(delay_s: float, pid: int, venue: str, symbol: str) -> None:
    """Blocking function used by thread mode.

    Once this function has started in a worker thread, cancelling the asyncio ``to_thread`` waiter
    cannot stop ``time.sleep``. These counters let the diagnostic observe that distinction.
    """
    global _thread_active, _thread_completed, _thread_started

    with _thread_lock:
        _thread_started += 1
        _thread_active += 1
        active = _thread_active
        started = _thread_started
    _logger.warning(
        "issue107_fake_thread_start pid=%s venue=%s symbol=%s delay_s=%s thread_active=%s thread_started=%s",
        pid,
        venue,
        symbol,
        delay_s,
        active,
        started,
    )

    try:
        time.sleep(delay_s)
    finally:
        with _thread_lock:
            _thread_active -= 1
            _thread_completed += 1
            active = _thread_active
            completed = _thread_completed
        _logger.warning(
            "issue107_fake_thread_done pid=%s venue=%s symbol=%s thread_active=%s thread_completed=%s",
            pid,
            venue,
            symbol,
            active,
            completed,
        )


def _thread_state() -> dict[str, int]:
    with _thread_lock:
        return {
            "thread_active": _thread_active,
            "thread_started": _thread_started,
            "thread_completed": _thread_completed,
        }


def _pool_state() -> dict[str, int]:
    """Flatten Psycopg pool stats without acquiring a DB connection.

    This intentionally reads the shared module's private global pool because this is contributor-only
    diagnostics. Production code should not depend on ``inalpha_shared.db._pool``.
    """
    pool = shared_db._pool  # type: ignore[attr-defined]
    if pool is None:
        return {"pool_initialized": 0}

    stats = pool.get_stats()
    out: dict[str, int] = {"pool_initialized": 1}
    for key, value in stats.items():
        out[f"pool_{key}"] = int(value)
    return out


class SlowIssue107Connector:
    """Fake OHLCV connector with controllable async or sync-thread provider latency."""

    def __init__(self, venue: str) -> None:
        self._venue = venue

    async def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        since: datetime,
        limit: int = 1000,
    ) -> list[tuple[datetime, float, float, float, float, float]]:
        global _provider_active, _provider_cancelled, _provider_completed, _provider_failed
        global _provider_started

        delay_s = float(os.environ.get("ISSUE107_PROVIDER_DELAY_S", "5"))
        mode = os.environ.get("ISSUE107_PROVIDER_MODE", "async").strip().lower()
        if mode not in {"async", "thread"}:
            raise RuntimeError(
                f"invalid ISSUE107_PROVIDER_MODE={mode!r}; expected 'async' or 'thread'"
            )
        pid = os.getpid()

        _provider_started += 1
        _provider_active += 1
        _logger.warning(
            "issue107_fake_provider_start pid=%s venue=%s symbol=%s timeframe=%s mode=%s delay_s=%s active=%s started=%s",
            pid,
            self._venue,
            symbol,
            timeframe,
            mode,
            delay_s,
            _provider_active,
            _provider_started,
        )

        try:
            if mode == "thread":
                await asyncio.to_thread(_sync_sleep, delay_s, pid, self._venue, symbol)
            else:
                await asyncio.sleep(delay_s)

            step_s = _TIMEFRAME_SECONDS.get(timeframe)
            if step_s is None:
                raise RuntimeError(f"issue107 fake has no step mapping for timeframe {timeframe!r}")

            configured = int(os.environ.get("ISSUE107_FAKE_BARS_PER_FETCH", "1"))
            count = max(1, min(limit, configured))
            start = since if since.tzinfo is not None else since.replace(tzinfo=UTC)
            rows = [
                (
                    start + timedelta(seconds=step_s * idx),
                    100.0 + idx * 0.01,
                    101.0 + idx * 0.01,
                    99.0 + idx * 0.01,
                    100.5 + idx * 0.01,
                    1000.0 + idx,
                )
                for idx in range(count)
            ]

            _provider_completed += 1
            _logger.warning(
                "issue107_fake_provider_done pid=%s venue=%s symbol=%s timeframe=%s mode=%s active=%s completed=%s rows=%s",
                pid,
                self._venue,
                symbol,
                timeframe,
                mode,
                _provider_active,
                _provider_completed,
                len(rows),
            )
            return rows
        except asyncio.CancelledError:
            _provider_cancelled += 1
            _logger.warning(
                "issue107_fake_provider_cancelled pid=%s venue=%s symbol=%s timeframe=%s mode=%s active=%s cancelled=%s",
                pid,
                self._venue,
                symbol,
                timeframe,
                mode,
                _provider_active,
                _provider_cancelled,
            )
            raise
        except Exception:
            _provider_failed += 1
            _logger.exception(
                "issue107_fake_provider_failed pid=%s venue=%s symbol=%s timeframe=%s mode=%s active=%s failed=%s",
                pid,
                self._venue,
                symbol,
                timeframe,
                mode,
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
async def _issue107_state() -> dict[str, int | str]:
    """Per-worker provider/thread/pool state without acquiring a DB connection."""
    return {
        "pid": os.getpid(),
        "mode": os.environ.get("ISSUE107_PROVIDER_MODE", "async").strip().lower(),
        "fake_venues": ",".join(_fake_venues()),
        "fake_bars_per_fetch": int(os.environ.get("ISSUE107_FAKE_BARS_PER_FETCH", "1")),
        "active": _provider_active,
        "started": _provider_started,
        "completed": _provider_completed,
        "cancelled": _provider_cancelled,
        "failed": _provider_failed,
        **_thread_state(),
        **_pool_state(),
    }


@asynccontextmanager
async def _issue107_lifespan(app_obj: Any):  # type: ignore[no-untyped-def]
    """Run normal startup, then replace selected venue registry entries with local fakes."""
    async with _original_lifespan(app_obj):
        venues = _fake_venues()
        for venue in venues:
            connectors_base._REGISTRY[venue] = SlowIssue107Connector(venue)
        _logger.warning(
            "issue107_fake_provider_installed pid=%s venues=%s mode=%s delay_s=%s bars_per_fetch=%s",
            os.getpid(),
            venues,
            os.environ.get("ISSUE107_PROVIDER_MODE", "async"),
            os.environ.get("ISSUE107_PROVIDER_DELAY_S", "5"),
            os.environ.get("ISSUE107_FAKE_BARS_PER_FETCH", "1"),
        )
        yield


app.router.lifespan_context = _issue107_lifespan
