"""Contributor-only live-runner-like data poll probe for Inalpha issue #107.

It reproduces the current ``LiveRunnerManager._fetch_latest_bar()`` network shape without requiring
promoted strategies, order execution, or real market-data providers:

    fresh=True
    -> POST /backfill/bars (best effort)
    -> GET /bars limit=5

Each simulated run creates its own short-lived ``httpx.AsyncClient`` for the poll, matching the
paper ``DataClient`` lifecycle used by ``_fetch_latest_bar``.

Recommended target is ``issue107_slow_data_app.py`` with every requested venue faked. The probe
refuses to run if a required venue is not listed in ``ISSUE107_FAKE_VENUES``.

Example exact one-worker diagnostic:

    ISSUE107_FAKE_VENUES=binance,baostock,yfinance ... data wrapper --workers 1

    uv run python issue107_runner_poll_probe.py \
      --data-url http://127.0.0.1:18001 --runs 8 --rounds 1 --stagger-ms 0

Compare with a controlled stagger without changing production code:

    uv run python issue107_runner_poll_probe.py --runs 8 --stagger-ms 100
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from inalpha_shared.config import get_settings


_TF_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
    "1wk": 604800,
    "1w": 604800,
}

# Mirrors the heterogeneous workload family named in #107 without touching real sources.
_RUN_PRESETS: tuple[tuple[str, str, str], ...] = (
    ("binance", "BTC/USDT", "1h"),
    ("binance", "BNB/USDT", "1h"),
    ("baostock", "sh.600000", "1h"),
    ("yfinance", "7203.T", "1h"),
    ("binance", "ETH/USDT", "1h"),
    ("binance", "SOL/USDT", "1h"),
    ("baostock", "sz.000001", "1h"),
    ("yfinance", "9984.T", "1h"),
)


@dataclass(frozen=True)
class SimRun:
    idx: int
    venue: str
    symbol: str
    timeframe: str


@dataclass
class PollResult:
    run: SimRun
    latency_s: float
    backfill_status: int | None = None
    backfill_error: str | None = None
    backfill_code: str | None = None
    bars_status: int | None = None
    bars_error: str | None = None
    bars_code: str | None = None
    bars_count: int | None = None


def _token() -> str:
    settings = get_settings()
    return jwt.encode(
        {
            "sub": "issue107-runner-poll-probe",
            "exp": int(time.time()) + 3600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except Exception:
        return None
    return body.get("code") if isinstance(body, dict) else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


async def _state(data_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=data_url, timeout=2.0, trust_env=False) as client:
        response = await client.get("/__issue107/state")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"unexpected state payload: {body!r}")
        return body


def _delta(before: dict[str, Any], after: dict[str, Any], key: str) -> int | None:
    if key not in before and key not in after:
        return None
    return int(after.get(key, 0)) - int(before.get(key, 0))


async def _poll_once(
    *,
    data_url: str,
    token: str,
    run: SimRun,
    timeout_s: float,
    stagger_s: float,
) -> PollResult:
    if stagger_s > 0:
        await asyncio.sleep(run.idx * stagger_s)

    now = datetime.now(UTC)
    tf_s = _TF_SECONDS[run.timeframe]
    lookback_s = max(tf_s * 5, 7200)
    from_ts = now - timedelta(seconds=lookback_s)

    t0 = time.perf_counter()
    result = PollResult(run=run, latency_s=0.0)

    # One client per simulated _fetch_latest_bar invocation: this matches paper's current
    # ``async with DataClient(...)`` lifecycle rather than giving the probe an unrealistic global pool.
    async with httpx.AsyncClient(
        base_url=data_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(timeout_s),
        trust_env=False,
    ) as client:
        try:
            backfill = await client.post(
                "/backfill/bars",
                headers={"X-Trace-Id": f"issue107-runner-bf-{run.idx}-{time.time_ns()}"},
                json={
                    "venue": run.venue,
                    "symbol": run.symbol,
                    "timeframe": run.timeframe,
                    "from_ts": from_ts.isoformat(),
                    "to_ts": now.isoformat(),
                },
            )
            result.backfill_status = backfill.status_code
            result.backfill_code = _code(backfill)
        except httpx.RequestError as exc:
            # Current paper get_bars(fresh=True) treats backfill failure as best-effort and still
            # performs the DB read. Preserve that behavior here.
            result.backfill_error = type(exc).__name__

        try:
            bars = await client.get(
                "/bars",
                headers={"X-Trace-Id": f"issue107-runner-bars-{run.idx}-{time.time_ns()}"},
                params={
                    "venue": run.venue,
                    "symbol": run.symbol,
                    "timeframe": run.timeframe,
                    "from_ts": from_ts.isoformat(),
                    "to_ts": now.isoformat(),
                    "limit": 5,
                },
            )
            result.bars_status = bars.status_code
            result.bars_code = _code(bars)
            if bars.status_code < 400:
                payload = bars.json()
                result.bars_count = len(payload) if isinstance(payload, list) else None
        except httpx.RequestError as exc:
            result.bars_error = type(exc).__name__

    result.latency_s = time.perf_counter() - t0
    return result


def _build_runs(count: int) -> list[SimRun]:
    if count < 1:
        raise ValueError("--runs must be >= 1")
    out: list[SimRun] = []
    for idx in range(count):
        venue, symbol, timeframe = _RUN_PRESETS[idx % len(_RUN_PRESETS)]
        # Make cycles above the preset count unique at the DB key level without changing venue shape.
        cycle = idx // len(_RUN_PRESETS)
        if cycle:
            symbol = f"{symbol}-R{cycle}"
        out.append(SimRun(idx=idx, venue=venue, symbol=symbol, timeframe=timeframe))
    return out


def _print_results(round_no: int, results: list[PollResult]) -> None:
    latencies = [r.latency_s for r in results]
    backfill_status = Counter(str(r.backfill_status) for r in results if r.backfill_status is not None)
    backfill_errors = Counter(r.backfill_error for r in results if r.backfill_error)
    backfill_codes = Counter(r.backfill_code for r in results if r.backfill_code)
    bars_status = Counter(str(r.bars_status) for r in results if r.bars_status is not None)
    bars_errors = Counter(r.bars_error for r in results if r.bars_error)
    bars_codes = Counter(r.bars_code for r in results if r.bars_code)
    bars_counts = Counter(r.bars_count for r in results if r.bars_count is not None)

    print(f"\n[round_{round_no}]")
    print(f"backfill_status={dict(backfill_status)}")
    print(f"backfill_errors={dict(backfill_errors)}")
    print(f"backfill_codes={dict(backfill_codes)}")
    print(f"bars_status={dict(bars_status)}")
    print(f"bars_errors={dict(bars_errors)}")
    print(f"bars_codes={dict(bars_codes)}")
    print(f"bars_count={dict(bars_counts)}")
    if latencies:
        p50 = _percentile(latencies, 0.50)
        p95 = _percentile(latencies, 0.95)
        p99 = _percentile(latencies, 0.99)
        assert p50 is not None and p95 is not None and p99 is not None
        print(
            f"latency_s p50={p50:.3f} p95={p95:.3f} p99={p99:.3f} "
            f"max={max(latencies):.3f}"
        )


def _print_state_delta(before: dict[str, Any], after: dict[str, Any]) -> None:
    print("\n[data_state_delta]")
    print(f"pid_before={before.get('pid')} pid_after={after.get('pid')}")
    if before.get("pid") != after.get("pid"):
        print("WARNING: state sampled different workers; exact process deltas are invalid")

    for key in (
        "http_post_backfill_bars_total",
        "http_get_bars_total",
        "started",
        "completed",
        "failed",
        "venue_binance_started",
        "venue_baostock_started",
        "venue_yfinance_started",
        "pool_requests_num",
        "pool_requests_queued",
        "pool_requests_wait_ms",
        "pool_requests_errors",
        "pool_usage_ms",
    ):
        value = _delta(before, after, key)
        if value is not None:
            print(f"{key}_delta={value}")


def _required_venues(runs: list[SimRun]) -> set[str]:
    return {run.venue for run in runs}


async def _run(args: argparse.Namespace) -> None:
    runs = _build_runs(args.runs)
    required = _required_venues(runs)

    before = await _state(args.data_url)
    fake = {item.strip() for item in str(before.get("fake_venues", "")).split(",") if item.strip()}
    missing = required - fake
    if missing:
        raise RuntimeError(
            "unsafe runner probe: not all requested venues are faked; "
            f"missing={sorted(missing)} configured={sorted(fake)}"
        )

    print(
        "configuration "
        f"runs={args.runs} rounds={args.rounds} stagger_ms={args.stagger_ms} "
        f"round_interval={args.round_interval}s venues={sorted(required)}"
    )

    token = _token()
    for round_idx in range(args.rounds):
        results = await asyncio.gather(
            *[
                _poll_once(
                    data_url=args.data_url,
                    token=token,
                    run=run,
                    timeout_s=args.timeout,
                    stagger_s=args.stagger_ms / 1000.0,
                )
                for run in runs
            ]
        )
        _print_results(round_idx + 1, results)
        if round_idx + 1 < args.rounds:
            await asyncio.sleep(args.round_interval)

    after = await _state(args.data_url)
    _print_state_delta(before, after)

    print("\n[interpretation]")
    print(
        "- stagger_ms=0 intentionally creates aligned wakeups; compare against the same run count "
        "with a small stagger to test H6 without modifying live_runner."
    )
    print(
        "- this reproduces the network/freshness shape of _fetch_latest_bar, not strategy/risk/order "
        "execution; actual paper restart/warmup remains a later integration scenario."
    )
    print(
        "- exact state deltas require one data worker; use PID/log evidence for two-worker confirmation."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-url", default="http://127.0.0.1:18001")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--stagger-ms", type=float, default=0.0)
    parser.add_argument("--round-interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


if __name__ == "__main__":
    asyncio.run(_run(_parser().parse_args()))
