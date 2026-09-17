# Issue #107 — Mega Smoke Baseline G–O (current main)

**Revision:** `ed01be9056776c107ab76a404c328a4fed19f529`  
**Branch under test:** `fix/data-service-saturation`  
**Suite:** remaining baseline smoke, 2026-09-17  
**Safety:** dedicated `inalpha_issue107`; contributor fake providers; no production candidate applied.

## Stage G — two data workers

Two-worker Uvicorn startup succeeded on Windows. D10/D12/D16 stayed client-healthy even though each busy worker's pool reached zero available while provider work was active.

At D20 the request split was skewed 13/7 across workers. The 13-request worker hit:

- provider active = 10;
- pool size = 10;
- pool available = 0;
- pool requests waiting = 3.

Client-visible results at D20:

- backfill 20/20 HTTP 200;
- backfill p95 ≈ 10.157 s (vs ≈5.2 s below the boundary);
- health 8/10 HTTP 200 + 2 ReadTimeout;
- OpenAPI 10/10 HTTP 200, p95 ≈0.127 s.

This is production-topology-relevant confirmation of H1: two workers move the boundary but do not remove per-worker pool starvation. Load imbalance means one worker can hit its 10-connection ceiling before aggregate service capacity is evenly consumed.

## Factor macro H/I/J

Cold single macro caller:

- 26 macro factor ids;
- 18 unique FRED series, but 26 fake-FRED provider starts because long daily windows require two fake-provider pages for 8 daily series;
- factor latency ≈3.909 s;
- pool wait delta ≈14.3 s;
- immediate warm wave made zero data/provider calls and completed ≈0.320 s.

Cold 6-call same-symbol:

- 6/6 HTTP 200;
- factor p95 ≈16.886 s;
- 118 FRED provider starts + 6 Binance starts;
- pool wait delta ≈740.8 s;
- warm wave zero data/provider calls, p95 ≈2.542 s.

Cold 6-call unique-symbol:

- 6/6 HTTP 200;
- factor p95 ≈12.642 s;
- 118 FRED provider starts + 6 Binance starts;
- pool wait delta ≈401.0 s;
- warm wave zero data/provider calls, p95 ≈1.696 s.

Therefore H8 cold in-flight macro duplication is materially visible. H11 adds redundant same-key main-price work (same-symbol calls still issue six Binance refreshes), but FRED/macro fan-out dominates this workload.

## Runner H6

Aligned 8-runner wave (0 ms):

- p95 ≈0.552 s;
- provider active max = 8;
- pool waiting max = 4;
- pool wait delta ≈605 ms.

100 ms stagger:

- p95 ≈0.387 s;
- provider active max = 3;
- pool waiting max = 0;
- pool wait delta ≈30 ms.

H6 is materially visible in runner-only load. It is still secondary to the data-service DB-lifetime problem and should not be selected as PR1 before Candidate A is tested.

## Mixed N

M1 same-symbol + aligned:
- factor p95 ≈7.187 s;
- runner p95 ≈0.664 s;
- pool waiting max = 62;
- pool wait delta ≈180.8 s;
- 0 factor/runner/health/OpenAPI failures.

M2 unique-symbol + aligned:
- factor p95 ≈6.581 s;
- runner p95 ≈0.586 s;
- pool waiting max = 62;
- pool wait delta ≈175.5 s;
- 0 failures.

M3 same-symbol + 100 ms stagger:
- factor p95 ≈7.367 s;
- runner p95 ≈0.475 s;
- health p95 ≈0.073 s;
- pool waiting max = 62;
- pool wait delta ≈212.9 s;
- 0 failures.

Runner staggering improves runner latency, but the factor/macro burst still drives the pool to max and leaves a large queue.

## Sustained O smoke

O1 primary cross-sectional (`factor-symbol-mode=unique`, 30 s):

- 17 cycles started/completed;
- 13 offered cycles skipped by pending cap;
- schedule-lag skips = 0;
- factor p95 ≈13.076 s;
- runner backfill p95 ≈3.843 s;
- runner bars p95 ≈2.966 s;
- health 30/34 HTTP 200 + 4 ReadTimeout, p95 ≈1.023 s;
- OpenAPI 34/34 HTTP 200, p95 ≈0.144 s;
- pool waiting max = 152;
- pool available min = 0;
- pool wait delta ≈869.6 s;
- provider failures/cancellations = 0.

This is the strongest representative smoke reproduction. The event loop/control path remains alive while DB-backed traffic queues heavily. No `DATA_SERVICE_UNREACHABLE` was produced because this harness gives factor a long timeout; prior H9 evidence shows shorter caller deadlines can expire while old server work continues.

O2 same-key stress (30 s) was worse in factor/backlog terms (12 completed cycles, 18 pending-cap skips, factor p95 ≈16.703 s), but see the harness caveat below before treating the delta as clean H11 materiality.

## Important harness finding: synthetic candle timestamps are not bucket-aligned

The current contributor fake uses the exact request `since` timestamp as the first candle timestamp. Concurrent factor requests have slightly different microsecond-level `from_ts` values, so fake candles for the same logical daily key land at different timestamps.

Observed same-symbol evidence:

- six concurrent BTC/USDT requests each persisted a separate 786-row time grid;
- score responses then reported `bars_used=4711` for five callers vs 786 for the first;
- unique-symbol runs stayed at 786;
- the same effect can also create extra rows for shared FRED series.

Real OHLCV/FRED candle timestamps are bucketed to timeframe boundaries, so this is a **contributor-harness artifact**, not production evidence of duplicate-key persistence failure.

Consequences:

- H1 conclusions are unaffected (proved independently in low-level D/E/G);
- provider-call duplication/H8 remains valid;
- runner L/M is unaffected because runner symbols are distinct;
- same-key H11 latency/data-volume interpretation is contaminated;
- O1 primary unique-symbol smoke is still useful as capacity evidence, but its shared FRED DB-write volume can be inflated by microsecond-shifted fake timestamps;
- PR-quality 60 s repetitions should use a corrected, timeframe-aligned fake connector and the same corrected harness for candidate comparison.

## Local factor startup side finding

Factor startup against the benchmark DB logs a caught `factor_candidates` missing-table warning. On Windows the Chinese warning then triggers CP1252 `UnicodeEncodeError` in the logging stream. Startup still completes and built-in macro scoring works. This is a local/self-host diagnostic issue, not #107 production evidence.

## Decision status

H1 is now strongly selected as the first measured constrained resource across:

- pool=2 deterministic proof;
- one-worker D10/D12 boundary;
- PostgreSQL `idle in transaction` evidence;
- two-worker D20 production-like confirmation;
- representative O1 sustained smoke.

Candidate A (short DB lease around latest lookup, release during provider I/O, short lease for persistence) remains the smallest first production candidate.

Before applying Candidate A, calibrate the fake candle timestamps and collect stable 60 s ×3 O1 baseline repetitions (and clean O2 control) using the corrected harness. Then apply Candidate A and replay the exact same calibrated workload.
