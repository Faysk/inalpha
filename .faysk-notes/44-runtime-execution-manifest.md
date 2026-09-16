# Issue #107 — Runtime Execution Manifest

**Status:** ready for the contributor machine.  
**Purpose:** turn the investigation plan into one repeatable execution sequence with stable scenario names, inputs and evidence filenames.

This is not a performance target document. It defines **what to run**, not what result we want to see.

Authoritative interpretation/safety rules live in:

```text
11-local-test-runbook.md
49-runtime-safety-order.md
50-sustained-load-acceptance.md
52-provider-isolation-and-soak-hardening.md
```

---

## 1. Session identity

Create one result directory per baseline/fix revision outside the Git working tree.

Recommended layout:

```text
../inalpha-issue107-results/
└── YYYYMMDD-HHMMSS-baseline/
    ├── 00-environment.txt
    ├── 01-repo-checks.txt
    ├── A-data-tests.txt
    ├── A-factor-tests.txt
    ├── B-h8-macro-unit.txt
    ├── B-h11-score-unit.txt
    ├── C-h1-pool2.txt
    ├── D-load-c08.txt
    ├── D-load-c10.txt
    ├── D-load-c12.txt
    ├── E-pg-stat-activity.txt
    ├── F-h9-async.txt
    ├── F-h9-thread.txt
    ├── G-2worker-confirmation.txt
    ├── H-macro-single.txt
    ├── I-macro-same.txt
    ├── J-macro-unique.txt
    ├── L-runner-aligned.txt
    ├── M-runner-stagger100.txt
    ├── N-mixed-m1.txt
    ├── N-mixed-m2.txt
    ├── N-mixed-m3.txt
    ├── O1-sustained-unique-run1.txt
    ├── O1-sustained-unique-run2.txt
    ├── O1-sustained-unique-run3.txt
    ├── O2-sustained-same-run1.txt
    ├── O2-sustained-same-run2.txt
    ├── O2-sustained-same-run3.txt
    └── notes.md
```

Do not put secrets or raw environment dumps in the result directory.

---

## 2. Revision gate

Before every baseline/fix session record:

```text
branch
HEAD
upstream/main
origin/notes/issue-107
working-tree status
```

Baseline starts with:

```text
HEAD == fresh upstream/main
```

Candidate comparison records the exact candidate commit and uses the same workload settings.

If upstream moves between baseline and implementation, re-review sensitive paths before comparing results.

---

## 3. Shared benchmark state and safety

Unless a scenario explicitly says otherwise:

```text
benchmark DB          = inalpha_issue107
real external APIs    = excluded from load work
JWT secret            = ordinary local dev setting, never copied into results
data-service URL      = http://127.0.0.1:18001
factor-service URL    = http://127.0.0.1:18004
factor workers        = 1
```

The hardened data wrapper must:

```text
force constituent snapshot scheduler off
fake every venue intentionally used by the scenario
block every other registered OHLCV venue from provider I/O
```

Factor-driven scenarios additionally require:

```text
issue107_factor_app:app
→ issue107_target_check.py
→ issue107_target_check=PASS
```

For a DB-cold/factor-cold scenario:

```text
restart factor
→ reset only bars in inalpha_issue107
→ verify bars count = 0
→ run one scenario
→ save output before resetting again
```

Never use the ordinary developer DB for destructive reset.

---

## 4. Stage A — current repository checks

Capture independently:

```bash
bash scripts/check-consistency.sh
(cd services/data && uv run ruff check . && uv run pytest)
(cd services/factor && uv run ruff check . && uv run pytest)
```

Record mypy for touched services once a production candidate exists.

Current-main failures, if any, are baseline evidence; do not silently repair unrelated failures inside #107.

---

## 5. Stage B — structural factor diagnostics

```bash
(cd services/factor && uv run pytest -vv -s tests/test_issue107_macro_stampede_local.py)
(cd services/factor && uv run pytest -vv -s tests/test_issue107_live_cache_stampede_local.py)
```

Record exact fetch-entry counts.

These answer only:

```text
H8/H11 structural duplicate in-flight work exists? yes/no
```

They do not decide materiality to #107.

---

## 6. Stage C — deterministic H1 pool=2 proof

```bash
(cd services/data && uv run pytest -vv -s tests/test_issue107_pool_pressure_local.py)
```

Test design:

```text
control:  1 blocked provider / pool=2
pressure: 2 blocked providers / pool=2
```

Decisive observation:

```text
/openapi.json remains responsive
while
/health cannot obtain DB capacity until provider release
```

If this does not reproduce, stop treating H1 as proven and debug the diagnostic.

---

## 7. Stage D — one-worker real-TCP capacity transition

Start hardened contributor data wrapper with:

```text
data workers                 = 1
fake venues                  = binance
ISSUE107_PROVIDER_MODE       = async
ISSUE107_PROVIDER_DELAY_S    = 5
ISSUE107_FAKE_BARS_PER_FETCH = 1
```

Initial diagnostic points around the current per-process DB pool size of 10:

```text
D08 = 8 concurrent backfills
D10 = 10 concurrent backfills
D12 = 12 concurrent backfills
```

These are diagnostic points, not production limits.

Example:

```bash
uv run python issue107_load_probe.py --backfills 8  --health-probes 10 --health-timeout 1.0
uv run python issue107_load_probe.py --backfills 10 --health-probes 10 --health-timeout 1.0
uv run python issue107_load_probe.py --backfills 12 --health-probes 10 --health-timeout 1.0
```

If the local transition occurs elsewhere, add only the smallest adjacent point necessary.

Record:

```text
backfill observed latency/errors
health observed latency/errors
openapi observed latency/errors
pool available minimum
pool waiting maximum
pool wait-ms delta
provider active
rows fetched/inserted
```

D08/D10/D12 are mechanism probes. Their small samples are **not** final p95 evidence.

---

## 8. Stage E — PostgreSQL-side evidence

Use the first Stage-D point that keeps provider work blocked long enough to inspect state.

Capture:

```text
pg_stat_activity state
transaction age
last query
Psycopg pool stats at the same time
```

Do not infer app checkout state from PostgreSQL `idle` alone.

---

## 9. Stage F — H9/H10 cancellation persistence

One data worker, fake Binance, 5s delay.

### F1 async waiter

```text
mode = async
attempts = 4
client timeout = 0.5s
settle > provider delay
```

### F2 thread-backed waiter

Same parameters, only:

```text
mode = thread
```

Run:

```bash
uv run python issue107_timeout_persistence_probe.py \
  --attempts 4 --request-timeout 0.5 --settle-wait 6
```

Record async provider and sync-thread counters separately.

---

## 10. Stage G — current production-like worker count

Repeat the already-understood low-level workload with:

```text
data workers = 2
```

Do not mechanically double every concurrency value. First rerun a known reproducer and increase only enough if necessary.

Primary evidence:

```text
client-visible latency/errors
worker PID distribution
per-worker logs/state samples
```

Process-local state is not container-global.

---

## 11. Stage H/I/J/K — factor macro path

For each independent cold comparison:

```text
data workers                 = 1
factor workers               = 1
fake venues                  = binance,fred
ISSUE107_FAKE_BARS_PER_FETCH = 1000
provider mode                = async
provider delay               = 0.25s initially
```

Require the no-load target checker to PASS for `binance,fred` before generating score load.

Run:

```text
H  cold single caller
I  cold 6 callers, same symbol
J  cold 6 callers, unique price symbols
K  immediate warm repeat where intended
```

The six callers are a controlled amplification probe, not a proposed service limit.

Record actual:

```text
POST /backfill/bars delta
GET /bars delta
Binance provider starts
FRED provider starts
pool wait/availability
factor errors/latency
bars_used / factor count
```

Do not replace runtime counts with the static 18-series number.

---

## 12. Stage L/M — runner alignment

Reset benchmark bars before each comparison.

```text
data workers                 = 1
fake venues                  = binance,baostock,yfinance
ISSUE107_FAKE_BARS_PER_FETCH = 1000
runs                         = 8
rounds                       = 1
```

Compare only scheduling:

```text
L: --stagger-ms 0
M: --stagger-ms 100
```

If 100ms is ambiguous, 250ms is an optional second control; do not also change provider delay.

---

## 13. Stage N — mixed issue-level burst baseline

```text
data workers                 = 1
factor workers               = 1
fake venues                  = binance,fred,baostock,yfinance
ISSUE107_FAKE_BARS_PER_FETCH = 1000
factor concurrency           = 4
runner runs                  = 8
```

Require target-check PASS.

Reset factor cache + benchmark bars independently before:

```text
M1  factor same-symbol + runner stagger 0
M2  factor unique price keys + runner stagger 0
M3  factor same-symbol + runner stagger 100ms
```

M1↔M2 isolates whole-score same-key amplification while retaining shared macro keys.

M1↔M3 isolates runner scheduling sensitivity.

Stage N is a combined burst/reproduction stage. Preserve observed percentiles, but do not use it as the final sustained p95 claim.

---

## 14. Stage O — sustained acceptance

Use `issue107_sustained_acceptance_probe.py` only after the preceding mechanisms are understood.

First run a 30-second smoke. Once stable, use the same evidence window for baseline and candidate, for example:

```text
60 seconds
3 repetitions
```

### O1 — primary cross-sectional sustained

```text
factor symbol mode = unique
factor concurrency = 4
runner runs        = 8
runner stagger     = 0
fake venues        = binance,fred,baostock,yfinance
```

Save all repetitions:

```text
O1-sustained-unique-run1.txt
O1-sustained-unique-run2.txt
O1-sustained-unique-run3.txt
```

### O2 — same-key stress control

Change only:

```text
factor symbol mode = same
```

Save all repetitions.

### O3 — optional runner stagger

Only if L/M shows H6 remains relevant. Change only runner stagger from O1.

Record separately:

```text
factor p50/p95/p99
runner backfill p50/p95/p99
runner bars p50/p95/p99
health p50/p95/p99
openapi p50/p95/p99
cycles started/completed
cycles skipped pending cap
cycles skipped schedule lag
cycles pending after settle
provider start/completion/cancel/fail deltas
pool queue/wait deltas
```

Important:

```text
cycles_skipped_schedule_lag > material noise
→ inspect generator/machine before attributing result to service capacity
```

The issue asks for controlled p95 but does not state a numeric SLO. Report measured p95 for the documented workload; do not invent a project threshold.

---

## 15. Decision gate after baseline

Fill `04-baseline-results.md` and `51-sustained-results-template.md` and answer:

```text
1. What resource degrades first?
2. Can we connect it to the visible #107 failure chain?
3. Which hypotheses received negative evidence?
4. What is the smallest change that removes the measured cause?
5. Which invariant/caller behavior could that change break?
6. Does O1 confirm the problem under sustained representative load?
```

Possible outcomes:

```text
H1 material        → Candidate A
provider overload  → Candidate C / provider-specific control
H8/H11 material    → factor-side coalescing/bounded work only if still needed
H3 material        → HTTP-client lifetime candidate
H6 material after data fix → runner scheduling discussion/alignment
none                → keep investigating
```

Do not combine candidates merely because multiple diagnostics are interesting.

---

## 16. Candidate comparison if selected

For Candidate A, only after H1 selects it:

```text
materialize patch/regression
implement cleanly against current reviewed main
run repository tests
run deterministic Candidate-A regression
repeat the same representative D/H-L/N/O scenarios
```

Before/after must keep constant:

```text
DB reset state
factor cache state
worker topology
provider fake mode
provider delay
bars-per-fetch
caller concurrency
runner stagger
client timeouts
O-stage duration + interval
```

Also apply the correctness gate in `43-candidate-a-overlap-write-correctness.md` if H4 shows material same-key duplicate refreshes.

---

## 17. Stop condition

PR1 is done when the smallest selected change:

```text
removes the measured #107 failure under the representative workload
keeps current-data freshness semantics
keeps explicit provider failures visible
keeps caller/auth/service boundaries intact
has deterministic regression coverage
shows no moved bottleneck severe enough to fail the same workload
```

Do not add extra optimizations afterward merely because the harness reveals future tuning opportunities.
