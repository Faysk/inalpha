# Issue #107 — Candidate A Same-Key Write Ordering Guard

**Status:** correctness guard only; do not expand PR1 unless runtime H4 shows same-key overlap is material.

**Purpose:** avoid overstating what the current `ON CONFLICT ... DO UPDATE` persistence rule guarantees when concurrent backfills for the same `(venue, symbol, timeframe)` overlap.

---

## 1. Important terminology correction

Current persistence is safe from **duplicate primary-key rows** because `insert_bars()` uses:

```sql
ON CONFLICT (ts, venue, symbol, timeframe) DO UPDATE
```

That means repeated writes to the same candle key do not create duplicate rows.

It does **not** by itself guarantee:

```text
newer provider observation always wins
```

or:

```text
completion order cannot regress a still-forming candle
```

So for #107 notes/PR language use the narrower wording:

```text
UPSERT keeps duplicate-key persistence repeatable and preserves the current row-key semantics.
```

Do not use `UPSERT makes all concurrent same-key writes logically safe` without a stronger ordering test.

---

## 2. Existing race shape

The current route intentionally re-fetches the latest cached candle so an earlier still-forming candle can be refreshed.

Two same-key backfills can therefore do:

```text
A: latest_bar_ts = T
B: latest_bar_ts = T

A: provider fetch returns candle T observation v1
B: provider fetch returns candle T observation v2 (newer source observation)

B: DB write v2
A: DB write v1 later
```

With unconditional `DO UPDATE`, the final row can become `v1` even though `v2` represented the later provider observation.

Whether this can happen materially with current real connectors depends on provider/request timing and is **not proven** by static inspection.

---

## 3. Relationship to Candidate A

This race class exists already because current `/backfill/bars` has no same-key single-flight lock.

Candidate A does not create the logical race, but it can change its probability:

```text
current route
→ DB pool accidentally caps how many requests reach provider wait

Candidate A
→ DB lease is released before provider wait
→ more same-key provider work could coexist if callers actually duplicate it
```

Therefore Candidate A acceptance must include:

```text
Did same-key duplicate provider work materially increase?
```

not just:

```text
Did DB pool waiting disappear?
```

---

## 4. Runtime decision gate

Do **not** build extra synchronization merely because this race is theoretically possible.

Use existing H4 measurements first:

```text
same-key backfill calls observed under representative workload?
    no / negligible
    → record negative evidence
    → keep PR1 focused

    yes, material
    → add a deterministic ordering diagnostic before shipping Candidate A
```

Useful signals:

```text
POST /backfill/bars count by logical key
provider calls by logical key
concurrent same-key provider active count
bars inserted/updated
latest candle values/timestamps before and after overlapping requests
```

The current contributor wrapper does not yet version fake candle values by request start/completion order; only add that behavior if H4 selects this question for deeper testing.

---

## 5. Deterministic diagnostic if H4 becomes material

A focused fake can force completion inversion:

```text
same venue/symbol/timeframe
same latest candle timestamp T

request A starts first
→ returns observation v1
→ deliberately delayed before persistence/completes last

request B starts second
→ returns observation v2
→ completes persistence first
```

Then assert what remains in `bars` for timestamp `T`.

Run this on:

```text
current main
Candidate A
```

and record whether Candidate A changes frequency/visibility of the behavior.

The test should model a genuinely mutable latest candle; using immutable historical candles would not exercise the correctness concern.

---

## 6. Possible mitigations — only if measured

### Same-key single-flight / coalescing

This is the most natural capacity/correctness direction if many callers request exactly the same backfill key/window concurrently:

```text
first caller performs refresh
other same-key callers await/reuse that work
```

But key design matters:

```text
venue
symbol
timeframe
requested freshness/window semantics
```

and process-local coalescing is not service-global with multiple workers.

Do not add this preemptively.

### Provider/admission control

A generic or per-provider gate can reduce overlap but does not inherently guarantee same-key observation ordering.

It is a capacity mechanism, not a substitute for an ordering contract.

### Conditional DB update

The current `bars` schema does not appear to persist provider-fetch observation version / fetched-at ordering metadata for each candle.

Without such an ordering signal, SQL cannot reliably decide that one same-timestamp OHLCV observation is "newer" merely from OHLCV values themselves.

Adding schema/version metadata would be a much larger change and is **not justified for #107 without evidence**.

---

## 7. Candidate A wording update

The prepared Candidate A patch comment now intentionally says:

```text
insert_bars() remains the transaction/commit boundary and its current UPSERT behavior is unchanged.
Same-key completion ordering remains a separate concurrency/correctness question.
```

This is more accurate than claiming that UPSERT alone makes concurrent backfills fully idempotent/safe.

---

## Current conclusion

For #107 the primary measured question remains service capacity.

This note exists so that, if Candidate A is selected, we do not accidentally trade:

```text
DB availability improvement
```

for an unnoticed increase in:

```text
duplicate same-key provider work / mutable-candle write inversion
```

The correct action remains:

```text
measure H4
→ if immaterial, stop
→ if material, prove ordering behavior deterministically
→ only then choose the smallest extra control
```
