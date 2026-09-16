# Issue #107 — Original TODO Disposition Against Current `main`

**Purpose:** keep the investigation anchored to what the maintainer actually asked for while accounting for changes that landed after the issue was written.

Issue #107 originally proposed several capacity controls as alternatives or combinations. This note records what is already present on current `main`, what is still absent, and what evidence would justify touching each item.

---

## 1. Original item: factor → data concurrency limit

Issue wording:

```text
limit factor→data concurrent fetches (example 6–8)
macro 18-series gather / panel N-symbol gather
```

### Current `main`

Panel has already changed materially:

```text
_PANEL_FETCH_CONCURRENCY = 16
panel fetches use bounded semaphore
panel reads use fresh=False
```

So the original panel backfill-storm shape is partly obsolete.

Macro remains different:

```text
18 unique FRED series for default full 1d/1wk macro set
asyncio.gather with no macro-specific semaphore
```

And current caches do not coalesce in-flight cold misses.

### Current disposition

```text
DO NOT blindly implement the issue's example 6–8 limit.
```

Measure:

- cold single live request;
- cold concurrent live requests;
- warm cache;
- actual factor→data request count;
- H8/H11 duplicate-work ratio;
- p95/error changes after primary data-side resource isolation.

Only then decide whether factor needs:

```text
bounded fan-out
single-flight
HTTP client reuse
or no change
```

---

## 2. Original item: data-service gate/queue for `/backfill/bars`

Issue wording:

```text
limit expensive backfills in flight + queue
```

### Current `main`

No service-level backfill admission gate is visible in the route.

However static review found a prerequisite concern that the original issue did not spell out:

```text
DBConn dependency is acquired before route body
→ current backfill retains DB lease across provider I/O
```

Therefore adding a semaphore **inside the current handler** can be too late:

```text
request gets DB connection
→ waits for semaphore
→ DB pool still consumed by queued request
```

### Current disposition

First reproduce H1.

If H1 is material, Candidate A is the smallest first intervention:

```text
short DB lookup lease
→ release
→ provider I/O
→ short persistence lease
```

Then rerun the same workload.

Only if provider/in-flight work still independently saturates the service should Candidate C (admission control) be selected.

Queue/busy semantics must be caller-compatible because factor, paper, research, dashboard and orchestration react differently to backfill failure/non-2xx.

---

## 3. Original item: live-runner throttling/staggering

Issue wording:

```text
stagger/throttle multiple polling symbols so runner does not compete with agent traffic
```

### Current `main`

Confirmed:

- one long-lived asyncio task per running strategy;
- fresh bar poll path still performs backfill + read;
- main poll loop has no randomized jitter;
- startup resumes persisted running runs and can create a warmup burst.

Refinement:

- not every resumed run launches the same factor load;
- intraday runs do not use macro factors;
- lineage-backed factor baseline requests may ask only a subset of factors;
- no-lineage daily/weekly snapshots can request the full macro set;
- cache state strongly affects burst size.

### Current disposition

Treat runner staggering as **H6**, not an assumed fix.

Measure steady-state polling and restart/resume separately.

Touch `paper/live_runner` only if overlap materially changes the representative failure curve after the data-service bottleneck is understood. This is a higher-risk scope than a data-local fix.

---

## 4. Original item: scale / connection-pool tuning

Issue wording:

```text
optional scaling / pool tuning
```

### Current `main`

Repository production topology currently specifies:

```text
data workers = 2
DB pool max_size = 10 per process
```

So theoretical container-wide DB checkouts are roughly 20, subject to uneven request distribution and one pool per worker.

### Current disposition

Do not use pool/worker inflation as the first fix.

Why:

```text
if provider waits retain DB leases,
more connections can simply allow more slow external work to retain more DB capacity
```

and

```text
more workers duplicate process-local caches/locks/semaphores/connectors
```

Scaling may be valid later, but only after the constrained resource is measured.

---

## 5. Original "retry already done" statement still matters

Issue explicitly says bounded factor GET retry already absorbs transient/reload blips but cannot solve sustained overload.

Current code still has that bounded retry.

Our plan therefore deliberately does **not** add more retries as a capacity fix.

Runtime work instead records whether existing retry turns one logical read into several physical requests under sustained slowness.

If so, that is amplification evidence, not justification for retry count inflation.

---

## 6. Verification target remains unchanged

The issue's acceptance target is still the right top-level target:

```text
agent + live runner concurrent workload
→ no DATA_SERVICE_UNREACHABLE
→ controlled p95 latency
```

Our additions are correctness guards around that target:

```text
refresh must make real data/timestamp progress
freshness must not be weakened
provider failures must not increase as the DB failure disappears
intentional backpressure, if ever introduced, must be explicit and measurable
```

---

## 7. Current mapping table

| Original #107 idea | Current-main status | First action | PR1 status |
|---|---|---|---|
| factor concurrency limit | panel already bounded; macro still bursty | measure macro/cold stampede | follow-up unless proven necessary |
| data backfill gate/queue | absent | first test DB lease ordering; gate only if still needed | possible follow-up / combined only with evidence |
| live-runner stagger | no jitter; restart burst exists | measure H6 | avoid PR1 unless causal |
| scale/pool tuning | 2 data workers, pool 10/worker | observe, do not tune first | out by default |
| bounded retry | already present | measure amplification only | no new retries |

---

## 8. Scope discipline

The investigation has uncovered more than the original issue text named, but the contribution should still answer the original operational problem rather than turn into a general data-platform rewrite.

Preferred decision tree:

```text
reproduce current failure class
→ identify first constrained resource
→ smallest fix at correct boundary
→ same workload before/after
→ stop if target is met
```

Do not implement every item in the issue just because it appears in the TODO list. The issue itself explicitly allows one or a combination; current code and measurements decide which are still necessary.