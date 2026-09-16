"""Contributor-only sustained acceptance probe for Inalpha issue #107.

This is the acceptance-oriented companion to ``issue107_sustained_mixed_probe.py``.
It reuses that tool's request/result helpers but adds two properties needed before using
sustained results as issue-level evidence:

1. explicit factor symbol shape (``unique`` cross-sectional vs ``same`` H11 stress);
2. bounded scheduling/settling that preserves partial evidence instead of hiding it when the
   service cannot drain all work before the settle timeout.

No production code is changed. All target/provider safety checks are inherited from the base
contributor probe and must pass before any load is scheduled.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

import httpx

import issue107_sustained_mixed_probe as base


async def _cycle(
    *,
    cycle: int,
    args: argparse.Namespace,
    token: str,
    factor_ids: list[str],
    factor_client: httpx.AsyncClient,
    control_client: httpx.AsyncClient,
    runs: list[base.SimRun],
) -> base.CycleResult:
    started = time.perf_counter()

    if args.factor_symbol_mode == "same":
        symbols = [f"ISSUE107-SOAK-{cycle}/USDT"] * args.factor_concurrency
    else:
        symbols = [
            f"ISSUE107-SOAK-{cycle}-{idx}/USDT"
            for idx in range(args.factor_concurrency)
        ]

    factor_tasks = [
        asyncio.create_task(
            base._factor_one(
                factor_client,
                token=token,
                symbol=symbol,
                factor_ids=factor_ids,
                cycle=cycle,
                idx=idx,
                lookback_bars=args.lookback_bars,
            )
        )
        for idx, symbol in enumerate(symbols)
    ]

    runner_tasks = [
        asyncio.create_task(
            base._runner_one(
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
            base._control_one(
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
            base._control_one(
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

    return base.CycleResult(
        cycle=cycle,
        elapsed_s=time.perf_counter() - started,
        factor=factor_results,
        runner_backfill=[pair[0] for pair in runner_pairs],
        runner_bars=[pair[1] for pair in runner_pairs],
        health=health,
        openapi=openapi,
    )


async def _collect_finished(
    tasks: list[asyncio.Task[base.CycleResult]],
    *,
    settle_timeout: float,
) -> tuple[list[base.CycleResult], int, list[str]]:
    if not tasks:
        return [], 0, []

    done, pending = await asyncio.wait(tasks, timeout=settle_timeout)
    cycles: list[base.CycleResult] = []
    cycle_errors: list[str] = []

    for task in done:
        try:
            cycles.append(task.result())
        except Exception as exc:
            cycle_errors.append(type(exc).__name__)

    pending_count = len(pending)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    return sorted(cycles, key=lambda item: item.cycle), pending_count, cycle_errors


async def _run(args: argparse.Namespace) -> None:
    if args.duration <= 0 or args.cycle_interval <= 0:
        raise ValueError("--duration and --cycle-interval must be > 0")
    if args.factor_concurrency < 1:
        raise ValueError("--factor-concurrency must be >= 1")
    if args.controls_per_cycle < 1:
        raise ValueError("--controls-per-cycle must be >= 1")
    if args.max_pending_cycles < 1:
        raise ValueError("--max-pending-cycles must be >= 1")

    args.data_url = base._norm(args.data_url)
    args.factor_url = base._norm(args.factor_url)
    data_state, factor_state = await base._preflight(args)
    token = base._token()
    factor_ids = await base._macro_ids(args.factor_url, token)
    runs = base._build_runs(args.runner_runs)

    print("issue107_sustained_acceptance_preflight=PASS")
    print(f"data_pid={data_state.get('pid')} factor_pid={factor_state.get('pid')}")
    print(f"macro_factor_ids={len(factor_ids)}")
    print(
        "configuration "
        f"duration={args.duration}s interval={args.cycle_interval}s "
        f"factor_symbol_mode={args.factor_symbol_mode} "
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
        base._sample_state(args.data_url, stop_sampling, samples, args.sample_interval)
    )

    cycle_tasks: list[asyncio.Task[base.CycleResult]] = []
    skipped_cycles = 0
    started_cycles = 0
    benchmark_start = time.perf_counter()
    slot = 0

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
        try:
            while True:
                scheduled_at = benchmark_start + slot * args.cycle_interval
                if scheduled_at - benchmark_start >= args.duration:
                    break

                now = time.perf_counter()
                if now < scheduled_at:
                    await asyncio.sleep(scheduled_at - now)

                # Re-check after sleep so a delayed scheduler never injects a cycle beyond duration.
                if time.perf_counter() - benchmark_start >= args.duration:
                    break

                pending = sum(1 for task in cycle_tasks if not task.done())
                if pending >= args.max_pending_cycles:
                    skipped_cycles += 1
                else:
                    cycle_tasks.append(
                        asyncio.create_task(
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
                    )
                    started_cycles += 1
                slot += 1

            cycles, pending_after_settle, cycle_errors = await _collect_finished(
                cycle_tasks,
                settle_timeout=args.settle_timeout,
            )
        finally:
            stop_sampling.set()
            await sampler

    total_elapsed = time.perf_counter() - benchmark_start

    print("\n[schedule]")
    print(f"cycles_started={started_cycles}")
    print(f"cycles_completed={len(cycles)}")
    print(f"cycles_skipped_pending_cap={skipped_cycles}")
    print(f"cycles_pending_after_settle={pending_after_settle}")
    print(f"cycle_task_errors={cycle_errors}")
    print(f"benchmark_elapsed_s={total_elapsed:.3f}")
    if cycles:
        cycle_elapsed = [item.elapsed_s for item in cycles]
        p50 = base._percentile(cycle_elapsed, 0.50)
        p95 = base._percentile(cycle_elapsed, 0.95)
        assert p50 is not None and p95 is not None
        print(
            f"cycle_elapsed_s min={min(cycle_elapsed):.3f} p50={p50:.3f} "
            f"p95={p95:.3f} max={max(cycle_elapsed):.3f}"
        )

    base._print_result_summary("factor", base._all_results(cycles, "factor"))
    base._print_result_summary("runner_backfill", base._all_results(cycles, "runner_backfill"))
    base._print_result_summary("runner_bars", base._all_results(cycles, "runner_bars"))
    base._print_result_summary("health", base._all_results(cycles, "health"))
    base._print_result_summary("openapi_control", base._all_results(cycles, "openapi"))
    base._print_state_summary(samples)

    print("\n[acceptance_interpretation]")
    print(
        "- factor_symbol_mode=unique is the primary cross-sectional shape for issue-level sustained "
        "evidence; same is an H11 stress control."
    )
    print(
        "- cycles_skipped_pending_cap and cycles_pending_after_settle are capacity/backlog signals; "
        "they must not be counted as successful throughput."
    )
    print(
        "- zero runner backfill progress can be legitimate during repeated polling inside one market "
        "interval; interpret it with GET /bars results and provider/timestamp evidence."
    )
    print(
        "- preserve the exact duration/interval/concurrency/stagger/provider settings for before/after."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor-url", default="http://127.0.0.1:18004")
    parser.add_argument("--data-url", default="http://127.0.0.1:18001")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--cycle-interval", type=float, default=1.0)
    parser.add_argument("--max-pending-cycles", type=int, default=4)
    parser.add_argument("--settle-timeout", type=float, default=180.0)
    parser.add_argument("--factor-symbol-mode", choices=("unique", "same"), default="unique")
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
