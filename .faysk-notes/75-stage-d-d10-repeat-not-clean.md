# Stage D — D10 repeated warm continuation after failed restart

Status: contributor-only runtime evidence for issue #107. This run is useful for repeatability, but it is **not** the canonical clean D10 because the old Uvicorn process remained bound to port 18001.

## What happened

A fresh Uvicorn process was started with the Windows Selector loop, but bind failed with WinError 10048 because the previous benchmark server was still listening on `127.0.0.1:18001`.

The subsequent target check proved requests were still reaching the old process:

```text
pid=57784
started=18
completed=18
pool_pool_size=10
pool_pool_available=10
```

Therefore the file named `12-stage-D-D10-clean.txt` is not a clean-start run and must not be labeled canonical.

## Repeated D10 result

Even though the process was warm, the pressure signal reproduced almost identically:

```text
under load:
provider active          = 10
pool_pool_size           = 10
pool_pool_available      = 0

openapi:
10/10 HTTP 200
p95 ~0.010 s

health:
7/10 HTTP 200
3/10 ReadTimeout at 1 s
p95 ~1.019 s

backfill:
10/10 HTTP 200
p95 ~5.109 s
```

Cumulative pool counters changed from:

```text
pool_requests_wait_ms  10777 -> 21022  (+10245 ms)
pool_usage_ms          91501 -> 142316 (+50815 ms)
```

The `pool_usage_ms` increment is again approximately 10 retained DB leases × 5 seconds of fake provider wait, strongly consistent with H1.

## Interpretation

This is strong **repeatability evidence** for the normal-pool-size failure mode:

```text
10 concurrent backfills
→ 10/10 DB pool slots retained while provider waits
→ DB-backed /health begins timing out
→ non-DB /openapi remains fast
→ backfills themselves still complete successfully
```

However, because the process was not restarted, this run must remain classified as warm continuation evidence.

## Next action

Identify and stop only the process currently listening on local port 18001, verify the port is free, start a fresh contributor wrapper process, verify counters reset (`started=0`, pool size near min=2), then rerun D10 once as canonical clean-start evidence.

No production source change was made and Candidate A remains unapplied.
