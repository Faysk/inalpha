"""Contributor-only factor-service wrapper for Inalpha issue #107.

Run this instead of ``inalpha_factor.main:app`` during factor/mixed capacity probes.

Safety purpose
--------------
A factor probe can safely verify that the running factor process is configured to call the intended
local fake data-service *before* issuing any ``/score`` request. Without this guard, a contributor
could accidentally start factor with the ordinary ``DATA_SERVICE_URL=http://localhost:8001`` and
then send synthetic load that reaches real providers.

Recommended startup from ``services/factor``::

    DATA_SERVICE_URL=http://127.0.0.1:18001 \
    ISSUE107_EXPECT_DATA_URL=http://127.0.0.1:18001 \
    FACTOR_MACRO_ENABLED=true \
    uv run uvicorn issue107_factor_app:app --host 127.0.0.1 --port 18004 --workers 1

The wrapper:

- refuses to import/start if FactorSettings.data_service_url does not exactly match the expected
  contributor data URL after trivial trailing-slash normalization;
- exposes ``GET /__issue107/config`` so probes can verify the actual factor→data target;
- adds ``X-Issue107-Factor-Worker-Pid`` to responses for contributor diagnostics;
- does not change factor engine/cache/business behavior.

This file is contributor tooling. Do not commit it to the upstream PR as-is.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Request

from inalpha_factor.config import get_factor_settings
from inalpha_factor.main import app


def _norm(url: str) -> str:
    return url.strip().rstrip("/")


_settings = get_factor_settings()
_expected_data_url = _norm(
    os.environ.get("ISSUE107_EXPECT_DATA_URL", "http://127.0.0.1:18001")
)
_actual_data_url = _norm(_settings.data_service_url)

if _actual_data_url != _expected_data_url:
    raise RuntimeError(
        "unsafe issue107 factor target: FactorSettings.data_service_url does not match the "
        "expected contributor fake data-service; "
        f"actual={_actual_data_url!r} expected={_expected_data_url!r}"
    )


@app.middleware("http")
async def _issue107_factor_worker_header(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["X-Issue107-Factor-Worker-Pid"] = str(os.getpid())
    return response


@app.get("/__issue107/config", include_in_schema=False)
async def _issue107_config() -> dict[str, Any]:
    """Expose only non-secret contributor safety metadata."""
    return {
        "pid": os.getpid(),
        "data_service_url": _actual_data_url,
        "expected_data_url": _expected_data_url,
        "macro_enabled": bool(_settings.macro_enabled),
        "service_name": _settings.service_name,
    }
