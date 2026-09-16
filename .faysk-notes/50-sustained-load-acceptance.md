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

## 2. Prepared bounded soak tool

Contributor-only tool:

```text
tools/issue107_sustained_mixed_probe.py
```

Materialized as:

```text
services/factor/issue107_sustained_mixed_probe.py
```

It combines bounded repeated cycles of:

```text
factor /score traffic
+ runner-like fresh backfill/read traffic
+ /health DB-backed controls
+ /openapi.json DB-free controls
```

It refuses to run unless the contributor data/factor safety endpoints prove that factor is routed to the intended fake data service and every required provider venue is fake.

It also caps the number of pending cycles. When the service falls behind, new cycles are skipped instead of allowing an unbounded local request backlog.

`cycles_skipped_pending_cap` is therefore a capacity signal and must be reported, not hidden.

---

## 3. Important static-review limitation in v1

The current v1 sustained tool creates one new factor symbol per cycle and then sends `factor_concurrency` concurrent requests for **that same symbol**.

Therefore:

```text
factor_concurrency > 1
```

also exercises H11 same-score-key cold duplication inside every cycle.

That is a useful stress case, but it is **not identical to the issue's cross-sectional multi-symbol agent workload**.

Do not describe v1 sustained results as the canonical cross-sectional acceptance result unless the probe is extended to support distinct factor symbols within each cycle.

Runtime interpretation:

```text
v1 same-key sustained
→ H11-heavy stress evidence

cross-sectional sustained
→ still needs unique-symbol-per-cycle-wave support before final issue-level p95 evidence
```

This distinction prevents us from overloading a pathological same-key pattern and then claiming it exactly represents the reported production workload.

---

## 4. Required sustained scenarios

After the probe supports both symbol shapes, keep two explicit scenarios rather than blending them:

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

## 5. Initial duration versus PR-quality evidence

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

## 6. Percentile interpretation

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

## 7. Progress / correctness interpretation

The sustained probe records operation progress, but zero progress is **context-dependent**.

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

## 8. Acceptance signals

For the representative sustained workload, record at minimum:

```text
DATA_SERVICE_UNREACHABLE / transport error count
HTTP error-code distribution
factor p50/p95/p99
runner backfill p50/p95/p99
runner bars p50/p95/p99
health p50/p95/p99
openapi p50/p95/p99
cycles started
cycles skipped because pending cap was reached
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

## 9. Before / after discipline

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
client timeouts
```

The exact same sustained scenario should run before and after the selected production change.

If upstream changes between runs, re-review the #107-sensitive paths before comparing results.

---

## 10. Tooling follow-up before runtime acceptance

Before using sustained results in the PR, extend/review the tool so that it can explicitly choose:

```text
--factor-symbol-mode same
--factor-symbol-mode unique
```

and ensure scheduling does not inject a cycle after the requested duration boundary.

Also make settle-timeout failures preserve enough partial evidence to diagnose backlog rather than only terminating without a final summary.

These are contributor-tool quality improvements, not production-scope changes.

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

Do not use the sustained v1 same-key stress output as the final cross-sectional acceptance evidence until its factor symbol shape is made representative.
