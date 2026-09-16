"""Contributor-only probe for issue #107: does server work survive client timeouts?

Target ``issue107_slow_data_app.py`` with **one Uvicorn worker** first. The wrapper exposes a
DB-free ``/__issue107/state`` endpoint and counts fake-provider starts/completions/cancellations.

Example:

    ISSUE107_PROVIDER_DELAY_S=5 uv run uvicorn issue107_slow_data_app:app \
      --host 127.0.0.1 --port 18001 --workers 1

    uv run python issue107_timeout_persistence_probe.py \
      --base-url http://127.0.0.1:18001 --attempts 4 --request-timeout 0.5 --settle-wait 6

No external market-data provider is contacted.
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


async def _run(args: argparse.Namespace) -> None:
    before = await _state(args.base_url)
    print(f"state_before={before}")

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
    print(
        "client_latencies_s="
        + repr([round(elapsed, 3) for _name, elapsed in results])
    )

    # Give Uvicorn a very small observation window after all client-side timeout exceptions have
    # returned. If active provider work is still non-zero here, client timeout did not immediately
    # cancel the application work.
    await asyncio.sleep(args.observe_delay)
    immediate = await _state(args.base_url)
    print(f"state_after_client_timeouts={immediate}")
    print(
        "immediate_delta "
        f"started={_delta(before, immediate, 'started')} "
        f"active={immediate.get('active')} "
        f"completed={_delta(before, immediate, 'completed')} "
        f"cancelled={_delta(before, immediate, 'cancelled')} "
        f"failed={_delta(before, immediate, 'failed')}"
    )

    await asyncio.sleep(args.settle_wait)
    settled = await _state(args.base_url)
    print(f"state_after_settle={settled}")
    print(
        "settled_delta "
        f"started={_delta(before, settled, 'started')} "
        f"active={settled.get('active')} "
        f"completed={_delta(before, settled, 'completed')} "
        f"cancelled={_delta(before, settled, 'cancelled')} "
        f"failed={_delta(before, settled, 'failed')}"
    )

    print("\ninterpretation:")
    print(
        "- ReadTimeout/other client timeout + active>0 immediately afterward => server provider "
        "work outlived the client deadline in this topology."
    )
    print(
        "- cancelled delta ~= started delta => disconnect/cancellation propagated into the fake "
        "provider wait."
    )
    print(
        "- completed increases only after clients already timed out => retries can overlap with "
        "older still-running work; measure this before claiming retry amplification."
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
