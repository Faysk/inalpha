# Issue #107 — Stage F thread-backed timeout persistence

**Scope:** contributor-only runtime evidence for H9/H10. No production code changed.

## Setup

- data worker: 1
- fake venue: `binance`
- provider mode: `thread`
- provider delay: 5s
- client attempts: 4
- client timeout: 0.5s
- dedicated DB: `inalpha_issue107`
- wrapper safety preflight: PASS

## Client-side result

All four callers timed out:

```text
client_outcomes={'ReadTimeout': 4}
client_latencies_s=[0.553, 0.545, 0.534, 0.523]
```

## Immediate server state after client timeouts

The application/provider waiters and the underlying synchronous fake workers were all still active:

```text
provider_started=4
provider_active=4
provider_completed=0
provider_cancelled=0
provider_failed=0

thread_started=4
thread_active=4
thread_completed=0

http_post_backfill_bars_inflight=4
pool_pool_size=4
pool_pool_available=0
```

This confirms that, in this real-TCP one-worker topology, client timeout did not promptly cancel either the request/provider waiter or the already-running thread-backed fake provider work.

## Settled state

After the 5s provider delay plus settle window:

```text
provider_started=4
provider_active=0
provider_completed=4
provider_cancelled=0
provider_failed=0

thread_started=4
thread_active=0
thread_completed=4

http_post_backfill_bars_inflight=0
pool_pool_available=4
pool_usage_ms=20264
```

The ~20.3s aggregate pool usage is consistent with four DB leases retained for roughly five seconds each while thread-backed provider work continued after the callers had already timed out.

## Interpretation

### H9

H9 is confirmed for this topology and mode:

```text
client timeout
→ request/provider work remains alive
→ DB capacity remains held
→ work finishes later
```

This mirrors the async fake-provider result and strengthens the retry-amplification model: a retry can overlap older server work that survived the caller deadline.

This does **not** by itself prove that production factor retries create a measurable retry storm; it proves the prerequisite persistence behavior exists.

### H10

This run confirms persistence of already-running thread-backed work after caller timeout:

```text
thread_active=4 after all four client ReadTimeouts
→ thread_completed=4 only later
```

However, with only four attempts, this run does **not** establish default-executor saturation or H10 production materiality. It is a cancellation/persistence control, not an executor-capacity boundary test.

## Decision impact

- H1 remains the measured first scarce-resource failure: DB leases are retained across provider waits.
- H9 increases the risk of transient overload amplification because timed-out requests can keep their DB/provider work alive while callers retry.
- Thread-backed providers can also keep executor work alive after caller timeout, but H10 should not be promoted to a production fix without a separate capacity/materiality result.
- Candidate A remains the leading narrow production candidate, still not applied at this stage.
