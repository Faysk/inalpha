"""Contributor-only sustained mixed-load probe for Inalpha issue #107.

Purpose
-------
The original issue is about *sustained* concurrency, not only one synchronized burst. This probe
runs a bounded sequence of mixed cycles against contributor wrappers only:

    new live factor score key each cycle
    + runner-like fresh polls across crypto / A-share / Japan
    + DB-backed /health and DB-free /openapi.json controls

Safety
------
Before scheduling any load it verifies both contributor-only endpoints:

    data   GET /__issue107/state
    factor GET /__issue107/config

It refuses to run unless:

- binance, fred, baostock and yfinance are all fake (or the explicitly requested set is fake);
- factor's configured data_service_url equals the checked contributor data URL;
- factor's expected_data_url equals the checked contributor data URL;
- macro is enabled;
- fake bars per provider fetch is >= 1000.

No real provider should be contacted when these guards pass.

This tool is deliberately bounded: if too many cycles are still pending, it skips new injections
instead of creating an unbounded local request storm.
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
    "1h": 3600,
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
class Result:
    kind: str
    latency_s: float
    status: int | None = None
    error_type: str | None = None
    code: str | None = None
    progress: int | None = None


@dataclass(frozen=True)
class SimRun:
    idx: int
    venue: str
    symbol: str
    timeframe: str


@dataclass
class CycleResult:
    cycle: int
    elapsed_s: float
    factor: list[Result]
    runner_backfill: list[Result]
    runner_bars: list[Result]
    health: list[Result]
    openapi: list[Result]


def _norm(url: str) -> str:
    return url.strip().rstrip("/")


def _token() -> str:
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "issue107-sustained-probe",
            "email": "issue107-sustained@local.invalid",
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


def _code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except Exception:
        return None
    return body.get("code") if isinstance(body, dict) else None


async def _json_get(base_url: str, path: str) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0, trust_env=False) as client:
        response = await client.get(path)
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"unexpected payload from {base_url}{path}: {body!r}")
    return body


async def _preflight(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    data_url = _norm(args.data_url)
    factor_url = _norm(args.factor_url)

    try:
        data = await _json_get(data_url, "/__issue107/state")
    except Exception as exc:
        raise RuntimeError(
            "unsafe sustained probe target: contributor data state endpoint unavailable"
        ) from exc

    fake = {
        item.strip().lower()
        for item in str(data.get("fake_venues", "")).split(",")
        if item.strip()
    }
    required = {"binance", "fred"} | {
        venue for venue, _symbol, _timeframe in _RUN_PRESETS[: args.runner_runs]
    }
    missing = required - fake
    if missing:
        raise RuntimeError(
            "unsafe sustained probe target: required venues are not fake; "
            f"missing={sorted(missing)} configured={sorted(fake)}"
        )

    bars_per_fetch = int(data.get("fake_bars_per_fetch", 0) or 0)
    if bars_per_fetch < 1000:
        raise RuntimeError(
            "misleading sustained probe configuration: ISSUE107_FAKE_BARS_PER_FETCH must be >=1000; "
            f"current={bars_per_fetch}"
        )

    try:
        factor = await _json_get(factor_url, "/__issue107/config")
    except Exception as exc:
        raise RuntimeError(
            "unsafe sustained probe target: contributor factor config endpoint unavailable; "
            "start issue107_factor_app:app"
        ) from exc

    configured_data = _norm(str(factor.get("data_service_url", "")))
    expected_data = _norm(str(factor.get("expected_data_url", "")))
    if configured_data != data_url or expected_data != data_url:
        raise RuntimeError(
            "unsafe sustained factor routing: factor is not pinned to the checked fake data target; "
            f"configured={configured_data!r} expected={expected_data!r} checked={data_url!r}"
        )
    if factor.get("macro_enabled") is not True:
        raise RuntimeError("sustained mixed probe requires macro_enabled=true")

    return data, factor


async def _macro_ids(factor_url: str, token: str) -> list[str]:
    async with httpx.AsyncClient(base_url=factor_url, timeout=10.0, trust_env=False) as client:
        response = await client.get("/catalog", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        body = response.json()
    factors = body.get("factors", []) if isinstance(body, dict) else []
    ids = [
        str(item["factor_id"])
        for item in factors
        if isinstance(item, dict)
        and item.get("source") == "macro"
        and item.get("available", True)
        and item.get("factor_id")
    ]
    if not ids:
        raise RuntimeError("factor catalog returned no available macro factor ids")
    return ids


async def _factor_one(
    client: httpx.AsyncClient,
    *,
    token: str,
    symbol: str,
    factor_ids: list[str],
    cycle: int,
    idx: int,
    lookback_bars: int,
) -> Result:
    t0 = time.perf_counter()
    try:
        response = await client.post(
            "/score",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Trace-Id": f"issue107-soak-factor-{cycle}-{idx}-{time.time_ns()}",
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
        progress: int | None = None
        if response.status_code < 400:
            body = response.json()
            if isinstance(body, dict) and body.get("bars_used") is not None:
                progress = int(body["bars_used"])
        return Result(
            kind="factor",
            latency_s=time.perf_counter() - t0,
            status=response.status_code,
            code=_code(response),
            progress=progress,
        )
    except httpx.RequestError as exc:
        return Result(
            kind="factor",
            latency_s=time.perf_counter() - t0,
            error_type=type(exc).__name__,
        )


async def _runner_one(
    *,
    data_url: str,
    token: str,
    run: SimRun,
    cycle: int,
    timeout_s: float,
    stagger_s: float,
) -> tuple[Result, Result]:
    if stagger_s > 0:
        await asyncio.sleep(run.idx * stagger_s)

    now = datetime.now(UTC)
    tf_s = _TF_SECONDS[run.timeframe]
    from_ts = now - timedelta(seconds=max(tf_s * 5, 7200))

    async with httpx.AsyncClient(
        base_url=data_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(timeout_s),
        trust_env=False,
    ) as client:
        t0 = time.perf_counter()
        try:
            response = await client.post(
                "/backfill/bars",
                headers={
                    "X-Trace-Id": f"issue107-soak-runner-bf-{cycle}-{run.idx}-{time.time_ns()}"
                },
                json={
                    "venue": run.venue,
                    "symbol": run.symbol,
                    "timeframe": run.timeframe,
                    "from_ts": from_ts.isoformat(),
                    "to_ts": now.isoformat(),
                },
            )
            progress: int | None = None
            if response.status_code < 400:
                body = response.json()
                if isinstance(body, dict) and body.get("bars_fetched") is not None:
                    progress = int(body["bars_fetched"])
            backfill = Result(
                kind="runner_backfill",
                latency_s=time.perf_counter() - t0,
                status=response.status_code,
                code=_code(response),
                progress=progress,
            )
        except httpx.RequestError as exc:
            backfill = Result(
                kind="runner_backfill",
                latency_s=time.perf_counter() - t0,
                error_type=type(exc).__name__,
            )

        # Preserve current paper semantics: refresh is best-effort; still read cached bars.
        t1 = time.perf_counter()
        try:
            response = await client.get(
                "/bars",
                headers={
                    "X-Trace-Id": f"issue107-soak-runner-bars-{cycle}-{run.idx}-{time.time_ns()}"
                },
                params={
                    "venue": run.venue,
                    "symbol": run.symbol,
                    "timeframe": run.timeframe,
                    "from_ts": from_ts.isoformat(),
                    "to_ts": now.isoformat(),
                    "limit": 5,
                },
            )
            progress = None
            if response.status_code < 400:
                body = response.json()
                progress = len(body) if isinstance(body, list) else None
            bars = Result(
                kind="runner_bars",
                latency_s=time.perf_counter() - t1,
                status=response.status_code,
                code=_code(response),
                progress=progress,
            )
        except httpx.RequestError as exc:
            bars = Result(
                kind="runner_bars",
                latency_s=time.perf_counter() - t1,
                error_type=type(exc).__name__,
            )

    return backfill, bars


async def _control_one(
    client: httpx.AsyncClient,
    *,
    kind: str,
    path: str,
    cycle: int,
    idx: int,
    timeout_s: float,
) -> Result:
    t0 = time.perf_counter()
    try:
        response = await client.get(
            path,
            headers={"X-Trace-Id": f"issue107-soak-{kind}-{cycle}-{idx}-{time.time_ns()}"},
            timeout=timeout_s,
        )
        return Result(
            kind=kind,
            latency_s=time.perf_counter() - t0,
            status=response.status_code,
            code=_code(response),
        )
    except httpx.RequestError as exc:
        return Result(
            kind=kind,
            latency_s=time.perf_counter() - t0,
            error_type=type(exc).__name__,
        )


def _build_runs(count: int) -> list[SimRun]:
    if count < 1 or count > len(_RUN_PRESETS):
        raise ValueError(f"--runner-runs must be between 1 and {len(_RUN_PRESETS)}")
    return [
        SimRun(idx=idx, venue=venue, symbol=symbol, timeframe=timeframe)
        for idx, (venue, symbol, timeframe) in enumerate(_RUN_PRESETS[:count])
    ]


async def _cycle(
    *,
    cycle: int,
    args: argparse.Namespace,
    token: str,
    factor_ids: list[str],
    factor_client: httpx.AsyncClient,
    control_client: httpx.AsyncClient,
    runs: list[SimRun],
) -> CycleResult:
    started = time.perf_counter()

    # New score key each cycle keeps the agent-side price request cold while macro/date keys become
    # naturally warm after the first successful cycle. This is closer to repeated queries across
    # different assets than restarting factor every second.
    symbol = f"ISSUE107-SOAK-{cycle}/USDT"
    factor_tasks = [
        asyncio.create_task(
            _factor_one(
                factor_client,
                token=token,
                symbol=symbol,
                factor_ids=factor_ids,
                cycle=cycle,
                idx=idx,
                lookback_bars=args.lookback_bars,
            )
        )
        for idx in range(args.factor_concurrency)
    ]

    runner_tasks = [
        asyncio.create_task(
            _runner_one(
                data_url=args.data_url,
                token=token,
                run=run,
                cycle=cycle,
                timeout_s=args.runner_timeout,
                stagger_s=args.runner_stagger_ms / 1000.0,
            )
        )
        for run in runs
    ]

    await asyncio.sleep(args.control_start_delay)
    openapi_tasks = [
        asyncio.create_task(
            _control_one(
                control_client,
                kind="openapi",
                path="/openapi.json",
                cycle=cycle,
                idx=idx,
                timeout_s=args.control_timeout,
            )
        )
        for idx in range(args.controls_per_cycle)
    ]
    health_tasks = [
        asyncio.create_task(
            _control_one(
                control_client,
                kind="health",
                path="/health",
                cycle=cycle,
                idx=idx,
                timeout_s=args.control_timeout,
            )
        )
        for idx in range(args.controls_per_cycle)
    ]

    factor_results = await asyncio.gather(*factor_tasks)
    runner_pairs = await asyncio.gather(*runner_tasks)
    openapi = await asyncio.gather(*openapi_tasks)
    health = await asyncio.gather(*health_tasks)

    return CycleResult(
        cycle=cycle,
        elapsed_s=time.perf_counter() - started,
        factor=factor_results,
        runner_backfill=[pair[0] for pair in runner_pairs],
        runner_bars=[pair[1] for pair in runner_pairs],
        health=health,
        openapi=openapi,
    )


async def _sample_state(
    data_url: str,
    stop: asyncio.Event,
    samples: list[dict[str, Any]],
    interval_s: float,
) -> None:
    while not stop.is_set():
        try:
            samples.append(await _json_get(data_url, "/__issue107/state"))
        except Exception as exc:
            samples.append({"sample_error": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass


def _all_results(cycles: list[CycleResult], attr: str) -> list[Result]:
    out: list[Result] = []
    for cycle in cycles:
        out.extend(getattr(cycle, attr))
    return out


def _print_result_summary(label: str, results: list[Result]) -> None:
    print(f"\n[{label}]")
    print(f"count={len(results)}")
    statuses = Counter(str(r.status) for r in results if r.status is not None)
    errors = Counter(r.error_type for r in results if r.error_type)
    codes = Counter(r.code for r in results if r.code)
    print(f"status_counts={dict(statuses)}")
    print(f"error_type_counts={dict(errors)}")
    print(f"error_code_counts={dict(codes)}")

    latencies = [r.latency_s for r in results]
    if latencies:
        p50 = _percentile(latencies, 0.50)
        p95 = _percentile(latencies, 0.95)
        p99 = _percentile(latencies, 0.99)
        assert p50 is not None and p95 is not None and p99 is not None
        print(
            f"latency_s p50={p50:.3f} p95={p95:.3f} p99={p99:.3f} "
            f"max={max(latencies):.3f}"
        )

    progress = [r.progress for r in results if r.progress is not None]
    if progress:
        print(f"progress_zero={sum(1 for value in progress if value <= 0)}/{len(progress)}")
        print(f"progress_min={min(progress)} progress_max={max(progress)}")


def _numeric(samples: list[dict[str, Any]], key: str) -> list[int]:
    return [
        int(sample[key])
        for sample in samples
        if isinstance(sample.get(key), (int, float))
    ]


def _print_state_summary(samples: list[dict[str, Any]]) -> None:
    print("\n[state_sampling]")
    print(f"samples={len(samples)}")
    errors = Counter(str(s.get("sample_error")) for s in samples if s.get("sample_error"))
    print(f"sample_errors={dict(errors)}")

    for key in (
        "active",
        "venue_binance_active",
        "venue_fred_active",
        "venue_baostock_active",
        "venue_yfinance_active",
        "thread_active",
        "http_post_backfill_bars_inflight",
        "http_get_bars_inflight",
        "pool_requests_waiting",
    ):
        values = _numeric(samples, key)
        if values:
            print(f"{key}_max={max(values)}")

    available = _numeric(samples, "pool_pool_available")
    if available:
        print(f"pool_pool_available_min={min(available)}")

    pids = sorted({str(sample.get("pid")) for sample in samples if sample.get("pid") is not None})
    print(f"observed_data_pids={pids}")


async def _run(args: argparse.Namespace) -> None:
    if args.duration <= 0 or args.cycle_interval <= 0:
        raise ValueError("--duration and --cycle-interval must be > 0")
    if args.factor_concurrency < 1:
        raise ValueError("--factor-concurrency must be >= 1")
    if args.controls_per_cycle < 1:
        raise ValueError("--controls-per-cycle must be >= 1")
    if args.max_pending_cycles < 1:
        raise ValueError("--max-pending-cycles must be >= 1")

    args.data_url = _norm(args.data_url)
    args.factor_url = _norm(args.factor_url)
    data_state, factor_state = await _preflight(args)
    token = _token()
    factor_ids = await _macro_ids(args.factor_url, token)
    runs = _build_runs(args.runner_runs)

    print("issue107_sustained_preflight=PASS")
    print(f"data_pid={data_state.get('pid')} factor_pid={factor_state.get('pid')}")
    print(f"macro_factor_ids={len(factor_ids)}")
    print(
        "configuration "
        f"duration={args.duration}s interval={args.cycle_interval}s "
        f"factor_concurrency={args.factor_concurrency} runner_runs={args.runner_runs} "
        f"runner_stagger_ms={args.runner_stagger_ms} controls_per_cycle={args.controls_per_cycle} "
        f"max_pending_cycles={args.max_pending_cycles}"
    )

    factor_limits = httpx.Limits(
        max_connections=max(50, args.factor_concurrency * args.max_pending_cycles + 10),
        max_keepalive_connections=max(20, args.factor_concurrency * 2),
    )
    control_limits = httpx.Limits(max_connections=30, max_keepalive_connections=10)

    stop_sampling = asyncio.Event()
    samples: list[dict[str, Any]] = []
    sampler = asyncio.create_task(
        _sample_state(args.data_url, stop_sampling, samples, args.sample_interval)
    )

    cycle_tasks: list[asyncio.Task[CycleResult]] = []
    skipped_cycles = 0
    started_cycles = 0
    benchmark_start = time.perf_counter()
    next_start = benchmark_start

    async with httpx.AsyncClient(
        base_url=args.factor_url,
        timeout=httpx.Timeout(args.factor_timeout),
        limits=factor_limits,
        trust_env=False,
    ) as factor_client, httpx.AsyncClient(
        base_url=args.data_url,
        timeout=httpx.Timeout(args.control_timeout),
        limits=control_limits,
        trust_env=False,
    ) as control_client:
        while True:
            now = time.perf_counter()
            if now - benchmark_start >= args.duration:
                break

            if now < next_start:
                await asyncio.sleep(next_start - now)

            pending = sum(1 for task in cycle_tasks if not task.done())
            if pending >= args.max_pending_cycles:
                skipped_cycles += 1
            else:
                task = asyncio.create_task(
                    _cycle(
                        cycle=started_cycles,
                        args=args,
                        token=token,
                        factor_ids=factor_ids,
                        factor_client=factor_client,
                        control_client=control_client,
                        runs=runs,
                    )
                )
                cycle_tasks.append(task)
                started_cycles += 1

            next_start += args.cycle_interval

        try:
            cycles = await asyncio.wait_for(
                asyncio.gather(*cycle_tasks),
                timeout=args.settle_timeout,
            )
        finally:
            stop_sampling.set()
            await sampler

    total_elapsed = time.perf_counter() - benchmark_start
    cycles = sorted(cycles, key=lambda item: item.cycle)

    print("\n[schedule]")
    print(f"cycles_started={started_cycles}")
    print(f"cycles_skipped_pending_cap={skipped_cycles}")
    print(f"benchmark_elapsed_s={total_elapsed:.3f}")
    if cycles:
        cycle_elapsed = [item.elapsed_s for item in cycles]
        print(
            f"cycle_elapsed_s min={min(cycle_elapsed):.3f} "
            f"p50={_percentile(cycle_elapsed, 0.50):.3f} "
            f"p95={_percentile(cycle_elapsed, 0.95):.3f} max={max(cycle_elapsed):.3f}"
        )

    _print_result_summary("factor", _all_results(cycles, "factor"))
    _print_result_summary("runner_backfill", _all_results(cycles, "runner_backfill"))
    _print_result_summary("runner_bars", _all_results(cycles, "runner_bars"))
    _print_result_summary("health", _all_results(cycles, "health"))
    _print_result_summary("openapi_control", _all_results(cycles, "openapi"))
    _print_state_summary(samples)

    print("\n[interpretation]")
    print(
        "- p95/p99 here aggregate many requests across a bounded sustained run; do not use the "
        "small D08/D10/D12 waves as statistically meaningful p95 evidence."
    )
    print(
        "- the first cycle may include cold macro population; later cycles intentionally use new "
        "price score keys while sharing the naturally warm macro/date cache."
    )
    print(
        "- skipped cycles mean the local pending-cycle safety cap was reached; report them as a "
        "capacity signal, not as successful throughput."
    )
    print(
        "- use one data worker for exact process-local state interpretation; two-worker confirmation "
        "needs per-PID/log evidence because /__issue107/state is process-local."
    )
    print(
        "- compare the exact same duration/interval/concurrency/stagger/provider settings before and "
        "after a selected production change."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor-url", default="http://127.0.0.1:18004")
    parser.add_argument("--data-url", default="http://127.0.0.1:18001")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--cycle-interval", type=float, default=1.0)
    parser.add_argument("--max-pending-cycles", type=int, default=4)
    parser.add_argument("--settle-timeout", type=float, default=180.0)
    parser.add_argument("--factor-concurrency", type=int, default=4)
    parser.add_argument("--lookback-bars", type=int, default=720)
    parser.add_argument("--factor-timeout", type=float, default=180.0)
    parser.add_argument("--runner-runs", type=int, default=8)
    parser.add_argument("--runner-stagger-ms", type=float, default=0.0)
    parser.add_argument("--runner-timeout", type=float, default=60.0)
    parser.add_argument("--controls-per-cycle", type=int, default=2)
    parser.add_argument("--control-timeout", type=float, default=1.0)
    parser.add_argument("--control-start-delay", type=float, default=0.05)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    return parser


if __name__ == "__main__":
    asyncio.run(_run(_parser().parse_args()))
