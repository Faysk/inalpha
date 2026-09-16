"""Contributor-only local load probe for Inalpha issue #107.

Intended target: ``issue107_slow_data_app.py`` running on localhost with one or two workers.
The fake provider means this script never stress-tests Binance/Yahoo/FRED.

Example:

    uv run python issue107_load_probe.py --base-url http://127.0.0.1:18001 \
      --backfills 40 --health-probes 10 --health-timeout 1.0

The script preserves concrete HTTPX exception types instead of collapsing everything into
``DATA_SERVICE_UNREACHABLE``. It probes both DB-backed ``/health`` and non-DB ``/openapi.json``
while backfills are blocked so we can distinguish DB-pool starvation from general server/event-loop
starvation. When the contributor wrapper is used it also records ``X-Issue107-Worker-Pid`` and
samples the wrapper's DB-free ``/__issue107/state`` endpoint, including Psycopg pool stats.
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
from uuid import uuid4

import httpx
import jwt
from inalpha_shared.config import get_settings


@dataclass
class Result:
    kind: str
    latency_s: float
    status: int | None = None
    error_type: str | None = None
    code: str | None = None
    bars_fetched: int | None = None
    bars_inserted: int | None = None
    worker_pid: str | None = None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


def _token() -> str:
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "issue107-local-probe",
            "email": "issue107@local.invalid",
            "iat": now,
            "exp": now + 3600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _response_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except Exception:
        return None
    return body.get("code") if isinstance(body, dict) else None


def _worker_pid(response: httpx.Response) -> str | None:
    return response.headers.get("X-Issue107-Worker-Pid")


async def _backfill_one(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    idx: int,
) -> Result:
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    trace_id = f"issue107-bf-{idx}-{uuid4().hex[:8]}"
    symbol = f"ISSUE107-{idx}-{uuid4().hex[:10]}/USDT"
    request_headers = {**headers, "X-Trace-Id": trace_id}

    t0 = time.perf_counter()
    try:
        response = await client.post(
            "/backfill/bars",
            headers=request_headers,
            json={
                "venue": "binance",
                "symbol": symbol,
                "timeframe": "1h",
                "from_ts": start.isoformat(),
                "to_ts": end.isoformat(),
            },
        )
        elapsed = time.perf_counter() - t0
        bars_fetched: int | None = None
        bars_inserted: int | None = None
        if response.status_code < 400:
            try:
                body = response.json()
                if isinstance(body, dict):
                    bars_fetched = body.get("bars_fetched")
                    bars_inserted = body.get("bars_inserted")
            except Exception:
                pass
        return Result(
            kind="backfill",
            latency_s=elapsed,
            status=response.status_code,
            code=_response_code(response),
            bars_fetched=bars_fetched,
            bars_inserted=bars_inserted,
            worker_pid=_worker_pid(response),
        )
    except httpx.RequestError as exc:
        return Result(
            kind="backfill",
            latency_s=time.perf_counter() - t0,
            error_type=type(exc).__name__,
        )


async def _probe_one(
    client: httpx.AsyncClient,
    *,
    kind: str,
    path: str,
    idx: int,
    timeout_s: float,
) -> Result:
    t0 = time.perf_counter()
    try:
        response = await client.get(
            path,
            headers={"X-Trace-Id": f"issue107-{kind}-{idx}-{uuid4().hex[:8]}"},
            timeout=timeout_s,
        )
        return Result(
            kind=kind,
            latency_s=time.perf_counter() - t0,
            status=response.status_code,
            code=_response_code(response),
            worker_pid=_worker_pid(response),
        )
    except httpx.RequestError as exc:
        return Result(
            kind=kind,
            latency_s=time.perf_counter() - t0,
            error_type=type(exc).__name__,
        )


async def _sample_state(base_url: str, count: int) -> list[dict[str, Any]]:
    """Collect DB-free per-worker snapshots using fresh short-lived connections.

    Uvicorn worker selection is not guaranteed, so these are *observed* workers only. Multiple fresh
    connections increase the chance of seeing both workers without pretending the sample is exhaustive.
    """
    samples: list[dict[str, Any]] = []
    for _ in range(count):
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=1.5,
                trust_env=False,
                headers={"Connection": "close"},
            ) as client:
                response = await client.get("/__issue107/state")
                if response.status_code == 200:
                    body = response.json()
                    if isinstance(body, dict):
                        samples.append(body)
        except httpx.RequestError:
            pass
    return samples


def _print_state_samples(label: str, samples: list[dict[str, Any]]) -> None:
    print(f"\n[{label}_state_samples]")
    if not samples:
        print("no state samples")
        return

    by_pid: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        by_pid.setdefault(str(sample.get("pid", "unknown")), []).append(sample)

    print(f"observed_pids={sorted(by_pid)} samples={len(samples)}")
    for pid, pid_samples in sorted(by_pid.items()):
        latest = pid_samples[-1]
        interesting = {
            key: latest.get(key)
            for key in (
                "mode",
                "active",
                "started",
                "completed",
                "cancelled",
                "failed",
                "thread_active",
                "thread_started",
                "thread_completed",
                "pool_pool_min",
                "pool_pool_max",
                "pool_pool_size",
                "pool_pool_available",
                "pool_requests_waiting",
                "pool_requests_num",
                "pool_requests_queued",
                "pool_requests_wait_ms",
                "pool_requests_errors",
                "pool_usage_ms",
            )
            if key in latest
        }
        print(f"pid={pid} latest={interesting}")


async def _run(args: argparse.Namespace) -> None:
    token = _token()
    headers = {"Authorization": f"Bearer {token}"}
    limits = httpx.Limits(
        max_connections=max(100, args.backfills + args.health_probes * 2 + 20),
        max_keepalive_connections=40,
    )
    timeout = httpx.Timeout(args.backfill_timeout)

    pre_state = await _sample_state(args.base_url, args.state_samples)
    _print_state_samples("pre", pre_state)

    async with httpx.AsyncClient(
        base_url=args.base_url,
        timeout=timeout,
        limits=limits,
        trust_env=False,
    ) as client:
        # Confirm the target is alive before load. These results are intentionally not included in
        # the pressure statistics.
        pre_health = await client.get("/health", timeout=2.0)
        pre_control = await client.get("/openapi.json", timeout=2.0)
        print(
            "pre_health "
            f"status={pre_health.status_code} pid={_worker_pid(pre_health)} body={pre_health.text}"
        )
        print(
            "pre_openapi "
            f"status={pre_control.status_code} pid={_worker_pid(pre_control)}"
        )

        backfill_tasks = [
            asyncio.create_task(_backfill_one(client, headers, idx))
            for idx in range(args.backfills)
        ]

        # Give requests enough time to enter route/provider wait before control probes begin.
        await asyncio.sleep(args.probe_start_delay)

        under_load_state = await _sample_state(args.base_url, args.state_samples)
        _print_state_samples("under_load", under_load_state)

        health_results: list[Result] = []
        control_results: list[Result] = []
        for idx in range(args.health_probes):
            # Non-DB control first. If this remains fast while health times out, the process/event
            # loop is alive and the evidence points more specifically at DB-backed capacity.
            control_results.append(
                await _probe_one(
                    client,
                    kind="openapi",
                    path="/openapi.json",
                    idx=idx,
                    timeout_s=args.health_timeout,
                )
            )
            health_results.append(
                await _probe_one(
                    client,
                    kind="health",
                    path="/health",
                    idx=idx,
                    timeout_s=args.health_timeout,
                )
            )
            if idx + 1 < args.health_probes:
                await asyncio.sleep(args.health_interval)

        backfill_results = await asyncio.gather(*backfill_tasks)

    post_state = await _sample_state(args.base_url, args.state_samples)
    _print_state_samples("post", post_state)

    _print_summary("openapi_control", control_results)
    _print_summary("health", health_results)
    _print_summary("backfill", backfill_results)

    progress = [
        r
        for r in backfill_results
        if r.status is not None and r.status < 400 and (r.bars_fetched or 0) > 0
    ]
    print(
        "backfill_data_progress "
        f"successful_with_rows={len(progress)}/{len(backfill_results)}"
    )

    health_failures = sum(
        1 for r in health_results if r.error_type is not None or (r.status or 0) >= 400
    )
    control_failures = sum(
        1 for r in control_results if r.error_type is not None or (r.status or 0) >= 400
    )
    print(
        "isolation_signal "
        f"health_failures={health_failures} openapi_failures={control_failures}"
    )


def _print_summary(name: str, results: list[Result]) -> None:
    latencies = [r.latency_s for r in results]
    statuses = Counter(str(r.status) for r in results if r.status is not None)
    errors = Counter(r.error_type for r in results if r.error_type is not None)
    codes = Counter(r.code for r in results if r.code is not None)
    pids = Counter(r.worker_pid for r in results if r.worker_pid is not None)

    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)
    p99 = _percentile(latencies, 0.99)

    print(f"\n[{name}]")
    print(f"count={len(results)}")
    print(f"status_counts={dict(statuses)}")
    print(f"error_type_counts={dict(errors)}")
    print(f"error_code_counts={dict(codes)}")
    print(f"worker_pid_counts={dict(pids)}")
    print(
        "latency_s "
        f"p50={p50:.3f} p95={p95:.3f} p99={p99:.3f} max={max(latencies):.3f}"
        if latencies and p50 is not None and p95 is not None and p99 is not None
        else "latency_s no-results"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18001")
    parser.add_argument("--backfills", type=int, default=40)
    parser.add_argument("--backfill-timeout", type=float, default=30.0)
    parser.add_argument("--health-probes", type=int, default=10)
    parser.add_argument("--health-timeout", type=float, default=1.0)
    parser.add_argument("--health-interval", type=float, default=0.25)
    parser.add_argument("--probe-start-delay", type=float, default=0.5)
    parser.add_argument(
        "--state-samples",
        type=int,
        default=8,
        help="Fresh DB-free state requests per phase; observed worker coverage is best-effort.",
    )
    return parser


if __name__ == "__main__":
    asyncio.run(_run(_parser().parse_args()))
