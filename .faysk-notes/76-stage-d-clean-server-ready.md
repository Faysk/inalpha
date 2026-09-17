# Stage D — clean one-worker benchmark server verified

Status: contributor-only runtime setup evidence for issue #107.

## Result

A fresh issue-107 data benchmark server was started successfully on Windows using the contributor PowerShell launcher and an explicit Selector event loop.

Observed server identity/state:

```text
pid=60968
mode=async
fake_venues=binance
blocked_venues=baostock,yfinance
snapshot_scheduler_forced_disabled=1
fake_bars_per_fetch=1
active=0
started=0
completed=0
cancelled=0
failed=0
pool_initialized=1
pool_pool_min=2
pool_pool_max=10
pool_pool_size=2
pool_pool_available=2
pool_requests_waiting=0
```

Uvicorn startup completed and bound successfully to `127.0.0.1:18001`.

The server log confirmed:

```text
issue107_provider_isolation_installed ... fake_venues=['binance'] ... mode=async delay_s=5 bars_per_fetch=1 snapshot_scheduler_forced_disabled=true
Application startup complete.
Uvicorn running on http://127.0.0.1:18001
```

This is the first clean Stage-D server state after the earlier warm-process contamination / port-reuse attempts. The previous PID 57784 is no longer serving this benchmark target.

## Safety classification

- dedicated benchmark target: yes
- real Binance provider used: no; Binance is replaced by the deterministic fake
- other OHLCV venues: blocked by contributor harness
- constituent snapshot scheduler: forced disabled
- production source changed: no
- candidate fix applied: no

## Next step

Run the canonical D10 capacity point from this clean process and save it under a new evidence filename so earlier non-canonical warm attempts remain preserved.
