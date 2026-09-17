# Issue #107 — Calibrated baseline complete (H/J/N/O, 60s ×3)

**Baseline revision:** `ed01be9056776c107ab76a404c328a4fed19f529`  
**Branch:** `fix/data-service-saturation`  
**Harness:** calibrated fake candle buckets (`fake_time_alignment=ceil_to_timeframe_bucket`)  
**Result directory:** `20260917-232148-calibrated-current-main-baseline`

The preflight confirmed `HEAD == upstream/main == ed01be...`, dedicated `inalpha_issue107`, and only the known contributor files were untracked. Upstream `main` remained unchanged when rechecked after the run.

## Calibration check

The fake timestamp correction removed the earlier same-key row-grid inflation:

- H single: `bars_used=785`;
- I same-symbol 6 callers: all six `bars_used=785`;
- J unique-symbol 6 callers: all six `bars_used=785`.

This makes the calibrated H/N/O results suitable for baseline/candidate comparison.

## H/I/J — macro / same-key structure

### H — one cold macro caller

- factor 1/1 HTTP 200;
- cold latency 4.081 s;
- 19 backfill HTTP calls = 1 Binance + 18 FRED logical series;
- FRED provider starts 26 because long daily windows require additional fake-provider pages;
- pool wait delta 8,671 ms;
- immediate warm repeat: zero data/provider calls, 0.196 s.

### I — six cold same-symbol callers

- 6/6 HTTP 200;
- p95 7.922 s;
- 114 backfill HTTP calls;
- Binance provider starts 6;
- FRED provider starts 118;
- pool wait delta 349,064 ms;
- immediate warm repeat: zero data/provider calls, p95 0.998 s.

### J — six cold unique-symbol callers

- 6/6 HTTP 200;
- p95 8.236 s;
- 114 backfill HTTP calls;
- Binance provider starts 6;
- FRED provider starts 117;
- pool wait delta 357,511 ms;
- immediate warm repeat: zero data/provider calls, p95 0.983 s.

Interpretation:

- H8 cold shared-macro duplication is material: six callers create ~4.5× the single-caller FRED provider work instead of coalescing shared keys.
- H11 same-key main-price duplication exists (six identical callers still start six Binance provider operations), but same vs unique factor latency/pool pressure is similar. H11 is not the first measured bottleneck for PR1.
- Post-population cache reuse works.

## N — calibrated mixed burst

### M1 same factor key + aligned runners

- factor p95 6.924 s;
- runner p95 1.065 s;
- health/OpenAPI failures 0;
- pool waiting max 62;
- pool wait delta 189,055 ms.

### M2 unique factor keys + aligned runners

- factor p95 9.408 s;
- runner p95 0.634 s;
- failures 0;
- pool waiting max 62;
- pool wait delta 244,438 ms.

### M3 same factor key + runner stagger 100 ms

- factor p95 7.243 s;
- runner p95 0.523 s;
- failures 0;
- pool waiting max 62;
- pool wait delta 206,893 ms.

Runner staggering helps runner latency, but it does not remove factor/macro-driven DB queueing.

## O1 — primary cross-sectional sustained baseline, 60 s ×3

All three runs:

- completed every started cycle;
- schedule-lag skips = 0;
- pending after settle = 0;
- factor/runner HTTP outcomes = all 200;
- provider failures/cancellations = 0;
- pool available minimum = 0;
- provider active maximum = 10;
- OpenAPI transport failures = 0.

Run values:

| Metric | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| cycles completed | 30 | 27 | 22 |
| skipped pending cap | 30 | 33 | 38 |
| factor p95 s | 14.601 | 16.301 | 17.455 |
| runner backfill p95 s | 1.808 | 1.851 | 1.992 |
| runner bars p95 s | 1.784 | 0.877 | 0.762 |
| health ReadTimeout | 6/60 | 4/54 | 4/44 |
| health p95 s | 1.104 | 1.073 | 1.061 |
| OpenAPI p95 s | 0.056 | 0.100 | 0.164 |
| pool waiting max | 131 | 152 | 150 |
| pool wait-ms delta | 801,894 | 1,088,462 | 1,041,350 |

Across the three primary O1 runs:

- 79 cycles completed;
- 101 offered cycles skipped by the bounded pending-cap;
- 14/158 health probes timed out;
- 0/158 OpenAPI probes failed;
- median factor p95 = 16.301 s;
- median pool waiting max = 150;
- median pool wait delta = 1,041,350 ms.

This is repeatable representative evidence of the #107 capacity problem: DB-backed traffic queues severely while the DB-free control remains responsive.

## O2 — same-key stress, 60 s ×3

| Metric | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| cycles completed | 27 | 33 | 21 |
| skipped pending cap | 33 | 27 | 39 |
| factor p95 s | 16.555 | 14.336 | 17.228 |
| health ReadTimeout | 8/54 | 2/66 | 10/42 |
| pool waiting max | 150 | 152 | 134 |
| pool wait-ms delta | 1,007,551 | 1,126,904 | 701,022 |

O2 is not consistently worse than O1 after correcting the fake timestamp artifact. H11 duplicate same-key work exists, but the sustained comparison does not select H11 as the first bottleneck.

One O2 run recorded one OpenAPI `RemoteProtocolError`; all other O1/O2 OpenAPI probes were successful. Preserve it as observed noise/anomaly rather than reclassifying the DB starvation signal.

## Decision gate

The evidence chain now includes:

1. deterministic pool=2 H1 proof;
2. one-worker D08/D10/D12 transition;
3. PostgreSQL: 10 `idle in transaction` sessions with `latest_bar_ts` as the last query while providers wait;
4. H9 async/thread client-timeout persistence;
5. two-worker D20 production-like boundary;
6. calibrated mixed load;
7. three repeatable 60-second O1 representative runs.

**Selected first production candidate: Candidate A.**

Candidate A is the smallest change connected directly to the first measured constrained resource:

```text
short DB lease for latest_bar_ts
→ release DB before external provider await
→ short DB lease for insert_bars
```

Do not combine H8/H11 single-flight, runner jitter, pool inflation, retry changes, or provider admission control into PR1 before Candidate A is measured.

Because same-key duplicate refreshes are real, Candidate-A comparison must continue to record same-key provider starts/progress and apply the existing overlap/write-correctness guard. If Candidate A makes duplicate same-key provider work materially worse or exposes ordering regression, investigate that separately before shipping.
