# Issue #107 — Candidate A Capacity-Decoupling Risk

**Status:** mandatory risk check if Candidate A is selected.

Candidate A can remove an unhealthy coupling:

```text
external provider latency
→ DB pool occupancy
```

But removing that coupling can also reveal a second constraint that the DB pool was accidentally masking:

```text
external provider concurrency / queue depth
```

This note exists specifically to enforce our rule:

> Solve #107 without moving the problem somewhere else.

---

## 1. The current DB pool acts as an accidental coarse admission limit

Today every `/backfill/bars` request acquires `DBConn` before provider I/O.

Per data worker:

```text
DB pool max_size = 10
```

So regardless of intent, current route ordering can indirectly limit the number of requests that reach the provider phase at once to roughly the number of DB leases available in that worker.

This is a **bad place** to enforce provider capacity because it starves unrelated DB reads, but it is still a real side effect of current architecture.

---

## 2. What Candidate A changes

After narrowing DB leases:

```text
request
→ short DB lookup
→ DB returned
→ provider wait/fetch
```

Many more requests can now coexist in the provider phase than the DB pool size.

That is exactly what the post-fix regression proves:

```text
test DB pool = 2
4 provider waits can coexist
/health still works
```

This is desired for DB isolation.

It also means:

```text
DB pool no longer protects providers from request bursts
```

which must be evaluated deliberately.

---

## 3. Provider behavior differs

### yfinance history

Current yfinance history path has a process-local `_FETCH_LOCK` and minimum request interval.

So Candidate A should not suddenly make ten Yahoo history calls execute concurrently in one worker. Instead it can change the queue shape from:

```text
requests queued while holding DB connections
```

to:

```text
requests queued behind Yahoo lock without holding DB connections
```

That is a clear resource-order improvement, though queue length/latency can still be large.

### FRED

Current FRED connector uses `asyncio.to_thread` around the synchronous FRED client and has no connector-local semaphore/admission gate.

For default live daily/weekly macro calculation:

```text
18 unique FRED series can be requested concurrently
```

With multiple cold callers and H8, actual calls can exceed 18 because same-key requests may duplicate before cache population.

Candidate A can therefore allow more FRED work to reach thread/provider capacity instead of stalling at DB checkout.

### Other synchronous connectors

Alpaca and other connector paths also use synchronous-library wrappers. Their actual safe concurrency/rate-limit behavior should be treated independently rather than assuming one global number works for every provider.

---

## 4. Success must include “no new upstream failure cliff”

Do not declare Candidate A successful only because:

```text
/health is fast
DATA_SERVICE_UNREACHABLE falls
```

Also compare before/after:

```text
peak provider in-flight
provider queue/wait
BARS_UPSTREAM_UNAVAILABLE
HTTP 429 from real upstreams in low-volume integration checks
HTTP 200 with zero/no progress
refresh timestamp progress
factor macro degradation count
backfill p95/p99
```

A result like this is **not** a complete win:

```text
DATA_SERVICE_UNREACHABLE: 20 → 0
but
upstream/provider failures: 0 → 30
```

That would only move the failure boundary.

---

## 5. Safe testing policy

Do **not** stress FRED/Yahoo/Alpaca to discover their limits.

Use fake providers for capacity sweeps.

The fake wrapper already reports:

```text
provider started/active/completed/cancelled
thread started/active/completed
```

So before/after can answer:

```text
How much provider concurrency did Candidate A expose?
```

Real-provider checks, if needed, stay low-volume and verify correctness/failure semantics rather than rate-limit thresholds.

---

## 6. Decision tree after Candidate A

```text
Candidate A selected
→ same fake workload
→ DB-backed requests recover?
    no  → Candidate A is insufficient/wrong; investigate
    yes → inspect provider-side behavior

provider work remains stable/bounded enough?
    yes → run representative mixed workload
          → issue target met?
              yes → STOP, keep PR small
              no  → identify next measured constraint

    no  → determine why
          ├─ legitimate per-request 18-way macro burst
          │    → evaluate Candidate B (bound macro fan-out)
          ├─ duplicate same-key cold macro work
          │    → evaluate H8 single-flight
          ├─ generic backfill external work overload
          │    → evaluate Candidate C admission control
          └─ provider-specific queue/rate policy
               → prefer provider-specific evidence/control
```

Do not preemptively implement all branches.

---

## 7. Why Candidate A can still be the correct first fix

The fact that DB starvation currently acts as an accidental limiter is not a reason to preserve it.

A database pool should not be the queue for external API calls.

The correct architecture is conceptually:

```text
external-work capacity governed by an external-work policy
DB capacity governed by short DB work
```

Candidate A can establish that separation.

If a real external-work limit is needed afterward, it can then be placed at the correct boundary without queued requests already consuming DB connections.

---

## 8. PR wording discipline

If Candidate A alone meets the issue target, describe it narrowly:

```text
The change prevents external backfill waits from retaining DB pool capacity.
```

Do not claim:

```text
The data-service now has unlimited/sufficient backfill capacity.
```

If provider concurrency becomes the next measured constraint, say so explicitly and either include a separately justified small control or leave it as follow-up depending on acceptance results.
