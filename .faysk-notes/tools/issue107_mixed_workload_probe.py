"""Contributor-only mixed workload probe for Inalpha issue #107.

This is the closest synthetic reproduction of the workload family named by the issue without
requiring real providers or seeded paper strategies:

    concurrent live factor /score requests (including macro FRED fan-out)
    + live-runner-like fresh polls across crypto / A-share / Japan
    + DB-backed /health and DB-free /openapi.json control probes

The target data service MUST be ``issue107_slow_data_app.py`` with every used venue replaced by the
local fake connector. The script refuses to run otherwise. This tool never intentionally contacts a
real market-data provider.

Recommended exact-count topology:

    data:   1 worker, fake binance,fred,baostock,yfinance, 1000 bars/fetch
    factor: 1 worker, DATA_SERVICE_URL=http://127.0.0.1:18001

Restart factor immediately before a cold-cache run.

Example:

    uv run python issue107_mixed_workload_probe.py \
      --factor-url http://127.0.0.1:18004 \
      --data-url http://127.0.0.1:18001 \
      --factor-concurrency 4 \
      --factor-symbol-mode same \
      --runner-runs 8 \
      --runner-stagger-ms 0

Repeat the same topology with ``--runner-stagger-ms 100`` to isolate H6 while keeping the factor
burst constant. For a true cold comparison, restart factor before each run.
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


@dataclass
class FactorResult:
    latency_s: float
    status: int | None = None
    error_type: str | None = None
    code: str | None = None
    bars_used: int | None = None
    factors: int | None = None


@dataclass(frozen=True)
class SimRun:
    idx: int
    venue: str
    symbol: str
    timeframe: str


@dataclass
class RunnerResult:
    run: SimRun
    latency_s: float
    backfill_status: int | None = None
    backfill_error: str | None = None
    backfill_code: str | None = None
    bars_status: int | None = None
    bars_error: str | None = None
    bars_code: str | None = None
    bars_count: int | None = None


@dataclass
class ProbeResult:
    kind: str
    latency_s: float
    status: int | None = None
    error_type: str | None = None
    code: str | None = None


def _token() -> str:
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "issue107-mixed-probe",
            "email": "issue107-mixed@local.invalid",
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


async def _sample_state(
    *,
    data_url: str,
    stop: asyncio.Event,
    samples: list[dict[str, Any]],
    interval_s: float,
) -> None:
    while not stop.is_set():
        try:
            samples.append(await _data_state(data_url))
        except Exception as exc:
            samples.append({"sample_error": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass


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


async def _factor_one(
    client: httpx.AsyncClient,
    *,
    token: str,
    symbol: str,
    factor_ids: list[str],
    idx: int,
    lookback_bars: int,
) -> FactorResult:
    t0 = time.perf_counter()
    try:
        response = await client.post(
            "/score",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Trace-Id": f"issue107-mixed-factor-{idx}-{time.time_ns()}",
            },
            json={
                "venue": "binance",
                "symbol": symbol,
                "timeframe": "1d",
                "lookback_bars": lookback_bars,
                "horizon_bars": 5,
                "quantiles": 5,
                "factor_ids": factor_ids,
            },
        )
        elapsed = time.perf_counter() - t0
        bars_used: int | None = None
        factor_count: int | None = None
        if response.status_code < 400:
            try:
                body = response.json()
                if isinstance(body, dict):
                    raw_bars = body.get("bars_used")
                    raw_factors = body.get("factors")
                    bars_used = int(raw_bars) if raw_bars is not None else None
                    factor_count = len(raw_factors) if isinstance(raw_factors, list) else None
            except Exception:
                pass
        return FactorResult(
            latency_s=elapsed,
            status=response.status_code,
            code=_machine_code(response),
            bars_used=bars_used,
            factors=factor_count,
        )
    except httpx.RequestError as exc:
        return FactorResult(
            latency_s=time.perf_counter() - t0,
            error_type=type(exc).__name__,
        )


async def _factor_wave(
    *,
    factor_url: str,
    token: str,
    factor_ids: list[str],
    concurrency: int,
    symbol_mode: str,
    symbol: str,
    lookback_bars: int,
    timeout_s: float,
) -> list[FactorResult]:
    if symbol_mode == "same":
        symbols = [symbol] * concurrency
    else:
        symbols = [f"ISSUE107-MIXED-F{idx}/USDT" for idx in range(concurrency)]

    limits = httpx.Limits(
        max_connections=max(50, concurrency + 10),
        max_keepalive_connections=max(20, concurrency),
    )
    async with httpx.AsyncClient(
        base_url=factor_url,
        timeout=httpx.Timeout(timeout_s),
        limits=limits,
        trust_env=False,
    ) as client:
        return await asyncio.gather(
            *[
                _factor_one(
                    client,
                    token=token,
                    symbol=symbol_value,
                    factor_ids=factor_ids,
                    idx=idx,
                    lookback_bars=lookback_bars,
                )
                for idx, symbol_value in enumerate(symbols)
            ]
        )


def _build_runs(count: int) -> list[SimRun]:
    if count < 1:
        raise ValueError("--runner-runs must be >= 1")
    out: list[SimRun] = []
    for idx in range(count):
        venue, symbol, timeframe = _RUN_PRESETS[idx % len(_RUN_PRESETS)]
        cycle = idx // len(_RUN_PRESETS)
        if cycle:
            symbol = f"{symbol}-R{cycle}"
        out.append(SimRun(idx=idx, venue=venue, symbol=symbol, timeframe=timeframe))
    return out


async def _runner_one(
    *,
    data_url: str,
    token: str,
    run: SimRun,
    timeout_s: float,
    stagger_s: float,
) -> RunnerResult:
    if stagger_s > 0:
        await asyncio.sleep(run.idx * stagger_s)

    now = datetime.now(UTC)
    tf_s = _TF_SECONDS[run.timeframe]
    from_ts = now - timedelta(seconds=max(tf_s * 5, 7200))
    t0 = time.perf_counter()
    result = RunnerResult(run=run, latency_s=0.0)

    # Match current paper _fetch_latest_bar: one DataClient lifecycle per poll.
    async with httpx.AsyncClient(
        base_url=data_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(timeout_s),
        trust_env=False,
    ) as client:
        try:
            response = await client.post(
                "/backfill/bars",
                headers={"X-Trace-Id": f"issue107-mixed-runner-bf-{run.idx}-{time.time_ns()}"},
                json={
                    "venue": run.venue,
                    "symbol": run.symbol,
                    "timeframe": run.timeframe,
                    "from_ts": from_ts.isoformat(),
                    "to_ts": now.isoformat(),
                },
            )
            result.backfill_status = response.status_code
            result.backfill_code = _machine_code(response)
        except httpx.RequestError as exc:
            # Paper fresh read treats refresh as best effort and still attempts GET /bars.
            result.backfill_error = type(exc).__name__

        try:
            response = await client.get(
                "/bars",
                headers={"X-Trace-Id": f"issue107-mixed-runner-bars-{run.idx}-{time.time_ns()}"},
                params={
                    "venue": run.venue,
                    "symbol": run.symbol,
                    "timeframe": run.timeframe,
                    "from_ts": from_ts.isoformat(),
                    "to_ts": now.isoformat(),
                    "limit": 5,
                },
            )
            result.bars_status = response.status_code
            result.bars_code = _machine_code(response)
            if response.status_code < 400:
                body = response.json()
                result.bars_count = len(body) if isinstance(body, list) else None
        except httpx.RequestError as exc:
            result.bars_error = type(exc).__name__

    result.latency_s = time.perf_counter() - t0
    return result


async def _runner_wave(
    *,
    data_url: str,
    token: str,
    runs: list[SimRun],
    timeout_s: float,
    stagger_ms: float,
) -> list[RunnerResult]:
    return await asyncio.gather(
        *[
            _runner_one(
                data_url=data_url,
                token=token,
                run=run,
                timeout_s=timeout_s,
                stagger_s=stagger_ms / 1000.0,
            )
            for run in runs
        ]
    )


async def _probe_one(
    client: httpx.AsyncClient,
    *,
    kind: str,
    path: str,
    timeout_s: float,
    idx: int,
) -> ProbeResult:
    t0 = time.perf_counter()
    try:
        response = await client.get(
            path,
            headers={"X-Trace-Id": f"issue107-mixed-{kind}-{idx}-{time.time_ns()}"},
            timeout=timeout_s,
        )
        return ProbeResult(
            kind=kind,
            latency_s=time.perf_counter() - t0,
            status=response.status_code,
            code=_machine_code(response),
        )
    except httpx.RequestError as exc:
        return ProbeResult(
            kind=kind,
            latency_s=time.perf_counter() - t0,
            error_type=type(exc).__name__,
        )


async def _control_wave(
    *,
    data_url: str,
    count: int,
    timeout_s: float,
    interval_s: float,
    start_delay_s: float,
) -> tuple[list[ProbeResult], list[ProbeResult]]:
    health: list[ProbeResult] = []
    openapi: list[ProbeResult] = []
    if count <= 0:
        return health, openapi

    await asyncio.sleep(start_delay_s)
    async with httpx.AsyncClient(base_url=data_url, timeout=timeout_s, trust_env=False) as client:
        for idx in range(count):
            # DB-free control first, then DB-backed health.
            openapi.append(
                await _probe_one(
                    client,
                    kind="openapi",
                    path="/openapi.json",
                    timeout_s=timeout_s,
                    idx=idx,
                )
            )
            health.append(
                await _probe_one(
                    client,
                    kind="health",
                    path="/health",
                    timeout_s=timeout_s,
                    idx=idx,
                )
            )
            if idx + 1 < count:
                await asyncio.sleep(interval_s)
    return health, openapi


def _delta(before: dict[str, Any], after: dict[str, Any], key: str) -> int | None:
    if key not in before and key not in after:
        return None
    return int(after.get(key, 0)) - int(before.get(key, 0))


def _numeric(samples: list[dict[str, Any]], key: str) -> list[int]:
    out: list[int] = []
    for sample in samples:
        value = sample.get(key)
        if isinstance(value, (int, float)):
            out.append(int(value))
    return out


def _print_factor(results: list[FactorResult]) -> None:
    print("\n[factor]")
    statuses = Counter(str(r.status) for r in results if r.status is not None)
    errors = Counter(r.error_type for r in results if r.error_type)
    codes = Counter(r.code for r in results if r.code)
    print(f"count={len(results)}")
    print(f"status_counts={dict(statuses)}")
    print(f"error_type_counts={dict(errors)}")
    print(f"error_code_counts={dict(codes)}")
    print(f"bars_used={dict(Counter(r.bars_used for r in results if r.bars_used is not None))}")
    print(f"factor_counts={dict(Counter(r.factors for r in results if r.factors is not None))}")
    _print_latency(results)


def _print_runner(results: list[RunnerResult]) -> None:
    print("\n[runner]")
    print(f"count={len(results)}")
    print(
        "backfill_status_counts="
        f"{dict(Counter(str(r.backfill_status) for r in results if r.backfill_status is not None))}"
    )
    print(
        "backfill_error_counts="
        f"{dict(Counter(r.backfill_error for r in results if r.backfill_error))}"
    )
    print(
        "backfill_code_counts="
        f"{dict(Counter(r.backfill_code for r in results if r.backfill_code))}"
    )
    print(
        "bars_status_counts="
        f"{dict(Counter(str(r.bars_status) for r in results if r.bars_status is not None))}"
    )
    print(f"bars_error_counts={dict(Counter(r.bars_error for r in results if r.bars_error))}")
    print(f"bars_code_counts={dict(Counter(r.bars_code for r in results if r.bars_code))}")
    print(f"bars_count={dict(Counter(r.bars_count for r in results if r.bars_count is not None))}")
    _print_latency(results)


def _print_latency(results: list[Any]) -> None:
    values = [float(r.latency_s) for r in results]
    if not values:
        return
    p50 = _percentile(values, 0.50)
    p95 = _percentile(values, 0.95)
    p99 = _percentile(values, 0.99)
    assert p50 is not None and p95 is not None and p99 is not None
    print(
        f"latency_s p50={p50:.3f} p95={p95:.3f} p99={p99:.3f} max={max(values):.3f}"
    )


def _print_controls(health: list[ProbeResult], openapi: list[ProbeResult]) -> None:
    for name, results in (("openapi_control", openapi), ("health", health)):
        print(f"\n[{name}]")
        print(f"count={len(results)}")
        print(
            f"status_counts={dict(Counter(str(r.status) for r in results if r.status is not None))}"
        )
        print(f"error_type_counts={dict(Counter(r.error_type for r in results if r.error_type))}")
        print(f"error_code_counts={dict(Counter(r.code for r in results if r.code))}")
        _print_latency(results)


def _print_state_delta(before: dict[str, Any], after: dict[str, Any]) -> None:
    print("\n[data_state_delta]")
    print(f"pid_before={before.get('pid')} pid_after={after.get('pid')}")
    if before.get("pid") != after.get("pid"):
        print("WARNING: state sampled different workers; exact deltas are invalid")

    keys = (
        "http_post_backfill_bars_total",
        "http_get_bars_total",
        "started",
        "completed",
        "cancelled",
        "failed",
        "venue_binance_started",
        "venue_fred_started",
        "venue_baostock_started",
        "venue_yfinance_started",
        "pool_requests_num",
        "pool_requests_queued",
        "pool_requests_wait_ms",
        "pool_requests_errors",
        "pool_usage_ms",
    )
    for key in keys:
        value = _delta(before, after, key)
        if value is not None:
            print(f"{key}_delta={value}")


def _print_peak_state(samples: list[dict[str, Any]]) -> None:
    print("\n[peak_state_during_mixed_wave]")
    print(f"samples={len(samples)}")
    errors = Counter(str(s.get("sample_error")) for s in samples if s.get("sample_error"))
    print(f"sample_errors={dict(errors)}")

    max_keys = (
        "active",
        "venue_binance_active",
        "venue_fred_active",
        "venue_baostock_active",
        "venue_yfinance_active",
        "thread_active",
        "http_post_backfill_bars_inflight",
        "http_get_bars_inflight",
        "pool_requests_waiting",
    )
    for key in max_keys:
        values = _numeric(samples, key)
        if values:
            print(f"{key}_max={max(values)}")

    available = _numeric(samples, "pool_pool_available")
    if available:
        print(f"pool_pool_available_min={min(available)}")

    size = _numeric(samples, "pool_pool_size")
    if size:
        print(f"pool_pool_size_max={max(size)}")


def _required_runner_venues(runs: list[SimRun]) -> set[str]:
    return {run.venue for run in runs}


async def _run(args: argparse.Namespace) -> None:
    token = _token()
    runs = _build_runs(args.runner_runs)
    before = await _data_state(args.data_url)

    required = _required_runner_venues(runs) | {"binance", "fred"}
    fake = {item.strip() for item in str(before.get("fake_venues", "")).split(",") if item.strip()}
    missing = required - fake
    if missing:
        raise RuntimeError(
            "unsafe mixed probe configuration: all data venues must be fake; "
            f"missing={sorted(missing)} configured={sorted(fake)}"
        )

    bars_per_fetch = int(before.get("fake_bars_per_fetch", 0) or 0)
    if bars_per_fetch < 1000:
        raise RuntimeError(
            "mixed probe requires ISSUE107_FAKE_BARS_PER_FETCH>=1000 so long 1d factor windows "
            "do not become artificial multi-batch provider loops; "
            f"current={bars_per_fetch}"
        )

    factor_ids = await _macro_ids(args.factor_url, token)
    print(
        "configuration "
        f"factor_concurrency={args.factor_concurrency} "
        f"factor_symbol_mode={args.factor_symbol_mode} macro_factor_ids={len(factor_ids)} "
        f"runner_runs={args.runner_runs} runner_stagger_ms={args.runner_stagger_ms} "
        f"control_probes={args.control_probes} sample_interval={args.sample_interval}s "
        f"fake_venues={sorted(fake)} fake_bars_per_fetch={bars_per_fetch}"
    )
    print("IMPORTANT: restart factor-service immediately before this script for a true cold-cache run.")

    stop = asyncio.Event()
    samples: list[dict[str, Any]] = []
    sampler = asyncio.create_task(
        _sample_state(
            data_url=args.data_url,
            stop=stop,
            samples=samples,
            interval_s=args.sample_interval,
        )
    )

    factor_task = asyncio.create_task(
        _factor_wave(
            factor_url=args.factor_url,
            token=token,
            factor_ids=factor_ids,
            concurrency=args.factor_concurrency,
            symbol_mode=args.factor_symbol_mode,
            symbol=args.factor_symbol,
            lookback_bars=args.lookback_bars,
            timeout_s=args.factor_timeout,
        )
    )
    runner_task = asyncio.create_task(
        _runner_wave(
            data_url=args.data_url,
            token=token,
            runs=runs,
            timeout_s=args.runner_timeout,
            stagger_ms=args.runner_stagger_ms,
        )
    )
    control_task = asyncio.create_task(
        _control_wave(
            data_url=args.data_url,
            count=args.control_probes,
            timeout_s=args.control_timeout,
            interval_s=args.control_interval,
            start_delay_s=args.control_start_delay,
        )
    )

    try:
        factor_results, runner_results, controls = await asyncio.gather(
            factor_task, runner_task, control_task
        )
    finally:
        stop.set()
        await sampler

    after = await _data_state(args.data_url)
    health_results, openapi_results = controls

    _print_factor(factor_results)
    _print_runner(runner_results)
    _print_controls(health_results, openapi_results)
    _print_state_delta(before, after)
    _print_peak_state(samples)

    health_failures = sum(
        1 for r in health_results if r.error_type is not None or (r.status or 0) >= 400
    )
    openapi_failures = sum(
        1 for r in openapi_results if r.error_type is not None or (r.status or 0) >= 400
    )
    factor_failures = sum(
        1 for r in factor_results if r.error_type is not None or (r.status or 0) >= 400
    )
    runner_read_failures = sum(
        1
        for r in runner_results
        if r.bars_error is not None or (r.bars_status is not None and r.bars_status >= 400)
    )

    print("\n[acceptance_signals]")
    print(f"factor_failures={factor_failures}/{len(factor_results)}")
    print(f"runner_bars_failures={runner_read_failures}/{len(runner_results)}")
    print(f"health_failures={health_failures}/{len(health_results)}")
    print(f"openapi_failures={openapi_failures}/{len(openapi_results)}")
    print(
        "Interpret intentional HTTP backpressure separately from transport failures if a later "
        "candidate introduces admission control."
    )

    print("\n[interpretation]")
    print(
        "- one-worker runs provide exact process-local provider/pool deltas and should be used to "
        "identify the first saturated resource."
    )
    print(
        "- rerun with two data workers only after the one-worker mechanism is understood; state "
        "sampling is process-local under multi-worker Uvicorn."
    )
    print(
        "- compare runner_stagger_ms=0 vs a small stagger with factor cold-cache conditions held "
        "constant; restart factor before each cold comparison."
    )
    print(
        "- factor_symbol_mode=same exposes whole-score cache stampede potential (H11); unique keeps "
        "price keys distinct while macro/date keys remain shared (H8)."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor-url", default="http://127.0.0.1:18004")
    parser.add_argument("--data-url", default="http://127.0.0.1:18001")
    parser.add_argument("--factor-concurrency", type=int, default=4)
    parser.add_argument("--factor-symbol-mode", choices=("same", "unique"), default="same")
    parser.add_argument("--factor-symbol", default="BTC/USDT")
    parser.add_argument("--lookback-bars", type=int, default=720)
    parser.add_argument("--factor-timeout", type=float, default=180.0)
    parser.add_argument("--runner-runs", type=int, default=8)
    parser.add_argument("--runner-stagger-ms", type=float, default=0.0)
    parser.add_argument("--runner-timeout", type=float, default=60.0)
    parser.add_argument("--control-probes", type=int, default=5)
    parser.add_argument("--control-timeout", type=float, default=1.0)
    parser.add_argument("--control-interval", type=float, default=0.1)
    parser.add_argument("--control-start-delay", type=float, default=0.1)
    parser.add_argument("--sample-interval", type=float, default=0.05)
    return parser


if __name__ == "__main__":
    asyncio.run(_run(_parser().parse_args()))
