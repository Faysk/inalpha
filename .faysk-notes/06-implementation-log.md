# Issue #107 — Implementation / Investigation Log

Chronological contributor log. Keep this factual: what was reviewed, what changed in **notes/tooling only**, what remains unproven, and why a production decision has or has not been made.

No runtime result is recorded here until it has actually been executed on the contributor machine.

---

## 2026-09-16 — repository / scope established

- Fork: `Faysk/inalpha`.
- Contribution branch: `fix/data-service-saturation`.
- Contributor documentation branch: `notes/issue-107`.
- Reviewed architecture, contribution rules, CI, service boundaries, data/factor/paper code paths and issue #107.
- Confirmed current `main` already contains partial mitigation versus the original June issue:
  - panel fan-out bounded;
  - panel avoids per-symbol forced fresh backfills;
  - `/backfill/bars` resumes incrementally from cached latest bar;
  - factor GET has bounded transport retry/backoff.
- Decision: reproduce current behavior rather than mechanically implement the original issue TODO.

---

## 2026-09-16 — current backfill resource lifetime

Static inspection confirmed current route shape:

```text
POST /backfill/bars
→ FastAPI DBConn checkout
→ latest_bar_ts()
→ external connector.fetch_bars()
→ insert_bars()
→ possible more provider/write batches
→ route exit releases DB connection
```

Therefore scarce DB capacity is held across external provider I/O.

Qualification recorded immediately:

```text
confirmed lifetime behavior ≠ measured root cause
```

`insert_bars()` commits every batch, so current behavior is already batch-durable rather than one request-wide DB transaction.

---

## 2026-09-16 — static capacity / timeout chain

Confirmed:

```text
shared DB pool max_size = 10 per process
shared DB checkout timeout = 30s
production data workers = 2
factor GET /bars timeout ≈ 30s
factor transport retries = bounded
/health and /bars require DBConn
```

This produced:

```text
H1   provider waits retain DB slots and starve unrelated DB-backed traffic
H1b  DB waiting crosses caller deadlines and surfaces as RequestError/retry/
     DATA_SERVICE_UNREACHABLE
```

No root-cause conclusion was made from static timing alone.

---

## 2026-09-16 — caller / provider review

Provider behavior matters because current route ordering can retain DB while waiting for provider-specific capacity:

- yfinance has process-local serialization/protection;
- Baostock/Tencent has source locking/throttling and thread-backed work;
- FRED uses `asyncio.to_thread`;
- provider controls are not one uniform global gate.

Caller failure semantics also differ:

- factor refresh is best effort and does not treat a plain non-2xx backfill POST as a transport exception before continuing to GET bars;
- paper fresh reads intentionally attempt cached DB read after refresh failure;
- other callers have different explicit/best-effort behavior.

Decision: no generic 429/503 admission response until runtime evidence says admission is needed and caller semantics are designed safely.

---

## 2026-09-16 — factor amplification hypotheses

Confirmed current macro shape:

```text
26 macro factor specs
→ 18 unique FRED series
```

Identified separately:

```text
H8   same macro/date key can duplicate during concurrent cold misses
H11  same whole live-score key can duplicate during concurrent cold misses
H3   short-lived factor HTTP clients may add connection churn (lower priority)
```

Prepared pure factor diagnostics for H8/H11. They prove/falsify structure only, not service-level materiality.

---

## 2026-09-16 — deterministic H1 proof prepared

Replaced the early “9 vs 10 normal pool connections” idea with a controlled property test using:

```text
pool max_size = 2
```

Baseline property:

```text
1 blocked provider request
→ /health should retain one free DB slot

2 blocked provider requests
→ /openapi.json should remain alive
→ /health should wait until provider release
```

This isolates DB-backed starvation from generic ASGI/event-loop starvation.

Prepared a separate **post-Candidate-A** regression with pool=2 and four provider waits; it is intentionally not materialized during baseline.

---

## 2026-09-16 — Candidate A drafted but not selected

Unapplied candidate:

```text
short get_conn() for latest_bar_ts
→ release DB
→ provider I/O
→ short get_conn() for insert_bars
```

Static review:

- uses existing public `get_conn()`;
- no `_shared` modification;
- no request/response schema change;
- no freshness/retry/admission change;
- preserves existing per-batch commit boundary;
- increases checkout frequency for multi-batch requests but greatly shortens lease duration;
- can expose more provider concurrency because DB is no longer an accidental provider gate.

The project already uses the same resource-ordering principle in live-runner M-1 paths:

```text
short DB work
→ release
→ external HTTP
→ short DB work
```

Candidate A remains a candidate, not a conclusion.

---

## 2026-09-16 — cancellation / executor diagnostics prepared

Contributor data wrapper and probes support:

```text
async provider wait
thread-backed provider wait
```

with separate counters for provider waiter vs underlying sync-thread lifetime.

Hypotheses:

```text
H9   caller timeout may leave server/provider work alive long enough to overlap retries
H10  thread-backed provider work may outlive cancelled asyncio waiters and become another constraint
```

---

## 2026-09-16 — live-runner model refined

Confirmed runner polling shape:

```text
fresh read
→ POST /backfill/bars best effort
→ GET /bars
```

Similar polling intervals can remain aligned because there is no inherent per-run jitter in the normal loop.

H6:

```text
aligned runner polling may concentrate otherwise-valid fresh work into bursts
```

Prepared aligned-vs-staggered runner probe without modifying paper/live-runner production code.

Also corrected restart assumptions: lineage/timeframe determine factor baseline fan-out; not every resumed run necessarily triggers the full macro universe.

---

## 2026-09-16 — full-stack / mixed workload prepared

Prepared contributor-only real-local-HTTP path:

```text
factor
→ FactorEngine/DataClient
→ data-service
→ real DB pool
→ deterministic fake providers
```

Macro scenarios distinguish:

```text
cold single
cold same-symbol concurrent
cold unique-price-key concurrent
warm control
```

Mixed burst scenarios:

```text
M1 same factor key + aligned runners
M2 unique factor price keys + aligned runners
M3 same factor key + staggered runners
```

These separate H11 and H6 while retaining the shared macro component.

---

## 2026-09-16 — DB/cache benchmark determinism hardened

Created dedicated benchmark DB discipline:

```text
inalpha_issue107
```

and safe reset helpers hard-coded to that database/table.

Every cold scenario explicitly distinguishes:

```text
factor process cache = cold/warm
data bars DB          = cold/warm
```

This prevents a later scenario from accidentally looking better because a previous run already populated PostgreSQL.

---

## 2026-09-16 — benchmark target safety hardened

Found a serious contributor-tooling risk: checking only the fake data URL was insufficient if factor internally still pointed to ordinary `:8001`.

Prepared `issue107_factor_app.py`:

```text
FactorSettings.data_service_url must equal ISSUE107_EXPECT_DATA_URL
or process refuses startup
```

Prepared no-load `issue107_target_check.py` to validate factor→data routing before `/score` load.

---

## 2026-09-16 — data-wrapper provider isolation hardened

A second safety review found that the normal data lifespan can start `ConstituentSnapshotScheduler`, whose configured loop performs a catch-up tick immediately before its first sleep.

Even though `CONSTITUENT_SNAPSHOT_INDICES` defaults empty, a contributor's normal root `.env` could enable it and create unrelated provider traffic during the capacity benchmark.

The contributor data wrapper now:

```text
forces CONSTITUENT_SNAPSHOT_INDICES="" before importing data main
runs normal DB/service lifespan
replaces explicitly requested OHLCV venues with deterministic fakes
replaces every other already-registered OHLCV venue with a fail-closed blocker
```

`/__issue107/state` exposes:

```text
fake_venues
blocked_venues
snapshot_scheduler_forced_disabled
```

and the no-load target checker requires a safe state.

This hardening is contributor-only; production scheduler/connector behavior is unchanged.

Documented in `52-provider-isolation-and-soak-hardening.md`.

---

## 2026-09-16 — sustained acceptance corrected

Issue #107 asks about **sustained** concurrency and controlled p95, so small transition probes cannot be the final latency evidence.

The first soak helper was retained as same-key-heavy H11 stress machinery.

Prepared acceptance-oriented soak:

```text
O1 --factor-symbol-mode unique
→ primary cross-sectional workload

O2 --factor-symbol-mode same
→ H11 stress control

O3 runner stagger
→ only if earlier H6 evidence remains material
```

Generator discipline was hardened:

```text
pending cap reached
→ cycles_skipped_pending_cap

load-generator misses a slot by >= one interval
→ cycles_skipped_schedule_lag
→ do NOT replay missed slot as catch-up burst
```

Also records partial pending work after settle timeout instead of losing the whole summary.

For PR-quality sustained evidence the current plan is:

```text
30s smoke
→ stable longer window, e.g. 60s
→ at least 3 repetitions
→ preserve all runs
```

The issue specifies no numeric p95 SLO; do not invent one.

---

## 2026-09-16 — sustained moved-bottleneck metrics added

O-stage acceptance now captures, for one data worker, exact before/after process-local deltas for:

```text
POST backfill / GET bars
provider start/completion/cancel/fail
per-venue provider outcomes
thread lifetime
DB pool request/queue/wait/error/usage metrics
```

Two-worker runs remain per-process; exact deltas are invalid when before/after state is served by different PIDs.

This makes the “do not move the problem” rule measurable:

```text
DB failures improve
but provider failures materially increase
→ not success
```

---

## 2026-09-16 — Candidate A revalidated against current main

Re-read current:

```text
services/data/api/backfill.py
services/_shared/db.py
services/data/storage/bars.py
services/data tests/conftest.py
test_backfill_router.py
```

Confirmed Candidate A remains mechanically coherent with current main if H1 selects it:

```text
existing get_conn() is sufficient
DBConn removal is internal FastAPI wiring, not external API schema
insert_bars already commits every batch
existing integration tests initialize the shared pool used by get_conn()
```

Hardened post-fix regression also disables the constituent scheduler during its test fixture.

Same-key completion-order correctness and provider-capacity release remain explicit post-selection gates.

Documented in `53-candidate-a-current-main-revalidation.md`.

---

## Current authoritative execution sequence

Use `11-local-test-runbook.md` + `44-runtime-execution-manifest.md`:

```text
A  untouched repo checks
B  pure H8/H11 structural diagnostics
C  controlled H1 pool=2 proof
D  one-worker Uvicorn capacity transition
E  pg_stat_activity + pool evidence
F  H9/H10 cancellation/thread persistence
G  two-worker production-like confirmation
H–K factor macro single/same/unique/warm
L–M runner aligned/staggered
N  mixed M1/M2/M3 burst reproduction
O1 sustained cross-sectional acceptance
O2 sustained same-key stress
O3 optional stagger control
→ fill baseline evidence
→ select exactly one smallest first production intervention, or none
```

Candidate A is **not** applied before the decision gate.

---

## Current status

Completed statically / tooling only:

- [x] architecture/business/contribution review
- [x] current issue path map
- [x] DB lease/timeout/caller/provider analysis
- [x] Candidate A/B/C/D hypotheses documented
- [x] deterministic H1 diagnostic
- [x] H8/H11 diagnostics
- [x] H9/H10 diagnostics
- [x] macro, runner and mixed harnesses
- [x] dedicated benchmark DB/reset safety
- [x] factor→data target fail-closed wrapper/checker
- [x] startup scheduler isolation
- [x] non-fake OHLCV venue blocking
- [x] sustained O1/O2 acceptance harness
- [x] missed-slot / backlog accounting
- [x] provider/DB moved-bottleneck counters
- [x] Candidate A current-main revalidation
- [x] current upstream SHA rechecked
- [x] contribution branch rechecked identical to main

Still requiring contributor runtime:

- [ ] install/sync dependencies on contributor machine
- [ ] start local Postgres/Timescale and migrate dedicated DB
- [ ] run untouched data/factor tests
- [ ] execute A–N diagnostics/reproduction
- [ ] execute sustained O1/O2 smoke and repeated evidence runs
- [ ] fill `04-baseline-results.md` + `51-sustained-results-template.md`
- [ ] identify first constrained resource with evidence
- [ ] select Candidate A/B/C/D or reject them
- [ ] only then alter production branch/code
- [ ] rerun identical before/after workloads

---

## Investigation rules

1. Change one meaningful variable at a time where possible.
2. Preserve failing reproduction before fixing it.
3. Record exact SHA and worker topology for every run.
4. Never stress real market-data providers for load testing.
5. Treat harness scheduling lag separately from service backlog.
6. Do not interpret external-provider failure as data-service saturation without evidence.
7. Do not call lower errors a success if freshness/correctness weakened.
8. HTTP 200 alone is not refresh success; zero backfill rows alone is not automatically failure either.
9. Rerun the exact same representative workload after the selected fix.
10. Record negative evidence and rejected hypotheses.
11. Keep contributor harnesses/notes out of the upstream PR unless explicitly requested.
12. Do not claim capacity/SLO beyond the tested workload/topology.
