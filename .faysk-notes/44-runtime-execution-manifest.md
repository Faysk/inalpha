# Issue #107 — Runtime Execution Manifest

**Status:** ready for the contributor machine.  
**Purpose:** turn the investigation plan into one repeatable execution sequence with stable scenario names, inputs and evidence filenames.

This is not a performance target document. It defines **what to run**, not what result we want to see.

The authoritative interpretation rules remain in `11-local-test-runbook.md` and `04-baseline-results.md`.

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

Baseline must begin with:

```text
HEAD == fresh upstream/main
```

Candidate comparison must record the exact candidate commit and use the same workload settings.

If upstream moves between baseline and implementation, re-review the sensitive paths before comparing results.

---

## 3. Shared benchmark state

Unless a scenario explicitly says otherwise:

```text
benchmark DB          = inalpha_issue107
real external APIs    = disabled/replaced by fakes for load work
JWT secret            = ordinary local dev setting, never copied into results
data-service URL      = http://127.0.0.1:18001
factor-service URL    = http://127.0.0.1:18004
factor workers        = 1
```

For a DB-cold/factor-cold scenario:

```text
stop/restart factor
→ reset only bars in inalpha_issue107
→ verify bars count = 0
→ run one scenario
→ save output before resetting again
```

Never use the ordinary developer DB for the destructive reset.

---

## 4. Stage A — current repository checks

Capture independently:

```bash
bash scripts/check-consistency.sh
(cd services/data && uv run ruff check . && uv run pytest)
(cd services/factor && uv run ruff check . && uv run pytest)
```

Also record `mypy` output for touched services when the production candidate exists.

Current-main failures, if any, are baseline evidence; do not silently repair unrelated failures inside #107.

---

## 5. Stage B — structural factor diagnostics

Run with the contributor diagnostics materialized but before any production change:

```bash
(cd services/factor && uv run pytest -vv -s tests/test_issue107_macro_stampede_local.py)
(cd services/factor && uv run pytest -vv -s tests/test_issue107_live_cache_stampede_local.py)
```

Record exact fetch-entry counts.

These answer only:

```text
H8/H11 structural duplicate in-flight work exists? yes/no
```

They do not decide whether it is material to #107.

---

## 6. Stage C — deterministic H1 pool=2 proof

Run:

```bash
(cd services/data && uv run pytest -vv -s tests/test_issue107_pool_pressure_local.py)
```

Expected **test design**, not assumed result:

```text
control:  1 blocked provider / pool=2
pressure: 2 blocked providers / pool=2
```

The decisive observation is whether:

```text
/openapi.json remains responsive
while
/health cannot get DB capacity until provider release
```

If this does not reproduce, stop treating H1 as proven and debug the diagnostic before moving on.

---

## 7. Stage D — one-worker real-TCP capacity transition

Start contributor data wrapper with:

```text
data workers                 = 1
fake venues                  = binance
ISSUE107_PROVIDER_MODE       = async
ISSUE107_PROVIDER_DELAY_S    = 5
ISSUE107_FAKE_BARS_PER_FETCH = 1
```

Use three initial concurrency points around the known per-process DB-pool size of 10:

```text
D08 = 8 concurrent backfills
D10 = 10 concurrent backfills
D12 = 12 concurrent backfills
```

These are diagnostic points around the current capacity boundary, **not proposed production limits**.

Example:

```bash
uv run python issue107_load_probe.py --backfills 8  --health-probes 10 --health-timeout 1.0
uv run python issue107_load_probe.py --backfills 10 --health-probes 10 --health-timeout 1.0
uv run python issue107_load_probe.py --backfills 12 --health-probes 10 --health-timeout 1.0
```

The load probe fails closed unless it detects the contributor wrapper and fake Binance.

If the transition occurs earlier/later because of local scheduling, add the smallest adjacent point needed to locate it. Do not launch a huge sweep just to produce a prettier chart.

Record:

```text
backfill p50/p95/p99
health p50/p95/p99
openapi p50/p95/p99
ReadTimeout/ConnectTimeout/etc
pool available minimum
pool waiting maximum
pool wait-ms delta
provider active
rows actually fetched/inserted
```

---

## 8. Stage E — PostgreSQL-side evidence

Use the first Stage-D point that clearly holds provider calls long enough to observe the DB state.

Follow `25-pg-stat-activity-diagnostic.md` and capture:

```text
pg_stat_activity state
xact age
last query
Psycopg pool stats at the same time
```

Do not infer checked-out status from PostgreSQL `idle` alone; correlate with pool stats.

---

## 9. Stage F — H9/H10 cancellation persistence

One data worker, fake Binance, delay 5s.

### F1 async provider waiter

```text
mode = async
attempts = 4
client timeout = 0.5s
settle > provider delay
```

### F2 thread-backed provider waiter

Same parameters, only:

```text
mode = thread
```

Run:

```bash
uv run python issue107_timeout_persistence_probe.py \
  --attempts 4 --request-timeout 0.5 --settle-wait 6
```

Record async-provider and sync-thread counters separately.

---

## 10. Stage G — current production-like worker count

Repeat the **already-understood** low-level workload with:

```text
data workers = 2
```

Do not start by doubling every concurrency value mechanically.

First rerun a point that reproduced pressure with one worker. If it no longer produces useful evidence, increase only enough to cross the observed two-worker service boundary.

Primary evidence becomes:

```text
client-visible latency/errors
worker PID distribution
per-worker logs/state samples
```

Do not sum one worker's `/__issue107/state` as though it were global service state.

---

## 11. Stage H/I/J/K — factor macro path

Start from DB-cold + factor-cold state for each independent cold comparison.

Topology:

```text
data workers                 = 1
factor workers               = 1
fake venues                  = binance,fred
ISSUE107_FAKE_BARS_PER_FETCH = 1000
provider mode                = async
provider delay               = 0.25s initially
```

Run in this order:

```text
H  cold single caller
I  cold 6 callers, same symbol
J  cold 6 callers, unique price symbols
K  immediate warm repeat of the corresponding first wave where intended
```

The `6` callers are a controlled amplification probe, not a proposed service concurrency limit.

Record actual:

```text
POST /backfill/bars delta
GET /bars delta
Binance provider starts
FRED provider starts
pool wait/availability
factor latency/error classes
bars_used/factor count
```

Do not replace runtime provider counts with the static `18 FRED series` number.

---

## 12. Stage L/M — runner alignment

For each comparison reset benchmark bars first.

Topology:

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

If 100ms is ambiguous, 250ms is an optional second control; do not change provider delay at the same time.

---

## 13. Stage N — issue-level mixed baseline

Exact-count first pass:

```text
data workers                 = 1
factor workers               = 1
fake venues                  = binance,fred,baostock,yfinance
ISSUE107_FAKE_BARS_PER_FETCH = 1000
factor concurrency           = 4
runner runs                  = 8
```

Reset factor cache + benchmark bars independently before M1/M2/M3.

```text
M1  factor same-symbol + runner stagger 0
M2  factor unique price keys + runner stagger 0
M3  factor same-symbol + runner stagger 100ms
```

M1↔M2 primarily tests whole-score same-key amplification while retaining shared macro keys.

M1↔M3 primarily tests runner alignment.

Run the first stable baseline scenario at least 3 times before using its p95/error count in PR evidence. Preserve all runs, not only the best one.

---

## 14. Decision gate after baseline

Fill `04-baseline-results.md` and answer in this order:

```text
1. What resource degrades first?
2. Can we connect that degradation to the user-visible #107 failure chain?
3. Which hypotheses received negative evidence?
4. What is the smallest change that removes the measured cause?
5. Which invariant/caller behavior could that change break?
```

Then choose:

```text
H1 material        → Candidate A
provider overload  → Candidate C / provider-specific control
H8/H11 material    → factor-side coalescing/bounded work only if still needed
H3 material        → HTTP-client lifetime candidate
H6 material after data fix → runner scheduling discussion/alignment
none                → keep investigating
```

Do not combine candidates just because several diagnostics are interesting.

---

## 15. Candidate-A comparison if selected

Only after H1 selects Candidate A:

```text
materialize candidate patch/regression
implement cleanly against current reviewed main
run repository tests
run Candidate-A deterministic regression
repeat the SAME Stage-D point
repeat SAME relevant macro/runner/mixed scenarios
```

For every before/after comparison keep constant:

```text
DB reset state
factor cache state
workers
provider fake mode
provider delay
bars-per-fetch
caller concurrency
runner stagger
client timeouts
```

Also check the correctness guard in `43-candidate-a-overlap-write-correctness.md` if H4 shows material same-key duplicate refreshes.

---

## 16. Stop condition

PR1 is done when the smallest selected change:

```text
removes the measured #107 failure under the representative workload
keeps current-data freshness semantics
keeps explicit provider failures visible
keeps caller/auth/service boundaries intact
has deterministic regression coverage
shows no moved bottleneck severe enough to fail the same workload
```

Do not add additional optimizations after that merely because the benchmark exposes future tuning opportunities.
