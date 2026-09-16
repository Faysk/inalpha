# Issue #107 — Live-Runner Resume → Factor Burst Shape

**Purpose:** make the runner-startup workload precise instead of saying “every resumed run triggers all macro factors.”

---

## 1. Startup behavior

When paper-service starts with resume enabled:

```text
list_all_running()
→ for each persisted running run: manager.start(run)
→ each run gets its own asyncio task
```

Those tasks independently build their sessions.

The build path includes fresh warmup bars:

```text
_warmup_session(...)
→ DataClient.get_bars(... fresh=True)
→ data POST /backfill/bars
→ data GET /bars
```

So a service restart with several persisted runs is a real source of concurrent fresh data traffic regardless of factors.

---

## 2. Factor baseline happens after successful build

After `_build_session(run)` succeeds, the live loop calls:

```text
capture_factor_baseline(run, settings)
```

This baseline path is **conditional**, not always a full snapshot.

It first reads the candidate's stored `factor_snapshot` lineage.

### Candidate has lineage factor IDs

```text
lineage_ids non-empty
→ FactorClient.score(... factor_ids=lineage_ids)
```

Therefore factor fan-out depends on the declared lineage:

- price/volume-only lineage → no FRED macro fetches;
- a few macro IDs → only their required FRED series;
- broad macro lineage → larger subset.

Do not count this as an automatic 18-series macro request.

### Candidate has no lineage factor IDs

```text
lineage_ids empty
→ FactorClient.snapshot(... no factor_ids filter)
```

For a `1d`/`1wk`/`1w` run with macro enabled and cold macro cache, this path can select the full default macro universe:

```text
26 macro factor specs
→ 18 unique FRED series
```

So **environment-baseline** runs are the stronger startup path for the exact 18-series cold burst.

---

## 3. H8 interaction is also conditional

A restart can start many `capture_factor_baseline()` calls from independent live-runner tasks.

H8 becomes especially plausible when several resumed runs share:

```text
same/similar daily-weekly timeframe
+ environment baseline (no lineage)
+ same date/cache window
+ factor macro cache cold
```

Then several snapshot calls can miss the same 18 macro keys before the first one populates them.

If runs have different lineage subsets, intraday timeframes, or already-warm macro cache, the factor burst is much smaller.

This distinction should be reflected in the reproduction workload.

---

## 4. Periodic FactorPatrol is different

`FactorPatrol.patrol_once()` first self-heals missing baselines with:

```python
for run in missing:
    await capture_factor_baseline(run, settings)
```

That loop is sequential inside the patrol task.

After baselines exist, runs are grouped by `(venue, symbol, timeframe)` and the patrol loops groups sequentially, issuing one `/score` per group.

Therefore normal periodic patrol is not the same burst shape as independent live-runner startup tasks.

Do not use “factor patrol scans all runs” as evidence of simultaneous macro fan-out.

---

## 5. Better restart reproduction matrix

Instead of only varying run count, classify resumed runs by baseline source.

### R1 — warmup only / no meaningful factor macro

```text
4 resumed intraday runs
→ concurrent fresh warmups
→ no macro factors due intraday timeframe
```

Isolates live-runner data pressure.

### R2 — daily runs with narrow lineage

```text
4 resumed 1d runs
→ fresh warmups
→ baseline score with explicit narrow factor_ids
```

Measures real lineage-scoped factor pressure.

### R3 — daily environment baselines

```text
4 resumed 1d runs with no factor lineage
→ fresh warmups
→ concurrent default snapshot baselines
→ cold factor macro cache can expose H8
```

This is the strongest current restart/macro burst case.

### R4 — same as R3, macro cache warm

Separates startup runner pressure from cold macro-cache amplification.

---

## 6. What to record

```text
number of resumed runs
run timeframes
baseline source per run: lineage/environment
lineage factor IDs if present
unique macro series required per baseline
macro cache cold/warm
actual factor→data macro calls
unique macro cache keys
fresh warmup backfills
peak overlap
```

This prevents us from attributing an 18-series burst to every live run when current code does not support that conclusion.

---

## 7. Scope implication

If R1 alone reproduces the issue, factor macro work is not required for the root cause.

If only R3 materially worsens it, H8/default snapshot behavior is a real multiplier worth evaluating after the data-service resource issue.

If Candidate A makes all R1–R4 meet the #107 target, do not add runner staggering or factor single-flight merely because those paths are theoretically bursty.
