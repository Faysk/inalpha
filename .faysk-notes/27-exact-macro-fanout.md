# Issue #107 — Exact Live Macro Fan-out on Current Main

**Purpose:** replace the loose “roughly 18” wording with the exact current code path and make the benchmark request shape reproducible.

---

## 1. Current macro catalog

`MacroAdapter` currently defines **26 macro factor specs** backed by **18 unique FRED series**.

Unique series from `_SERIES_META` / `required_series()`:

### Daily — 8

```text
DFF
DGS10
DGS2
DGS3MO
DTWEXBGS
VIXCLS
BAMLH0A0HYM2
BAMLC0A0CM
```

### Monthly — 10

```text
CPIAUCSL
CPILFESL
UNRATE
PAYEMS
M2SL
PPIACO
INDPRO
RSAFS
HOUST
UMCSENT
```

Total:

```text
8 + 10 = 18 unique FRED series
```

Several factor specs reuse the same series (for example multiple DGS10/CPI/VIX transformations), so **26 factors do not mean 26 data requests**.

---

## 2. Default live score/snapshot path

For `timeframe=1d` / `1wk` / `1w` with macro enabled and no explicit `factor_ids` filter:

```text
_score_with_series(... factor_ids=None)
→ _computable_ids(timeframe)
→ includes all available macro specs
→ _compute_macro(... all macro factor ids)
→ MacroAdapter.required_series(...)
→ exact 18 unique series
→ asyncio.gather(18 _fetch_one calls)
```

So a **cold default live daily/weekly score/snapshot** has an exact current macro fan-out ceiling of 18 distinct macro-series fetches before considering duplicate concurrent callers.

If the caller supplies a narrower `factor_ids` list, fan-out is correspondingly smaller.

---

## 3. Daily vs monthly data-service keys

`series_timeframe()` maps:

```text
daily FRED series   → timeframe="1d"
monthly FRED series → timeframe="1mo"
```

This matters when counting unique work/cache/backfill keys. The same symbol with a different timeframe would be a different bars-series identity, though current built-in macro metadata fixes each series to one native bucket.

---

## 4. Warmup windows

When all default macro factors are requested, monthly factors are present, so:

```text
MacroAdapter.warmup_days(...) = 600 days
```

The factor engine then asks data-service for those macro series over that historical window, with live `fresh=True` on a cache miss.

The data service's incremental backfill behavior means this does **not** necessarily refetch the full 600-day provider history every time if rows already exist. The capacity concern is still that each cold live macro series can enter the fresh backfill route and its external provider path.

Do not equate request window length with provider rows fetched without measuring DB state.

---

## 5. Cache behavior

Each live macro series cache key is:

```text
("__macro__", series_id, from_ts.date(), to_ts.date())
```

with a one-hour TTL.

For one request after cache population:

```text
18 keys → hits → no new factor→data calls for those keys
```

For multiple **simultaneous cold** default requests before population completes:

```text
18 unique keys × N callers
```

can become up to `18 × N` `_fetch_df()` operations because current cache has no per-key in-flight single-flight.

That is H8. It is duplicate work across callers, distinct from the legitimate 18-way fan-out within one request.

---

## 6. Capacity arithmetic — use exact wording

For static discussion, use:

```text
one cold default live daily/weekly factor request
→ up to 18 distinct macro-series fetches
```

not:

```text
“about 18”
```

and not:

```text
“26 macro requests”
```

because 26 is the factor-spec count, not unique upstream series count.

Production data currently has 2 workers with 10 DB pool connections each, but request distribution is not guaranteed even. The exact 18 fan-out therefore does **not** imply a deterministic 9/9 worker split.

---

## 7. Benchmark cases now worth distinguishing

```text
M1: one cold default 1d snapshot/score
    expected unique macro keys = 18

M2: one warm repeat
    expected new macro data fetches ≈ 0 while keys remain cached

M3: N simultaneous cold default requests
    unique macro keys still = 18
    actual fetches may approach 18 × N if H8 manifests fully

M4: explicit narrow factor_ids
    expected unique macro keys = required_series(filtered ids)
```

Record both:

```text
unique macro keys
actual factor→data calls
```

so legitimate fan-out is not mislabeled as duplicate work.
