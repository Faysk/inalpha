"""Contributor-only no-load target verifier for Inalpha issue #107.

This script sends only contributor diagnostic GETs. It does not call /score, /backfill/bars, /bars,
or any external market-data provider.

Use it immediately before capacity probes to prove the local benchmark target is isolated.

Factor-driven mode verifies:

1. the data target is issue107_slow_data_app with every required venue faked;
2. the data wrapper has disabled the startup constituent scheduler and blocks non-fake OHLCV venues;
3. the factor target is issue107_factor_app;
4. factor's configured data_service_url equals the exact contributor data URL being checked;
5. macro can optionally be required for macro/mixed scenarios.

Data-only mode (``--data-only``) performs the data-side isolation checks without requiring a running
factor-service. Use it before runner-only and low-level data probes.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import httpx


def _norm(url: str) -> str:
    return url.strip().rstrip("/")


async def _json_get(base_url: str, path: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=2.0, trust_env=False) as client:
            response = await client.get(path)
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        raise RuntimeError(f"target check failed for {base_url}{path}: {exc}") from exc
    if not isinstance(body, dict):
        raise RuntimeError(f"unexpected object from {base_url}{path}: {body!r}")
    return body


async def _run(args: argparse.Namespace) -> None:
    data_url = _norm(args.data_url)
    factor_url = _norm(args.factor_url)

    data = await _json_get(data_url, "/__issue107/state")
    fake_venues = {
        item.strip().lower()
        for item in str(data.get("fake_venues", "")).split(",")
        if item.strip()
    }
    blocked_venues = {
        item.strip().lower()
        for item in str(data.get("blocked_venues", "")).split(",")
        if item.strip()
    }
    required_venues = {
        item.strip().lower()
        for item in args.required_venues.split(",")
        if item.strip()
    }
    if not required_venues:
        raise RuntimeError("--required-venues must contain at least one venue")

    missing = required_venues - fake_venues
    if missing:
        raise RuntimeError(
            "unsafe data target: not all required venues are fake; "
            f"missing={sorted(missing)} configured={sorted(fake_venues)}"
        )
    if required_venues & blocked_venues:
        raise RuntimeError(
            "unsafe data target: a required fake venue is also reported blocked; "
            f"overlap={sorted(required_venues & blocked_venues)}"
        )
    if data.get("snapshot_scheduler_forced_disabled") != 1:
        raise RuntimeError(
            "unsafe data target: contributor wrapper did not prove the startup constituent "
            "scheduler is forced disabled"
        )

    fake_bars_per_fetch = int(data.get("fake_bars_per_fetch", 0) or 0)
    if args.min_fake_bars_per_fetch > 0 and fake_bars_per_fetch < args.min_fake_bars_per_fetch:
        raise RuntimeError(
            "misleading data target: fake provider batch is smaller than required for this "
            f"scenario; current={fake_bars_per_fetch} required={args.min_fake_bars_per_fetch}"
        )

    print("issue107_data_target_check=PASS")
    print(f"data_pid={data.get('pid')}")
    print(f"data_url={data_url}")
    print(f"fake_venues={','.join(sorted(fake_venues))}")
    print(f"blocked_venues={','.join(sorted(blocked_venues))}")
    print(f"required_venues={','.join(sorted(required_venues))}")
    print("snapshot_scheduler_forced_disabled=true")
    print(f"fake_bars_per_fetch={fake_bars_per_fetch}")

    if args.data_only:
        print("issue107_target_check=PASS")
        print("factor_check=skipped_data_only")
        return

    factor = await _json_get(factor_url, "/__issue107/config")
    configured_data_url = _norm(str(factor.get("data_service_url", "")))
    expected_data_url = _norm(str(factor.get("expected_data_url", "")))

    if configured_data_url != data_url:
        raise RuntimeError(
            "unsafe factor routing: factor data_service_url does not match checked data target; "
            f"factor={configured_data_url!r} checked={data_url!r}"
        )
    if expected_data_url != data_url:
        raise RuntimeError(
            "unsafe factor wrapper expectation: expected_data_url does not match checked data target; "
            f"wrapper={expected_data_url!r} checked={data_url!r}"
        )
    if args.require_macro and factor.get("macro_enabled") is not True:
        raise RuntimeError("factor target has macro_enabled != true")

    print("issue107_target_check=PASS")
    print(f"factor_pid={factor.get('pid')}")
    print(f"factor_url={factor_url}")
    print(f"factor_data_service_url={configured_data_url}")
    print(f"macro_enabled={factor.get('macro_enabled')}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-url", default="http://127.0.0.1:18001")
    parser.add_argument("--factor-url", default="http://127.0.0.1:18004")
    parser.add_argument(
        "--required-venues",
        default="binance,fred",
        help="Comma-separated venues that must be replaced by the contributor fake.",
    )
    parser.add_argument(
        "--min-fake-bars-per-fetch",
        type=int,
        default=0,
        help="Optional minimum fake batch size required by the scenario; zero disables this check.",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Verify only the hardened data target; do not require/query factor-service.",
    )
    parser.add_argument("--require-macro", action="store_true")
    return parser


if __name__ == "__main__":
    asyncio.run(_run(_parser().parse_args()))
