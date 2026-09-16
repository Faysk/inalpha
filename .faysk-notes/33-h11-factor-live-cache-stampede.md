# Issue #107 — H11: Full Live Factor Cache Stampede

**Status:** static hypothesis with a contributor-only pure unit diagnostic prepared.  
**Scope:** factor-side amplification only; do not fold into the first #107 production fix unless runtime materiality is shown.

H8 covered the macro-series cache specifically. This note generalizes the same observation to the **whole live factor score cache**.

---

## 1. Current cache shape

Factor request engines are request-scoped, but the live cache is module-level:

```text
FactorEngine per request
        ↓
module-level _panel_cache
```

The cache is a single LRU with:

```text
_PANEL_CACHE_MAX = 64
```

It stores both:

- normal live score/snapshot cache entries;
- macro-series entries using `("__macro__", ...)` keys.

The cache functions are ordinary synchronous get/put operations.

There is no in-flight registry around a cache miss.

---

## 2. Whole-score miss path

For a live score/snapshot request, current logic is effectively:

```text
cache get(score key)
        ↓ miss
_fetch_df(main price, fresh=True)
        ↓
compute price factors
        ↓
_compute_macro(... fresh=True)
        ↓
cache put(score key)
```

Because the `await` happens between cache get and cache put, concurrent requests with the same cold key can all observe the miss before any one of them populates the cache.

That means the duplication is not limited to macro fetches.

---

## 3. Same-key cold burst

Consider `N` simultaneous identical live daily score/snapshot requests after restart or eviction.

For the default full daily/weekly factor set, one caller can require approximately:

```text
1 fresh main price series
+ 18 unique fresh macro/FRED series
= 19 fresh data fetch sequences
```

Each `DataClient.get_bars(... fresh=True)` is currently shaped as:

```text
POST /backfill/bars
→ GET /bars
```

So a static upper-bound for **6 simultaneous identical cold callers** is:

```text
6 × 19 = 114 fresh fetch sequences
up to roughly
114 backfill POSTs + 114 bars GETs = 228 factor→data HTTP operations
```

before considering retries.

This is deliberately an **upper bound**, not a production claim. Real counts can be lower because of request timing, factor filtering, unavailable FRED, early cache population, degradation, or different keys.

The point is that the current cache does not structurally coalesce same-key in-flight work.

---

## 4. Different symbols can still duplicate the same macro work

The full score cache key includes symbol and other score parameters, so six different symbols legitimately have six different price-cache keys.

But macro cache keys are based on:

```text
series id
from date
to date
```

not the target asset symbol.

Therefore six concurrent daily scores for different symbols on the same date can still all miss the **same 18 macro keys** before first population.

Static upper-bound macro duplication:

```text
6 callers × 18 same macro series = 108 macro fresh fetches
```

for only 18 unique macro keys.

This is especially relevant to multi-run/restart scenarios where different strategies/symbols ask factor for current daily context at roughly the same time.

---

## 5. The one-hour macro TTL is an upper bound, not a retention guarantee

Macro entries and normal live score entries share the same 64-entry LRU.

A macro cache hit moves its entry to the end, so active daily macro traffic tends to protect those keys.

But unrelated cache churn — especially live intraday/non-macro score keys that do not touch macro entries — can evict macro entries **before** the nominal one-hour TTL expires.

Therefore the capacity model should say:

```text
macro TTL <= 1 hour
subject to LRU eviction
```

not:

```text
one FRED burst at most once per hour
```

This is a subtle but important correction to earlier static wording.

---

## 6. Why H11 is separate from Candidate A

Candidate A, if selected, addresses:

```text
data-service DB lease spans provider I/O
```

H11 addresses:

```text
factor callers duplicate cold same-key work before cache population
```

They are different layers and different failure mechanisms.

A good outcome is entirely possible where:

```text
Candidate A alone fixes #107 representative workload
→ H11 remains technical debt / follow-up only
```

Do not bundle a factor single-flight implementation into the first PR merely because the code permits a stampede.

---

## 7. Pure unit diagnostic

Prepared contributor-only draft:

```text
.faysk-notes/tools/test_factor_live_cache_stampede_draft.py
```

It disables macro so it isolates only the **whole-score live cache**.

Test shape:

```text
clear module cache
create 6 request-scoped engines sharing a blocking probe
launch 6 identical live score calls concurrently
require all 6 to enter _fetch_df before releasing any
→ proves cache miss does not coalesce in-flight work

then call the same key sequentially after population
→ should hit cache with no additional fetch
```

No data-service, DB or external provider is contacted.

This diagnostic proves structure, not production materiality.

---

## 8. Runtime materiality test

If the pure test behaves as predicted, service-level evidence should count:

```text
logical factor requests
unique full score keys
unique macro keys
actual factor→data fresh fetches
actual /backfill/bars calls
actual /bars calls
```

Separate at least:

```text
cold single caller
cold concurrent identical callers
cold concurrent different-symbol callers
warm callers
```

Then compute:

```text
full-score duplicate ratio = actual main-price fetches / unique score keys
macro duplicate ratio      = actual macro fetches / unique macro keys
```

---

## 9. Selection gate for any future single-flight fix

Only consider a factor-side in-flight coalescing change if all are true:

1. concurrent cold requests materially duplicate work in a representative #107 workload;
2. Candidate A / primary data-side correction does not already make the workload stable enough;
3. the duplicate work contributes meaningfully to p95/errors/provider pressure;
4. request/token isolation remains correct;
5. cancellation semantics for followers/leader are designed explicitly;
6. freshness semantics remain unchanged.

A single-flight implementation has its own complexity:

```text
leader fails
followers need same explicit failure
leader cancelled
followers must not hang
cache must not store failure/empty poison
per-process only under current factor worker topology
```

So it is not a free optimization.

---

## 10. Acceptance wording

H11 should be reported as one of:

```text
confirmed structurally, not material in representative load
```

or

```text
confirmed and materially amplifies #107 workload
```

Do not jump from a unit-level stampede proof to "root cause."

---

## Current conclusion

Current factor caching prevents repeated work **after** population, but does not provide in-flight request coalescing for either the full live score key or macro subkeys.

That can make cold/restart/eviction bursts substantially larger than a steady-state cache-hit model suggests.

For #107, it is a measured secondary amplifier candidate — not yet a reason to expand PR1 beyond `services/data`.