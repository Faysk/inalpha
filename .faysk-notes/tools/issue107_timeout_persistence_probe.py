"""Contributor-only probe for issue #107: does server work survive client timeouts?

Target ``issue107_slow_data_app.py`` with **one Uvicorn worker** first. The wrapper exposes a
DB-free ``/__issue107/state`` endpoint and counts both the async provider waiter and, in ``thread``
mode, the underlying synchronous fake worker.

Cooperative async wait:

    ISSUE107_PROVIDER_MODE=async ISSUE107_PROVIDER_DELAY_S=5 \
      uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 1

Thread-backed wait (closer to FRED/other sync SDK wrappers):

    ISSUE107_PROVIDER_MODE=thread ISSUE107_PROVIDER_DELAY_S=5 \
      uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 1

Then:

    uv run python issue107_timeout_persistence_probe.py \
      --base-url http://127.0.0.1:18001 --attempts 4 --request-timeout 0.5 --settle-wait 6

No external market-data provider is contacted. Before creating timed-out backfill load, the probe
requires the current contributor wrapper state, fake Binance, scheduler isolation, and no
fake/blocked overlap for Binance.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import jwt
from inalpha_shared.config import get_settings


def _token() -> str:
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "issue107-timeout-probe",
            "email": "issue107-timeout@local.invalid",
            "iat": now,
            "exp": now + 3600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


async def _state(base_url: str) -> dict[str, Any]:
    # Use a fresh client/connection for observation so a timed-out request connection cannot affect
    # the control channel.
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0, trust_env=False) as client:
        response = await client.get("/__issue107/state")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"unexpected state response: {body!r}")
        return body


def _assert_safe_target(state: dict[str, Any]) -> None:
    fake = {
        item.strip().lower()
        for item in str(state.get("fake_venues", "")).split(",")
        if item.strip()
    }
    blocked = {
        item.strip().lower()
        for item in str(state.get("blocked_venues", "")).split(",")
        if item.strip()
    }
    if "binance" not in fake:
        raise RuntimeError(
            "unsafe timeout probe target: binance is not faked; "
            f"fake_venues={sorted(fake)}"
        )
    if "binance" in blocked:
        raise RuntimeError("unsafe timeout probe target: binance is reported both fake and blocked")
    if state.get("snapshot_scheduler_forced_disabled") != 1:
        raise RuntimeError(
            "unsafe timeout probe target: current contributor wrapper did not prove startup "
            "snapshot scheduler isolation"
        )


async def _timed_backfill(
    *,
    base_url: str,
    token: str,
    idx: int,
    timeout_s: float,
) -> tuple[str, float]:
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    symbol = f"TIMEOUT-{idx}-{uuid4().hex[:8]}/USDT"

    t0 = time.perf_counter()
    try:
        # Fresh client per attempt intentionally creates an independent TCP connection. This models
        # retries/new callers rather than an artificial local client-pool queue.
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s),
            trust_env=False,
        ) as client:
            response = await client.post(
                "/backfill/bars",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Trace-Id": f"issue107-timeout-{idx}-{uuid4().hex[:8]}",
                },
                json={
                    "venue": "binance",
                    "symbol": symbol,
                    "timeframe": "1h",
                    "from_ts": start.isoformat(),
                    "to_ts": end.isoformat(),
                },
            )
            return f"http_{response.status_code}", time.perf_counter() - t0
    except httpx.RequestError as exc:
        return type(exc).__name__, time.perf_counter() - t0


def _delta(before: dict[str, Any], after: dict[str, Any], key: str) -> int:
    return int(after.get(key, 0)) - int(before.get(key, 0))


def _print_state_delta(label: str, before: dict[str, Any], after: dict[str, Any]) -> None:
    print(
        f"{label} "
        f"mode={after.get('mode')} "
        f"provider_started={_delta(before, after, 'started')} "
        f"provider_active={after.get('active')} "
        f"provider_completed={_delta(before, after, 'completed')} "
        f"provider_cancelled={_delta(before, after, 'cancelled')} "
        f"provider_failed={_delta(before, after, 'failed')} "
        f"thread_started={_delta(before, after, 'thread_started')} "
        f"thread_active={after.get('thread_active')} "
        f"thread_completed={_delta(before, after, 'thread_completed')}"
    )


async def _run(args: argparse.Namespace) -> None:
    before = await _state(args.base_url)
    _assert_safe_target(before)
    print(
        "issue107_timeout_preflight=PASS "
        f"pid={before.get('pid')} mode={before.get('mode')} "
        f"fake_venues={before.get('fake_venues')}"
    )

    token = _token()
    results = await asyncio.gather(
        *[
            _timed_backfill(
                base_url=args.base_url,
                token=token,
                idx=idx,
                timeout_s=args.request_timeout,
            )
            for idx in range(args.attempts)
        ]
    )
    outcomes = Counter(name for name, _elapsed in results)
    print(f"client_outcomes={dict(outcomes)}")
    print("client_latencies_s=" + repr([round(elapsed, 3) for _name, elapsed in results]))

    # Give Uvicorn a very small observation window after all client-side timeout exceptions have
    # returned. If active provider work is still non-zero here, client timeout did not immediately
    # cancel the application work. In thread mode the async waiter may be cancelled while the
    # underlying sync thread remains active, which is why both sets of counters are recorded.
    await asyncio.sleep(args.observe_delay)
    immediate = await _state(args.base_url)
    print(f"state_after_client_timeouts={immediate}")
    _print_state_delta("immediate_delta", before, immediate)

    await asyncio.sleep(args.settle_wait)
    settled = await _state(args.base_url)
    print(f"state_after_settle={settled}")
    _print_state_delta("settled_delta", before, settled)

    print("\ninterpretation:")
    print(
        "- client timeout + provider_active>0 => the application/provider waiter outlived the "
        "caller deadline in this topology."
    )
    print(
        "- provider_cancelled rises and provider_active becomes 0 => cancellation reached the "
        "async waiter."
    )
    print(
        "- in thread mode, provider_cancelled can rise while thread_active stays >0. That means "
        "the coroutine stopped waiting but already-running synchronous SDK work did not stop."
    )
    print(
        "- thread_completed increasing only later demonstrates executor work surviving caller/request "
        "cancellation; retries can still contend for thread capacity even after DB/request capacity "
        "has been released."
    )
    print(
        "- preserve mixed results instead of treating cancellation as a single universal property "
        "for every connector."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18001")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--request-timeout", type=float, default=0.5)
    parser.add_argument("--observe-delay", type=float, default=0.1)
    parser.add_argument(
        "--settle-wait",
        type=float,
        default=6.0,
        help="Set this slightly longer than ISSUE107_PROVIDER_DELAY_S.",
    )
    return parser


if __name__ == "__main__":
    asyncio.run(_run(_parser().parse_args()))
