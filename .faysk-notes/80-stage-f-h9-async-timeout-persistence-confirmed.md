# Issue #107 — Stage F H9 async timeout persistence confirmed

## Scope

Contributor-only baseline evidence on current main. No production change applied.

- one data worker
- dedicated DB: `inalpha_issue107`
- hardened contributor wrapper
- fake venue: Binance only
- provider mode: async
- provider delay: 5 s
- 4 concurrent backfills
- client timeout: 0.5 s

## Result

All four client requests timed out with `ReadTimeout` around 0.53–0.56 s.

Immediately after the client-side timeouts, the server still reported:

```text
provider_started=4
provider_active=4
provider_completed=0
provider_cancelled=0
http_post_backfill_bars_inflight=4
pool_pool_size=4
pool_pool_available=0
```

After the settle window, the server reported:

```text
provider_active=0
provider_completed=4
provider_cancelled=0
http_post_backfill_bars_inflight=0
pool_pool_available=4
pool_usage_ms=20294
```

The server logs show all four fake provider waits completed and all four `/backfill/bars` handlers finished with HTTP 200 roughly five seconds after they started, even though the clients had already timed out around 0.5 s.

## Interpretation

H9 is confirmed for this one-worker real-TCP async-provider topology:

```text
client timeout/disconnect
!= immediate cancellation of application/provider work
```

The abandoned server work survived the caller deadline and continued through provider completion and persistence.

This materially strengthens the retry-amplification model for issue #107: if a caller retries after its timeout, the older request can still occupy data-service resources while the new attempt begins.

It also reinforces H1 rather than replacing it. `pool_usage_ms=20294` is approximately four requests holding DB capacity for about five seconds each, consistent with the current `/backfill/bars` lifetime retaining DB leases while the fake provider is awaited.

## Scope caution

This does **not** prove all connectors have identical cancellation behavior. Thread-backed connectors require a separate control because an asyncio waiter and an already-running synchronous executor task have different cancellation semantics.

No production disconnect/cancellation policy is selected from this result alone.

## Decision impact

Current evidence now supports:

```text
H1 material + H9 true
→ stale timed-out requests can overlap caller retries
→ Candidate A remains the smallest leading production candidate for protecting DB capacity
→ thread/provider capacity still needs measurement before considering admission or executor changes
```

Next: Stage F thread-backed control to distinguish request/provider waiter persistence from underlying executor-thread persistence (H10 shape).
