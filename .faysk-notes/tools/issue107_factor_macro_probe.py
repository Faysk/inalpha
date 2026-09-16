"""Contributor-only full-stack macro load probe for Inalpha issue #107.

This script targets:

- factor-service on localhost (normally one worker), and
- ``issue107_slow_data_app.py`` with fake ``binance,fred`` venues.

No real market-data provider should be contacted when the data wrapper is configured correctly.

Recommended exact-count diagnostic topology:

    data:   1 worker, ISSUE107_FAKE_VENUES=binance,fred, ISSUE107_FAKE_BARS_PER_FETCH=1000
    factor: 1 worker, DATA_SERVICE_URL=http://127.0.0.1:18001

Restart factor before a cold run so its module-level caches are empty.

Example:

    uv run python issue107_factor_macro_probe.py \
      --factor-url http://127.0.0.1:18004 \
      --data-url http://127.0.0.1:18001 \
      --concurrency 6 \
      --symbol-mode same \
      --factor-set macro

The script runs two waves with the same keys:

1. cold concurrent wave;
2. immediate warm wave.

It records factor status/latency plus exact one-worker data HTTP, fake-provider and pool-state deltas.
``same`` symbol mode exercises both full-score and macro same-key stampede potential. ``unique``
mode gives each factor request a different main price key while still sharing macro/date keys.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from inalpha_shared.config import get_settings


@dataclass
class ScoreResult:
    latency_s: float
    status: int | None = None
    error_type: str | None = None
    code: str | None = None
    bars_used: int | None = None
    factors: int | None = None


def _token() -> str:
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "issue107-factor-macro-probe",
            "email": "issue107-factor@local.invalid",
            "iat": now,
            "exp": now + 3600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


def _machine_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except Exception:
        return None
    return body.get("code") if isinstance(body, dict) else None


async def _data_state(data_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=data_url, timeout=2.0, trust_env=False) as client:
        response = await client.get("/__issue107/state")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"unexpected data state response: {body!r}")
        return body


async def _macro_ids(factor_url: str, token: str) -> list[str]:
    async with httpx.AsyncClient(base_url=factor_url, timeout=10.0, trust_env=False) as client:
        response = await client.get(
            "/catalog",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        body = response.json()
    factors = body.get("factors", []) if isinstance(body, dict) else []
    out = [
        str(item["factor_id"])
        for item in factors
        if isinstance(item, dict)
        and item.get("source") == "macro"
        and item.get("available", True)
        and item.get("factor_id")
    ]
    if not out:
        raise RuntimeError("factor catalog returned no available macro factor ids")
    return out


async def _score_one(
    client: httpx.AsyncClient,
    *,
    token: str,
    symbol: str,
    timeframe: str,
    lookback_bars: int,
    factor_ids: list[str] | None,
    idx: int,
) -> ScoreResult:
    body: dict[str, Any] = {
        "venue": "binance",
        "symbol": symbol,
        "timeframe": timeframe,
        "lookback_bars": lookback_bars,
        "horizon_bars": 5,
        "quantiles": 5,
    }
    if factor_ids is not None:
        body["factor_ids"] = factor_ids

    t0 = time.perf_counter()
    try:
        response = await client.post(
            "/score",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Trace-Id": f"issue107-factor-{idx}-{time.time_ns()}",
            },
            json=body,
        )
        elapsed = time.perf_counter() - t0
        bars_used: int | None = None
        factor_count: int | None = None
        if response.status_code < 400:
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    raw_bars = payload.get("bars_used")
                    raw_factors = payload.get("factors")
                    bars_used = int(raw_bars) if raw_bars is not None else None
                    factor_count = len(raw_factors) if isinstance(raw_factors, list) else None
            except Exception:
                pass
        return ScoreResult(
            latency_s=elapsed,
            status=response.status_code,
            code=_machine_code(response),
            bars_used=bars_used,
            factors=factor_count,
        )
    except httpx.RequestError as exc:
        return ScoreResult(
            latency_s=time.perf_counter() - t0,
            error_type=type(exc).__name__,
        )


async def _run_wave(
    *,
    factor_url: str,
    token: str,
    symbols: list[str],
    timeframe: str,
    lookback_bars: int,
    factor_ids: list[str] | None,
    timeout_s: float,
) -> list[ScoreResult]:
    limits = httpx.Limits(
        max_connections=max(50, len(symbols) + 10),
        max_keepalive_connections=max(20, len(symbols)),
    )
    async with httpx.AsyncClient(
        base_url=factor_url,
        timeout=httpx.Timeout(timeout_s),
        limits=limits,
        trust_env=False,
    ) as client:
        return await asyncio.gather(
            *[
                _score_one(
                    client,
                    token=token,
                    symbol=symbol,
                    timeframe=timeframe,
                    lookback_bars=lookback_bars,
                    factor_ids=factor_ids,
                    idx=idx,
                )
                for idx, symbol in enumerate(symbols)
            ]
        )


def _delta(before: dict[str, Any], after: dict[str, Any], key: str) -> int | None:
    if key not in before and key not in after:
        return None
    return int(after.get(key, 0)) - int(before.get(key, 0))


def _print_score_summary(label: str, results: list[ScoreResult]) -> None:
    statuses = Counter(str(r.status) for r in results if r.status is not None)
    errors = Counter(r.error_type for r in results if r.error_type is not None)
    codes = Counter(r.code for r in results if r.code is not None)
    latencies = [r.latency_s for r in results]

    print(f"\n[{label}]")
    print(f"count={len(results)}")
    print(f"status_counts={dict(statuses)}")
    print(f"error_type_counts={dict(errors)}")
    print(f"error_code_counts={dict(codes)}")
    if latencies:
        p50 = _percentile(latencies, 0.50)
        p95 = _percentile(latencies, 0.95)
        p99 = _percentile(latencies, 0.99)
        assert p50 is not None and p95 is not None and p99 is not None
        print(
            f"latency_s p50={p50:.3f} p95={p95:.3f} p99={p99:.3f} "
            f"max={max(latencies):.3f}"
        )
    print(f"bars_used={Counter(r.bars_used for r in results if r.bars_used is not None)}")
    print(f"factor_counts={Counter(r.factors for r in results if r.factors is not None)}")


def _print_state_delta(label: str, before: dict[str, Any], after: dict[str, Any]) -> None:
    print(f"\n[{label}_data_state_delta]")
    print(f"pid_before={before.get('pid')} pid_after={after.get('pid')}")
    if before.get("pid") != after.get("pid"):
        print("WARNING: data state sampled different workers; exact deltas are not valid")

    keys = [
        "http_post_backfill_bars_total",
        "http_get_bars_total",
        "started",
        "completed",
        "cancelled",
        "failed",
        "venue_binance_started",
        "venue_binance_completed",
        "venue_binance_failed",
        "venue_fred_started",
        "venue_fred_completed",
        "venue_fred_failed",
        "pool_requests_num",
        "pool_requests_queued",
        "pool_requests_wait_ms",
        "pool_requests_errors",
        "pool_usage_ms",
    ]
    for key in keys:
        value = _delta(before, after, key)
        if value is not None:
            print(f"{key}_delta={value}")

    for key in (
        "pool_pool_min",
        "pool_pool_max",
        "pool_pool_size",
        "pool_pool_available",
        "pool_requests_waiting",
        "http_post_backfill_bars_inflight",
        "http_get_bars_inflight",
        "venue_binance_active",
        "venue_fred_active",
    ):
        if key in after:
            print(f"{key}_after={after[key]}")


async def _run(args: argparse.Namespace) -> None:
    token = _token()

    initial_state = await _data_state(args.data_url)
    fake_venues = {item.strip() for item in str(initial_state.get("fake_venues", "")).split(",")}
    missing = {"binance", "fred"} - fake_venues
    if missing:
        raise RuntimeError(
            "unsafe macro probe configuration: data wrapper is not faking required venues "
            f"{sorted(missing)}; state fake_venues={sorted(fake_venues)}"
        )

    factor_ids: list[str] | None
    if args.factor_set == "macro":
        factor_ids = await _macro_ids(args.factor_url, token)
        print(f"macro_factor_ids={len(factor_ids)}")
    else:
        factor_ids = None
        print("factor_set=all")

    if args.symbol_mode == "same":
        symbols = [args.symbol] * args.concurrency
    else:
        symbols = [f"ISSUE107-{idx}/USDT" for idx in range(args.concurrency)]

    print(
        "configuration "
        f"concurrency={args.concurrency} symbol_mode={args.symbol_mode} "
        f"timeframe={args.timeframe} lookback_bars={args.lookback_bars}"
    )
    print(
        "IMPORTANT: restart factor-service immediately before this script when you need a true "
        "cold-cache wave."
    )

    before_cold = await _data_state(args.data_url)
    cold_results = await _run_wave(
        factor_url=args.factor_url,
        token=token,
        symbols=symbols,
        timeframe=args.timeframe,
        lookback_bars=args.lookback_bars,
        factor_ids=factor_ids,
        timeout_s=args.timeout,
    )
    after_cold = await _data_state(args.data_url)

    _print_score_summary("cold_or_first_wave", cold_results)
    _print_state_delta("cold_or_first_wave", before_cold, after_cold)

    await asyncio.sleep(args.between_waves)

    before_warm = await _data_state(args.data_url)
    warm_results = await _run_wave(
        factor_url=args.factor_url,
        token=token,
        symbols=symbols,
        timeframe=args.timeframe,
        lookback_bars=args.lookback_bars,
        factor_ids=factor_ids,
        timeout_s=args.timeout,
    )
    after_warm = await _data_state(args.data_url)

    _print_score_summary("immediate_warm_wave", warm_results)
    _print_state_delta("immediate_warm_wave", before_warm, after_warm)

    print("\n[interpretation]")
    print(
        "- exact HTTP/provider deltas require data WORKERS=1; with multiple workers use logs + "
        "per-PID state sampling instead."
    )
    print(
        "- same-symbol cold concurrency can expose full-score + macro in-flight duplication; "
        "unique-symbol mode isolates different price keys that still share macro keys."
    )
    print(
        "- compare http_post_backfill_bars_total/http_get_bars_total with provider-start deltas to "
        "separate factor HTTP fan-out from data provider pagination/behavior."
    )
    print(
        "- an immediate warm wave with ~zero data/provider deltas confirms post-population cache "
        "reuse; it does not by itself prove cold in-flight coalescing."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor-url", default="http://127.0.0.1:18004")
    parser.add_argument("--data-url", default="http://127.0.0.1:18001")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--symbol-mode", choices=("same", "unique"), default="same")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", choices=("1d", "1wk"), default="1d")
    parser.add_argument("--lookback-bars", type=int, default=720)
    parser.add_argument("--factor-set", choices=("macro", "all"), default="macro")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--between-waves", type=float, default=0.25)
    return parser


if __name__ == "__main__":
    asyncio.run(_run(_parser().parse_args()))
