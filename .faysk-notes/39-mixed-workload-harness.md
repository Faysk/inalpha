# Issue #107 — Mixed Factor + Runner Workload Harness

**Status:** prepared contributor diagnostic; no production code selected or modified.

**Purpose:** reproduce the workload family in issue #107 as one controlled local experiment:

```text
live factor/macro burst
+
live-runner-like fresh polling across several markets
+
unrelated DB-backed and DB-free control requests
```

All market providers are replaced by deterministic local fakes.

---

## 1. Why this is the next step

The narrow diagnostics deliberately isolate mechanisms:

```text
H1   route-scoped DB lease across provider wait
H6   aligned live-runner polls
H8   macro same-key cold stampede
H9   client timeout vs surviving server/provider work
H10  thread executor pressure
H11  whole live-score same-key cold stampede
```

Isolation is necessary to understand cause, but #107's acceptance target is a **mixed** agent + live-runner workload.

The mixed harness is the bridge between those two stages:

```text
unit/mechanism proof
→ mixed local reproduction
→ smallest fix
→ identical mixed workload after fix
```

---

## 2. Tool

```text
.faysk-notes/tools/issue107_mixed_workload_probe.py
```

It drives real localhost HTTP through:

```text
factor /score
    ↓
FactorEngine
    ↓
factor DataClient
    ↓
data-service
    ↓
real Timescale/Postgres pool
    ↓
fake Binance + fake FRED

simulated runner poll
    ↓
POST /backfill/bars
    ↓
GET /bars
    ↓
real data route + DB
    ↓
fake Binance / Baostock / yfinance
```

No strategy orders, risk actions or real provider traffic are required.

---

## 3. Mandatory safe topology and state

For exact process-local counters, start with:

```text
data workers   = 1
factor workers = 1
```

The data wrapper must fake:

```text
binance
fred
baostock
yfinance
```

and must use:

```text
ISSUE107_FAKE_BARS_PER_FETCH=1000
```

Use the dedicated benchmark DB from:

```text
41-benchmark-db-state-determinism.md
```

Recommended:

```text
benchmark DB = inalpha_issue107
```

The script refuses to run unless required provider replacement/bar batching is present, but it cannot automatically prove that your DB/cache state matches the previous comparison. That discipline is external and must be recorded.

Why 1000 bars:

- runner lookbacks should not become artificial one-bar provider loops;
- live factor 1d scoring can request hundreds of bars;
- macro warmup windows can also be long;
- one synthetic provider fetch should behave like one normal batch rather than inventing extra pressure.

---

## 4. Cold-state reset rule

This is essential because `/backfill/bars` is incremental.

For each cold M1/M2/M3 comparison:

```text
1. finish the prior wave
2. restart factor so process-local factor cache is empty
3. TRUNCATE bars in the dedicated inalpha_issue107 DB
4. verify count(*) from bars = 0
5. keep provider mode/delay and worker topology unchanged
6. run exactly one scenario
7. save its output before resetting again
```

Do not compare:

```text
M1 with empty PostgreSQL bars
against
M2/M3 after M1 already populated the same FRED/price keys
```

Restarting factor alone is **not** enough: it clears factor memory but does not clear PostgreSQL bars.

For every result label both:

```text
factor cache = cold/warm
data DB bars = cold/warm
```

---

## 5. Recommended startup

Data wrapper, from `services/data` after copying the contributor tool locally:

```bash
DATABASE_URL="$ISSUE107_DATABASE_URL" \
ISSUE107_FAKE_VENUES=binance,fred,baostock,yfinance \
ISSUE107_FAKE_BARS_PER_FETCH=1000 \
ISSUE107_PROVIDER_MODE=async \
ISSUE107_PROVIDER_DELAY_S=0.5 \
uv run uvicorn issue107_slow_data_app:app \
  --host 127.0.0.1 --port 18001 --workers 1
```

Factor should use the same dedicated DB for its optional DB paths and point to the wrapper:

```text
DATABASE_URL=<inalpha_issue107 URL>
DATA_SERVICE_URL=http://127.0.0.1:18001
```

Run factor with one worker on port `18004`.

Restart factor immediately before a run intended to represent **cold factor cache**.

---

## 6. Baseline experiment M1 — aligned mixed burst

Start from cold factor cache + cold dedicated bars, then:

```bash
uv run python issue107_mixed_workload_probe.py \
  --factor-url http://127.0.0.1:18004 \
  --data-url http://127.0.0.1:18001 \
  --factor-concurrency 4 \
  --factor-symbol-mode same \
  --runner-runs 8 \
  --runner-stagger-ms 0
```

Shape:

```text
4 concurrent cold live /score calls
+ 8 aligned runner-like fresh polls
+ health/openapi controls
```

`factor-symbol-mode=same` intentionally exposes H11 as part of the high-pressure case.

Save the complete output and state before resetting the DB for M2.

---

## 7. Experiment M2 — unique factor price keys

Reset the dedicated bars table and restart factor first, then:

```bash
uv run python issue107_mixed_workload_probe.py \
  --factor-concurrency 4 \
  --factor-symbol-mode unique \
  --runner-runs 8 \
  --runner-stagger-ms 0
```

Interpretation:

```text
main price keys differ
macro/date keys remain shared
```

This reduces whole-score same-key H11 overlap while retaining H8 macro-key overlap.

If M1 is much worse than M2 under equal DB/cache state, whole-score cold duplication may be a material multiplier.

---

## 8. Experiment M3 — runner stagger control

Reset the dedicated bars table and restart factor again so state matches M1, then:

```bash
uv run python issue107_mixed_workload_probe.py \
  --factor-concurrency 4 \
  --factor-symbol-mode same \
  --runner-runs 8 \
  --runner-stagger-ms 100
```

Only runner timing should differ from M1.

If the small stagger materially reduces peak DB waiting, errors or p95 while provider delay and total request count stay fixed, H6 gains evidence.

Do not infer that a production stagger is needed until Candidate A is also tested against the same workload.

---

## 9. What the harness measures

### Factor results

```text
HTTP status
transport exception class
machine error code
bars_used
factor count
p50 / p95 / p99
```

### Runner results

```text
backfill status / exception / code
bars status / exception / code
bars returned
p50 / p95 / p99
```

### Data wrapper deltas

```text
POST /backfill/bars
GET /bars
provider starts/completions/failures
provider calls per venue
DB pool requests
DB queue events
DB wait ms
DB errors
DB usage ms
```

### In-flight samples

```text
provider active max
provider active by venue
backfill HTTP in-flight max
bars HTTP in-flight max
pool requests waiting max
pool available min
thread active max
```

### Isolation controls

```text
/openapi.json  # DB-free
/health        # DB-backed
```

If OpenAPI stays responsive while health degrades, the evidence is more specific to DB-backed capacity than generic ASGI/event-loop failure.

---

## 10. Acceptance interpretation

The issue's target is not “every request must always be 200 under arbitrary load.”

We need to distinguish:

```text
transport/service failure
vs
explicit intentional backpressure
vs
successful but slow response
```

Before any admission-control candidate exists, primary failure signals are:

```text
factor transport failures / DATA_SERVICE_UNREACHABLE chain
runner GET /bars failures
health degradation while DB-free control survives
unbounded/large pool wait
p95/p99 blow-up
```

If a later Candidate C deliberately returns a busy response, count that separately rather than pretending it is the same as connection/read timeout.

---

## 11. Candidate A decision use

The most important before/after comparison is:

```text
current main M1/M2/M3
vs
Candidate A M1/M2/M3
```

with the same:

```text
provider mode
provider delay
DB pool
worker count
factor concurrency
runner count
stagger
factor cache condition
data DB condition
```

Use the dedicated DB reset before each cold before/after scenario.

### Candidate A is sufficient

If Candidate A produces:

```text
zero transport/unreachable failures
controlled p95
healthy DB-backed controls
acceptable provider in-flight work
```

across the agreed mixed workload, stop there for PR1.

Do **not** add factor semaphores, runner jitter or admission control merely because they could further smooth load.

### Candidate A moves the bottleneck

If DB pressure disappears but fake-provider active work becomes excessive or latency remains unbounded, Candidate C/B becomes relevant.

That is exactly why provider and pool metrics are recorded together.

---

## 12. Multi-worker confirmation

Only after the mechanism is clear with one data worker, rerun with:

```text
data workers = 2
```

matching current repository production compose.

Important limitation:

```text
asyncio locks/semaphores/counters/cache
```

are process-local. `/__issue107/state` is likewise process-local.

For two-worker evidence use:

- `X-Issue107-Worker-Pid` where available;
- per-process server logs;
- client-visible p95/errors;
- do not treat one sampled state endpoint as service-global metrics.

Use the same dedicated DB reset discipline before cold comparisons even though counters become per-process.

---

## 13. What this still does not prove

Even this mixed harness does not reproduce:

- actual third-party provider rate limits;
- real yfinance process lock behavior in the fake path;
- a seeded paper restart with candidate loading/risk/session state;
- Docker/host-level socket exhaustion;
- distributed multi-replica data-service behavior.

Those should only be added if the controlled harness leaves an important question unanswered.

The goal is not maximum realism at any cost. It is enough realism to identify the first constrained resource without external noise.
