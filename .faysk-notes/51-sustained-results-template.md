# Issue #107 — Sustained Benchmark Results Template

**Status:** empty until runtime execution.  
**Purpose:** keep O1/O2 before/after evidence comparable and prevent cherry-picking one favorable run.

Use with `50-sustained-load-acceptance.md` and the authoritative safety order in `49-runtime-safety-order.md`.

---

## Session identity

```text
revision:
branch:
upstream/main:
result directory:
OS / WSL:
CPU:
RAM:
Docker limits:
data workers:
factor workers:
provider fake mode:
provider delay:
fake bars per fetch:
```

Safety evidence:

```text
benchmark DB verified as inalpha_issue107: yes/no
target checker PASS: yes/no
snapshot scheduler forced disabled: yes/no
required fake venues:
blocked non-fake OHLCV venues:
factor configured data URL:
```

Do not continue the capacity run if the safety evidence is not affirmative.

---

## O1 — cross-sectional sustained (`factor-symbol-mode=unique`)

Controlled settings:

```text
duration:
cycle interval:
max pending cycles:
settle timeout:
factor concurrency:
runner runs:
runner stagger ms:
controls per cycle:
factor timeout:
runner timeout:
control timeout:
```

Run each stable revision at least three times before using percentile evidence in PR text.

| Metric | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| cycles started | | | |
| cycles completed | | | |
| cycles skipped pending cap | | | |
| cycles skipped schedule lag | | | |
| cycles pending after settle | | | |
| cycle task errors | | | |
| factor transport/HTTP failures | | | |
| factor p50 s | | | |
| factor p95 s | | | |
| factor p99 s | | | |
| runner backfill failures | | | |
| runner backfill p95 s | | | |
| runner bars failures | | | |
| runner bars p95 s | | | |
| health failures | | | |
| health p95 s | | | |
| openapi failures | | | |
| openapi p95 s | | | |
| pool available min | | | |
| pool waiting max | | | |
| pool requests queued delta | | | |
| pool wait ms delta | | | |
| POST backfill delta | | | |
| GET bars delta | | | |
| Binance starts / failures | | | |
| FRED starts / failures | | | |
| Baostock starts / failures | | | |
| yfinance starts / failures | | | |
| provider cancelled total | | | |

Record error classes separately; do not collapse these into one count:

```text
ConnectTimeout:
ReadTimeout:
ConnectError:
PoolTimeout:
HTTP 429:
HTTP 5xx:
DATA_SERVICE_UNREACHABLE:
other machine codes:
```

For `data workers=1`, the acceptance probe's before/after state counters are exact process-local deltas. For `data workers=2`, do not aggregate two unrelated worker snapshots as if they were service-global; use per-PID logs/state samples plus client-visible results.

---

## O2 — same-key stress (`factor-symbol-mode=same`)

Use exactly the same settings as O1 except factor symbol mode.

| Metric | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| cycles started | | | |
| cycles completed | | | |
| cycles skipped pending cap | | | |
| cycles skipped schedule lag | | | |
| cycles pending after settle | | | |
| factor failures | | | |
| factor p95 s | | | |
| runner bars failures | | | |
| health failures | | | |
| health p95 s | | | |
| pool available min | | | |
| pool waiting max | | | |
| provider starts / failures | | | |

Interpret O2 as H11 stress evidence, not as the primary representation of the issue's cross-sectional agent workload.

---

## Optional O3 — runner stagger

Only fill this section if L/M earlier showed material H6 sensitivity.

```text
base scenario = O1
only changed variable = runner stagger ms
```

| Metric | O1 aligned | O3 staggered |
|---|---:|---:|
| factor p95 s | | |
| runner bars p95 s | | |
| health p95 s | | |
| failures | | |
| cycles skipped pending cap | | |
| cycles skipped schedule lag | | |
| pool waiting max | | |

If more than one meaningful variable changed, the comparison is invalid for attributing an H6 effect.

---

## Progress / data-quality notes

Do not use `bars_fetched == 0` alone as failure evidence during repeated runner polling.

For suspicious successful responses, correlate:

```text
bars_fetched / bars_inserted
GET /bars count
latest persisted timestamp when inspected
provider start/completion/failure counters
whether another candle should actually exist in the requested interval
```

Record any case where HTTP success masked a current-data freshness failure separately.

---

## Before → after summary

After a production candidate is selected and the exact same O1 workload is repeated:

| Signal | Baseline | Candidate | Interpretation |
|---|---:|---:|---|
| DATA_SERVICE_UNREACHABLE | | | |
| total transport failures | | | |
| factor p95 | | | |
| runner bars p95 | | | |
| health p95 | | | |
| cycles skipped pending cap | | | |
| cycles skipped schedule lag | | | |
| cycles pending after settle | | | |
| pool waiting max | | | |
| pool wait ms delta | | | |
| provider failures | | | |

Acceptance is not based on latency alone. A candidate is not successful if it removes DB/transport failures by causing provider failure, stale-data fallback, silent no-progress, or another invariant regression.

The issue asks for a controlled p95 but does not state a numeric p95 SLO. Until the maintainer provides one, record the measured percentile under the exact documented workload and compare before/after; do not invent an absolute threshold and present it as a project requirement.

---

## Evidence wording gate

Before copying any statement into `08-pr-draft.md`, verify that the recorded runs support the exact wording.

Allowed shape:

```text
Under the documented local fake-provider workload, across N repeated 60-second runs, ...
```

Avoid unsupported shape:

```text
The service can now handle all production concurrency.
```

The benchmark supports the tested workload and topology only.
