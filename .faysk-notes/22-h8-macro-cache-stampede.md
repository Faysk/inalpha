# Issue #107 — H8: Cold Macro Cache Stampede

**Status:** new measured-candidate hypothesis from static review. Not yet a root cause.

---

## 1. Why this matters

Current live factor score/snapshot behavior uses two process-local caches in `services/factor/src/inalpha_factor/engine.py`:

- panel/result cache for live score/snapshot;
- macro-series cache with `_MACRO_CACHE_TTL_S = 3600`.

The cache itself is shared at module level across request-scoped `FactorEngine` instances.

However cache population has no per-key single-flight/in-flight registry.

Current macro-series path is effectively:

```text
request A: cache miss ─┐
request B: cache miss ─┼→ each independently calls _fetch_df(... fresh=True)
request C: cache miss ─┘

later:
all successful callers put the same key into cache
```

So the cache prevents **later sequential** duplicate work but does not prevent a **cold-cache stampede** when multiple requests arrive before the first one finishes.

---

## 2. Why the multiplier can be large

A live daily/weekly score or snapshot can request roughly 18 required FRED series and `_compute_macro()` gathers them concurrently.

For one cold request:

```text
~18 macro series
→ ~18 fresh data-service fetch paths
```

For `N` concurrent cold requests with overlapping macro requirements, absence of single-flight can theoretically produce approximately:

```text
N × 18 macro-series fetch attempts
```

before any of them populate the shared cache.

This is a burst multiplier, not a claim that every real request always asks for all 18 series.

---

## 3. Why this is especially relevant to #107

The issue itself names macro fan-out as part of the capacity chain.

Current code has added an hour-long macro cache since then, which reduces steady-state pressure, but a TTL cache alone does not remove cold-start/expiry bursts.

Representative cold-cache moments include:

- factor service restart;
- first live 1d/1wk request of the day/window;
- macro cache expiry;
- several agent requests arriving concurrently before first fill completes.

There is also a paper-service startup interaction:

```text
paper restart
→ resume multiple live runs
→ each run builds independently
→ capture_factor_baseline(...)
→ factor score/snapshot requests can overlap
```

If those requests are daily/weekly and macro-enabled while factor cache is cold, the overlap can amplify the macro burst.

Later periodic `FactorPatrol.patrol_once()` is less dangerous because it iterates grouped score calls sequentially, but startup baseline capture occurs from independent live-runner tasks.

---

## 4. Existing cache test gap

Current `services/factor/tests/test_cache.py` verifies the sequential behavior:

```text
first macro-series request → fetch
second request same key → cache hit
```

That proves the cache works after population.

It does **not** test:

```text
several callers miss the same key simultaneously
```

Therefore H8 can be tested deterministically without a data-service or real FRED key.

A contributor-only diagnostic is prepared at:

```text
.faysk-notes/tools/test_macro_cache_stampede_draft.py
```

---

## 5. What the diagnostic should prove

Control:

```text
request 1 completes and populates macro key
→ request 2 same key
→ only one _fetch_df call total
```

Pressure case:

```text
6 request-scoped FactorEngine instances
→ same macro series/date key
→ all start concurrently
→ fake _fetch_df blocks before cache put
```

Expected current behavior:

```text
all 6 reach _fetch_df
fetch_count == 6
```

That proves the cache has no same-key in-flight coalescing.

It still does **not** prove H8 is materially responsible for production #107. The service-level mixed benchmark must show that concurrent cold factor requests actually occur and matter.

---

## 6. Bounded fan-out vs single-flight

These are different controls.

### Per-request semaphore

```text
18 required series
→ allow e.g. K at a time
```

Effect:

- bounds one request's burst;
- does not eliminate duplicate same-key work across concurrent requests.

### Same-key single-flight

```text
request A starts DGS10 fetch
request B wants same DGS10/date
→ B awaits A instead of starting another fetch
```

Effect:

- eliminates duplicate work for the same cache key;
- does not cap different series/keys.

Depending on runtime evidence, one, both, or neither may be justified.

Do not add both by default.

---

## 7. Candidate E if H8 is material

A minimal factor-side single-flight design would likely be module-local because production factor currently runs one worker.

Conceptually:

```text
_macro_inflight[key] -> Task/Future

cache hit
→ return

existing in-flight key
→ await leader

no in-flight key
→ create leader fetch
→ on success cache result
→ always remove in-flight entry
```

Correctness questions before implementation:

- follower cancellation must not cancel the leader for everyone;
- leader exception must not poison cache;
- in-flight entry must always be removed;
- cache TTL semantics must remain unchanged;
- historical `fresh=False` must not be accidentally coalesced into live cache semantics;
- process-local limitation must be documented if factor is ever scaled to multiple workers.

This would be a **factor-side** change and may warrant a separate commit/PR from a data-service-local Candidate A.

---

## 8. Decision gate

Treat H8 as material only if all of the following are observed:

1. concurrent cold live factor calls occur in a representative #107 workload;
2. provider/data calls materially exceed unique macro cache keys;
3. duplicate macro work contributes to p95/errors or backfill pressure;
4. Candidate A alone does not already satisfy the issue target, or H8 remains a clear independent multiplier.

If the same workload passes after Candidate A, stop. Do not add single-flight just because the static code permits a stampede.
