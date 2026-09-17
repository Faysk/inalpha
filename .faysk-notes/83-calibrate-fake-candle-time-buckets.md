# Issue #107 — Contributor fake candle timestamp calibration

**Status:** contributor-harness correction only.  
**Production scope:** none.

## Finding

The first G–O smoke bundle exposed a benchmark artifact in `issue107_slow_data_app.py`.

The fake connector generated each candle series from the request's exact `since` value:

```python
start = since
```

Factor live requests derive their windows from independently sampled `datetime.now()`, so concurrent same-key callers differ by microseconds. The contributor fake therefore produced different synthetic candle timestamp grids for logically identical timeframe keys.

Example from the same-symbol 6-caller macro run:

- six BTC/USDT daily backfills were concurrent;
- each fetched/persisted 786 synthetic bars;
- five score responses later observed `bars_used=4711` while the first observed 786;
- unique-symbol runs observed 786 each.

The same microsecond-shift effect can occur for shared FRED series.

Real OHLCV/FRED data uses timeframe/calendar bucket timestamps, so this should not be treated as a production duplicate-row or mutable-candle ordering result.

## Calibration

The notes-branch contributor wrapper now computes the first fake timestamp as the first timeframe bucket **at or after** `since`:

- fixed-second frames: epoch-based ceil;
- weekly: Monday 00:00 UTC;
- monthly: first day of month;
- quarterly: first day of quarter;
- yearly: January 1.

The state endpoint now reports:

```text
fake_time_alignment=ceil_to_timeframe_bucket
```

This preserves deterministic fake-provider latency/counters while preventing microsecond request timing from manufacturing distinct logical candles.

Notes-branch tool commit:

```text
49d5f7dd7297ef067c17614c2363f318909dc048
```

## Interpretation impact

Already-valid evidence remains valid:

- H1 deterministic pool=2 proof;
- one-worker D08/D10/D12;
- PostgreSQL idle-in-transaction evidence;
- H9 async/thread timeout persistence;
- Stage G two-worker D20 starvation boundary;
- runner-only L/M scheduling comparison;
- provider-call duplication counters.

The following should be rerun before PR-quality before/after claims because row volume/GET size could be inflated by the old fake timestamp grid:

- H/I/J macro latency and bars_used;
- mixed N M1/M2/M3;
- sustained O1/O2 percentiles/backlog.

The primary O1 topology remains representative, but its 30-second smoke numbers are mechanism/smoke evidence rather than final percentile evidence.

## Decision

Do not change production code to address this artifact.

Use the calibrated fake for all remaining 60-second baseline repetitions and for every Candidate-A comparison, so before/after measurements share exactly the same harness semantics.
