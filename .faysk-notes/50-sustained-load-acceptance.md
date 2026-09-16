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

The small D08/D10/D12 probes are intentionally designed to locate a capacity boundary and explain the mechanism. They are not large enough to make strong percentile claims.

Therefore runtime acceptance gets a separate sustained stage after the lower-level mechanism is understood.

---

## 2. Two sustained tools with different purposes

The first contributor-only tool is:

```text
tools/issue107_sustained_mixed_probe.py
```

It established the bounded-soak mechanics and combines repeated cycles of:

```text
factor /score traffic
+ runner-like fresh backfill/read traffic
+ /health DB-backed controls
+ /openapi.json DB-free controls
```

Static review found that v1 sends `factor_concurrency` requests for the same factor symbol inside each cycle. That makes it useful as H11 same-key stress evidence, but not an exact model of the issue's cross-sectional multi-symbol workload.

The acceptance-oriented companion is now:

```text
tools/issue107_sustained_acceptance_probe.py
```

Materialized as:

```text
services/factor/issue107_sustained_acceptance_probe.py
```

It reuses the already-reviewed request/result helpers from v1 but adds:

```text
--factor-symbol-mode unique   # default; representative cross-sectional shape
--factor-symbol-mode same     # H11 stress control
```

and improves bounded scheduling/settling so a delayed scheduler does not inject a cycle after the requested duration and unfinished cycles are reported as backlog evidence rather than making the entire final summary disappear.

---

## 3. Safety model

Both sustained tools require the contributor safety chain from `49-runtime-safety-order.md`:

```text
dedicated benchmark DB
→ issue107_slow_data_app
→ all workload venues fake
→ issue107_factor_app
→ factor routed to fake data URL
→ contributor diagnostic preflight PASS
→ only then load
```

The acceptance probe inherits the base probe's preflight and therefore refuses to schedule load unless:

```text
binance/fred + all runner venues are fake
factor data_service_url == checked fake data URL
factor expected_data_url == checked fake data URL
macro_enabled == true
fake bars per fetch >= 1000
```

No real provider is part of the intended workload.

---

## 4. Required sustained scenarios

Keep two explicit factor symbol shapes rather than blending them.

### O1 — representative cross-sectional sustained

```text
factor symbol mode = unique within each cycle
runner traffic     = BTC / BNB / A-share / JP mix
runner stagger     = 0 initially
provider fakes     = binance,fred,baostock,yfinance
```

This is the primary sustained acceptance workload for #107.

### O2 — same-key stress control

```text
factor symbol mode = same within each cycle
all other settings = identical to O1
```

This measures whether H11 can still amplify load even if it is not the dominant reported workload.

### O3 — runner stagger control, only if H6 remains relevant

Repeat O1 with the measured stagger value from L/M while holding every other setting constant.

Do not include O3 merely because it is available; only run/use it if the earlier runner experiment shows scheduling materially changes capacity.

---

## 5. Bounded backlog behavior

The acceptance probe keeps the pending-cycle cap from v1.

When the service cannot drain work quickly enough:

```text
pending cycles >= cap
→ skip new injection
→ increment cycles_skipped_pending_cap
```

At the end it also reports:

```text
cycles_started
cycles_completed
cycles_pending_after_settle
cycle_task_errors
```

Pending cycles are cancelled only after the settle window expires and are explicitly counted.

Do not treat skipped or pending cycles as successful throughput. They are direct capacity/backlog evidence.

---

## 6. Initial duration versus PR-quality evidence

Use a short bounded run first to validate the harness:

```text
30 seconds
```

Once the topology and outputs are stable, use a longer repeated run for evidence intended for the PR, for example:

```text
60 seconds per repetition
at least 3 repetitions
```

The exact duration is not a production SLO. It is only an evidence window.

Do not cherry-pick the best repetition. Preserve and report all runs.

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

Never merge those into one global latency percentile because they represent different operations and timeout budgets.

Small mechanism probes such as D08/D10/D12 can still report their observed latency, but PR wording should not treat a handful of samples as statistically meaningful p95 evidence.

---

## 8. Progress / correctness interpretation

The sustained probes record operation progress, but zero progress is **context-dependent**.

For example:

```text
runner backfill bars_fetched = 0
```

can be legitimate when repeated polling occurs within the same market-data interval and there is nothing new to fetch.

Therefore do not classify every `progress_zero` value as a data-quality failure.

Use progress together with:

```text
HTTP/error status
GET /bars result count
latest persisted timestamp when relevant
provider logs/counters
scenario timing
```

The stronger correctness rule remains:

> HTTP 200 alone is not proof that a current-data refresh succeeded, but zero inserted/fetched rows alone is also not automatically failure.

---

## 9. Acceptance signals

For O1 record at minimum:

```text
DATA_SERVICE_UNREACHABLE / transport error count
HTTP error-code distribution
factor p50/p95/p99
runner backfill p50/p95/p99
runner bars p50/p95/p99
health p50/p95/p99
openapi p50/p95/p99
cycles started/completed
cycles skipped because pending cap was reached
cycles still pending after settle timeout
DB pool available minimum
DB pool waiting maximum
provider active peaks by venue
provider failure counts
worker PID distribution in two-worker confirmation
```

The first selected production fix is acceptable only if it improves the measured failure chain without simply moving saturation to the provider layer.

Bad outcome example:

```text
DATA_SERVICE_UNREACHABLE 20 → 0
provider failures        0 → 30
```

That is not a successful #107 fix.

---

## 10. Before / after discipline

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

The exact same sustained scenario should run before and after the selected production change.

If upstream changes between runs, re-review the #107-sensitive paths before comparing results.

---

## 11. Recommended command shape

After the safety checker passes, first smoke O1:

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

For PR-quality before/after evidence, increase the evidence window only after the 30-second run behaves predictably and preserve the same settings on both revisions.

---

## Current conclusion

The runtime plan now separates three questions cleanly:

```text
short burst
→ where is the capacity boundary?

controlled diagnostics
→ why does it happen?

sustained representative workload
→ does the selected fix actually satisfy #107 over time?
```

The previous same-key-only limitation is now retained as an explicit stress control rather than being mistaken for the canonical cross-sectional workload.
