# Issue #107 — Sustained Mixed-Load Acceptance

**Status:** runtime acceptance supplement; no production change selected yet.  
**Purpose:** distinguish short mechanism-finding bursts from the sustained-capacity evidence requested by issue #107.

---

## 1. Why this stage exists

Issue #107 is specifically about **sustained high concurrency** and asks for:

```text
agent + live runner concurrency
→ no DATA_SERVICE_UNREACHABLE
→ controlled p95 latency
```

The small D08/D10/D12 probes are designed to locate a capacity boundary and explain mechanism. Their sample sizes are not sufficient for strong percentile claims.

The mixed M1/M2/M3 scenarios are representative combined bursts and isolate H11/H6 effects, but the final p95/stability evidence uses a separate sustained stage.

The issue does **not** state a numeric p95 SLO. Until the maintainer provides one, we measure and compare p95 under a precisely documented workload rather than inventing a threshold and attributing it to the project.

---

## 2. Sustained tools and roles

### Base soak machinery

```text
tools/issue107_sustained_mixed_probe.py
```

This established the bounded-cycle machinery and remains useful as same-key-heavy H11 stress infrastructure.

Its original per-cycle factor traffic uses one repeated symbol key. That is intentionally **not** treated as the canonical #107 cross-sectional workload.

### Acceptance-oriented probe

```text
tools/issue107_sustained_acceptance_probe.py
```

Materialized as:

```text
services/factor/issue107_sustained_acceptance_probe.py
```

It adds:

```text
--factor-symbol-mode unique   # default / representative cross-sectional shape
--factor-symbol-mode same     # H11 stress control
```

and hardens scheduling/settling/evidence capture.

---

## 3. Mandatory safety chain

Follow `49-runtime-safety-order.md` and `52-provider-isolation-and-soak-hardening.md`.

Before any sustained load:

```text
dedicated inalpha_issue107 DB
→ hardened issue107_slow_data_app
→ startup constituent snapshot scheduler forced disabled
→ every requested OHLCV venue replaced by deterministic fake
→ every other registered OHLCV venue blocked before provider I/O
→ issue107_factor_app pins factor to the fake data target
→ issue107_target_check.py
→ issue107_target_check=PASS
→ only then load
```

The sustained acceptance probe duplicates the most important target guard and refuses load if scheduler isolation is absent or a required workload venue is blocked instead of fake.

This is contributor-only benchmark safety. None of these diagnostic endpoints/wrappers belongs in the production fix as-is.

---

## 4. Required sustained scenarios

### O1 — primary cross-sectional sustained workload

```text
factor symbol mode = unique within each cycle
factor concurrency = 4 initially
runner traffic     = BTC / BNB / A-share / JP mix
runner runs        = 8 initially
runner stagger     = 0 initially
provider fakes     = binance,fred,baostock,yfinance
```

O1 is the primary sustained acceptance workload for #107 because the issue describes multi-symbol agent traffic combined with background runners.

### O2 — same-key H11 stress control

Use exactly O1 settings except:

```text
factor symbol mode = same
```

O2 answers whether whole-score cold same-key duplication can materially amplify pressure. It must not be substituted for O1 in the issue-level conclusion.

### O3 — optional runner stagger control

Only if L/M shows H6 remains materially relevant, repeat O1 with the measured stagger value while holding every other meaningful variable constant.

Do not run O3 merely because the knob exists.

---

## 5. Offered-load scheduling and backlog accounting

The acceptance probe is bounded by:

```text
cycle interval
requested duration
max pending cycles
settle timeout
```

Two skip signals are deliberately distinct.

### Service/harness backlog cap

```text
pending cycles >= max_pending_cycles
→ do not inject another cycle
→ cycles_skipped_pending_cap += 1
```

### Generator scheduling lag

If the load generator itself is at least one complete cycle interval late:

```text
now - scheduled_at >= cycle_interval
→ do not catch up the old slot
→ cycles_skipped_schedule_lag += 1
```

Missed slots are never replayed back-to-back. Otherwise local event-loop or host scheduling delay could be transformed into an artificial burst and wrongly attributed to Inalpha.

At settle completion, record:

```text
cycles_started
cycles_completed
cycles_skipped_pending_cap
cycles_skipped_schedule_lag
cycles_pending_after_settle
cycle_task_errors
```

None of the skipped/pending values count as successful throughput.

If `cycles_skipped_schedule_lag` is material, review the generator/machine before using that run as service-capacity evidence.

---

## 6. Initial smoke vs PR-quality evidence

First validate topology/tooling with a bounded smoke:

```text
30 seconds
```

Once the harness behaves predictably, use the same longer evidence window on baseline and candidate, for example:

```text
60 seconds per repetition
at least 3 repetitions
```

The duration is an evidence window, not a production SLO.

Preserve every repetition. Do not cherry-pick the best run.

---

## 7. Percentile interpretation

Calculate p50/p95/p99 separately for:

```text
factor score
runner backfill
runner bars read
health
openapi control
```

Do not combine these into one global latency percentile because they are different operations with different semantics and timeout budgets.

Use D/N observed latencies for mechanism/reproduction context only. Use O1 repetitions for sustained p95 wording intended for the PR.

---

## 8. Provider / DB moved-bottleneck evidence

For one data worker the acceptance probe captures before/after process-local deltas for:

```text
POST /backfill/bars total
GET /bars total
provider started / completed / cancelled / failed
per-venue started / completed / cancelled / failed
thread started / completed
DB pool requests
DB pool queued count
DB pool wait milliseconds
DB pool checkout errors
DB pool usage milliseconds
```

State sampling also records peaks/minima such as:

```text
provider active by venue
thread active
backfill HTTP in flight
GET bars in flight
pool requests waiting
pool available minimum
```

For two data workers, state is process-local. If before/after PIDs differ, exact deltas are invalid. Use per-PID logs/state sampling plus client-visible results for production-like confirmation.

A candidate is not successful if it merely changes where saturation occurs.

Bad example:

```text
DATA_SERVICE_UNREACHABLE 20 → 0
provider failures        0 → 30
```

That moved the bottleneck; it did not satisfy the issue.

---

## 9. Progress / freshness interpretation

The probes record operation progress, but zero progress is context-dependent.

Example:

```text
runner backfill bars_fetched = 0
```

can be legitimate when repeated polling occurs inside the same market-data interval and there is no newer candle.

Therefore correlate suspicious successful responses with:

```text
HTTP/error status
bars_fetched / bars_inserted
GET /bars count
latest persisted timestamp where relevant
provider counters/logs
whether a new candle should actually exist
scenario timing
```

The rule is deliberately two-sided:

> HTTP 200 alone is not proof that current-data refresh succeeded; zero inserted/fetched rows alone is not automatically a failure either.

Any capacity improvement obtained by silently serving stale current data is a failed fix.

---

## 10. Required O1 evidence

Record at minimum:

```text
DATA_SERVICE_UNREACHABLE count
concrete HTTPX transport error classes
HTTP machine-code distribution
factor p50/p95/p99
runner backfill p50/p95/p99
runner bars p50/p95/p99
health p50/p95/p99
openapi p50/p95/p99
cycles started/completed
cycles skipped pending cap
cycles skipped schedule lag
cycles pending after settle
DB pool available minimum
DB pool waiting maximum
DB pool queued/wait-ms deltas
provider active peaks by venue
provider starts/completions/cancellations/failures by venue
worker PID evidence where relevant
refresh/read progress evidence
```

Use `51-sustained-results-template.md` so every repetition is preserved in the same shape.

---

## 11. Before / after discipline

Candidate comparison must hold constant:

```text
benchmark DB reset state
factor cache start state
workers
provider fake mode
provider delay
bars per fetch
factor symbol mode
factor concurrency
runner run count
runner stagger
cycle interval
duration
pending-cycle cap
settle timeout
client timeouts
```

The same O1 workload is run before and after the selected production change.

If upstream changes between runs, re-review #107-sensitive paths before using the comparison.

---

## 12. Recommended command shape

After `issue107_target_check=PASS`, smoke O1:

```bash
uv run python issue107_sustained_acceptance_probe.py \
  --factor-symbol-mode unique \
  --duration 30 \
  --cycle-interval 1 \
  --factor-concurrency 4 \
  --runner-runs 8 \
  --runner-stagger-ms 0
```

O2 changes only:

```text
--factor-symbol-mode same
```

For PR-quality evidence, increase the evidence window only after the smoke is stable, then preserve exactly the same settings on baseline and candidate revisions.

---

## 13. Evidence wording gate

Until a numeric SLO is explicitly supplied, acceptable wording is scoped to the measurement:

```text
Under the documented local fake-provider workload, across N repeated 60-second runs,
DATA_SERVICE_UNREACHABLE changed from ... to ... and factor/runner/health p95 changed from ... to ... .
```

Do not claim:

```text
the data-service now handles all production concurrency
or
p95 meets project SLO X
```

unless the tested topology/evidence or maintainer-provided target actually supports that statement.

---

## Current conclusion

The runtime plan now separates:

```text
D — where is the low-level capacity transition?
E/F — what resource/cancellation mechanism explains it?
H–M — which caller/provider patterns amplify it?
N — can the issue's combined burst be reproduced?
O1 — does the behavior remain stable under sustained representative cross-sectional load?
O2 — how much additional pressure comes from same-key H11 stress?
```

Only after those results does the production decision gate choose the smallest justified Candidate A/B/C/D — or none of them if the evidence points elsewhere.
