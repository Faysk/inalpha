# Issue #107 — Implementation / Investigation Log

Chronological contributor log. Keep this factual: what was reviewed, what changed in the **notes/tooling only**, what remains unproven, and why a production decision has or has not been made.

---

## 2026-09-16 — setup and scope

- Created/confirmed contributor fork `Faysk/inalpha`.
- Contribution branch: `fix/data-service-saturation`.
- Contributor documentation branch: `notes/issue-107`.
- Reviewed architecture, service boundaries, current-state docs, CI, contribution rules, PR templates, security policy, service READMEs and relevant factor/data/paper paths.
- Confirmed #107 is still open and that current `main` already contains partial mitigation compared with the original June issue:
  - panel fetch concurrency is bounded at 16;
  - panel scoring avoids per-symbol forced fresh backfills;
  - `/backfill/bars` is incremental from the latest cached bar;
  - factor GET has bounded transport retry/backoff.
- Decision: do not blindly implement the original issue TODO; reproduce current behavior first.

---

## 2026-09-16 — current backfill resource ordering

Static inspection confirmed:

```text
POST /backfill/bars
→ route-level DBConn checkout
→ latest_bar_ts()
→ external connector.fetch_bars()
→ insert_bars()
→ repeat as needed
→ route exit returns DB connection
```

The route therefore retains scarce DB capacity across external I/O.

Important qualification:

```text
confirmed lifetime behavior ≠ measured root cause
```

`insert_bars()` commits each batch explicitly, so current backfill is already durable per batch rather than one request-wide transaction.

The first timestamp SELECT can leave a read transaction open during the first provider wait; after a batch commit later waits may no longer have an open transaction, but the pool lease is still retained.

---

## 2026-09-16 — DB pool / timeout chain

Confirmed current static values:

```text
shared DB pool max_size = 10 per process
shared DB pool checkout timeout = 30s
data production workers = 2
factor GET /bars HTTP timeout ≈ 30s
factor GET transport retries = 3
```

`/health` and `/bars` both require `DBConn`.

This produced runtime hypotheses:

```text
H1   slow backfill provider waits retain DB slots and starve DB-backed traffic
H1b  DB wait reaches caller deadline and becomes RequestError/retry/
     DATA_SERVICE_UNREACHABLE
```

No production conclusion was made from static timing alone.

---

## 2026-09-16 — provider and caller review

Confirmed provider-specific behavior:

- yfinance serializes history fetches per process and has a dedicated bounded executor;
- baostock/Tencent also throttles/serializes external work and uses thread-backed operations;
- FRED uses `asyncio.to_thread` and has no local data-service admission gate.

This matters because current route ordering can reserve DB capacity while a request is waiting for provider capacity.

Confirmed caller semantics differ:

- factor best-effort refresh does not inspect plain non-2xx POST status before continuing to GET bars;
- paper parses explicit backfill errors but `get_bars(fresh=True)` intentionally continues to cached DB read after refresh failure;
- research/dashboard have their own best-effort behavior;
- orchestration treats non-2xx as explicit errors.

Decision: do **not** add a generic 429/503 admission response until caller compatibility is designed and evidence says admission control is needed.

---

## 2026-09-16 — factor amplification hypotheses

Confirmed live/current factor behavior:

```text
26 macro factor specs
→ 18 unique FRED series
```

Macro fetching uses concurrent gather.

Two distinct cold-cache stampede hypotheses were identified:

```text
H8   same macro/date key can be fetched by several cold callers before first cache put
H11  same whole live-score cache key can be recomputed/fetched by several cold callers
     before first score cache put
```

Factor also constructs short-lived `DataClient` / `httpx.AsyncClient` objects per `_fetch_df`, retained as low-priority connection-churn hypothesis H3.

Prepared contributor-only pure unit diagnostics:

```text
tools/test_macro_cache_stampede_draft.py
tools/test_factor_live_cache_stampede_draft.py
```

They prove/falsify structure only; service-level materiality remains a runtime question.

---

## 2026-09-16 — deterministic H1 diagnostic

The early idea of relying on the normal 10-connection pool was replaced with a stronger deterministic test.

Prepared:

```text
tools/test_backfill_pool_pressure_draft.py
```

The test forces:

```text
DB pool max_size = 2
```

Control:

```text
1 blocked fake-provider backfill
→ 1/2 pool slots retained
→ /health should succeed
```

Pressure:

```text
2 blocked fake-provider backfills
→ 2/2 pool slots retained
→ /openapi.json should remain responsive
→ /health should block until provider release
```

This isolates DB-backed starvation from generic ASGI/event-loop starvation and does not depend on ordinary pool tuning.

Prepared post-fix Candidate A regression:

```text
tools/test_candidate_a_regression_draft.py
```

Target property with pool=2:

```text
4 slow provider requests can all reach provider I/O
while
/health still acquires DB capacity
```

No external market-data provider is used.

---

## 2026-09-16 — Candidate A design, still unapplied

Prepared an **unapplied** patch draft:

```text
tools/candidate_a_narrow_db_lease.patch
```

Shape:

```text
short get_conn() for latest_bar_ts
→ release DB
→ external provider I/O
→ short get_conn() for persistence
```

Static review found:

- no `_shared` change required;
- successful API request/response shape can remain the same;
- existing UPSERT/idempotency remains;
- batch commit semantics remain;
- pure validation can occur before DB checkout, so failure precedence can improve/change under simultaneous invalid request + DB outage;
- checkout count increases for multi-batch requests while checkout duration shrinks;
- provider concurrency may become more visible once DB is no longer the accidental queue.

Candidate A remains **unselected** until H1 is reproduced.

---

## 2026-09-16 — project precedent for Candidate A

A particularly strong project-fit finding was confirmed in `paper/live_runner.py`.

The project already explicitly applies the rule:

```text
DB read
→ release connection
→ external HTTP
→ DB write
```

for live-runner FX/funding paths, with comments explaining that slow external HTTP must not monopolize DB pool capacity under concurrent runs.

This directly matches Candidate A's intended resource ordering.

Conclusion:

```text
if runtime H1 selects Candidate A,
its design follows an existing Inalpha reliability principle rather than introducing a new one
```

This does not replace runtime evidence.

Documented in:

```text
37-existing-db-http-separation-precedent.md
```

---

## 2026-09-16 — H9/H10 diagnostics

Prepared real-TCP contributor wrapper/probes to distinguish client timeout from server/provider work lifetime.

Tools:

```text
issue107_slow_data_app.py
issue107_load_probe.py
issue107_timeout_persistence_probe.py
```

The fake provider supports:

```text
async mode   # cooperative asyncio wait
thread mode  # synchronous work behind asyncio.to_thread
```

Counters include:

```text
provider started/active/completed/cancelled/failed
thread active/started/completed
worker PID
per-path HTTP totals/in-flight
Psycopg pool get_stats()
```

Hypotheses:

```text
H9   client deadline may leave older server/provider work alive long enough to overlap new work
H10  thread-backed provider execution may create a different cancellation/executor constraint
```

---

## 2026-09-16 — live runner traffic model

Confirmed paper is intentionally single-process because live runners are in-process tasks.

Startup resume path:

```text
list_all_running()
→ manager.start(run) per row
→ one asyncio task per run
→ concurrent build/warmup
→ capture factor baseline
→ live polling
```

Normal latest-bar polling does:

```text
fresh=True
→ POST /backfill/bars best effort
→ GET /bars limit=5
```

The loop sleeps `poll_s` with no per-run jitter, so tasks with similar intervals that start together can remain approximately aligned.

This sharpened H6:

```text
aligned runner polls may concentrate otherwise-valid fresh work into a burst
```

Factor baseline shape was also corrected:

- lineage factors → only declared factor ids;
- no lineage → snapshot default universe;
- only relevant daily/weekly environment baselines can generate the full cold macro shape.

Periodic FactorPatrol itself is more sequential and should not be treated as the same burst.

Documented in:

```text
29-runner-resume-factor-burst-shape.md
```

---

## 2026-09-16 — runner aligned/staggered harness

Prepared:

```text
38-runner-poll-harness.md
tools/issue107_runner_poll_probe.py
```

The probe models current `_fetch_latest_bar` freshness/network behavior without promoted strategies or orders.

Controlled variable:

```text
--stagger-ms 0
vs
--stagger-ms 100
```

It measures per-run latency/errors plus peak:

```text
provider active
per-venue provider active
backfill HTTP in-flight
bars HTTP in-flight
DB requests waiting
DB pool available
thread work
```

Fidelity guard added:

```text
ISSUE107_FAKE_BARS_PER_FETCH must be >= 10; recommended 1000
```

This prevents a one-bar fake from inventing artificial multi-batch provider pressure for a 5-bar live window.

---

## 2026-09-16 — full-stack factor macro harness

Prepared:

```text
36-safe-full-stack-macro-harness.md
tools/issue107_factor_macro_probe.py
```

It runs real:

```text
factor HTTP
→ FactorEngine
→ factor DataClient
→ localhost data-service
→ real DB pool
→ fake Binance/FRED
```

Recommended exact-count topology:

```text
data workers = 1
factor workers = 1
fake binance + fred
fake bars/fetch = 1000
```

Compare:

```text
cold single caller
cold same-symbol concurrent callers
cold unique-symbol concurrent callers
immediate warm wave
```

This lets us separate legitimate 18-series fan-out from H8/H11 duplication.

---

## 2026-09-16 — issue-level mixed workload harness

Prepared:

```text
39-mixed-workload-harness.md
tools/issue107_mixed_workload_probe.py
```

It combines:

```text
cold factor/macro /score burst
+ runner-like fresh polling across crypto/A-share/JP
+ /health DB-backed probes
+ /openapi.json DB-free controls
```

Requires all used market venues to be fake and `ISSUE107_FAKE_BARS_PER_FETCH>=1000`.

Primary experiments:

```text
M1  cold factor same symbol + aligned runner
M2  cold factor unique price keys + aligned runner
M3  cold factor same symbol + 100ms runner stagger
```

M2 helps isolate H11 from H8. M3 helps isolate H6.

This becomes the main issue-level before/after workload once isolated mechanisms are understood.

---

## 2026-09-16 — evidence documents aligned to runtime plan

Updated:

```text
04-baseline-results.md
07-before-after-results.md
10-active-investigation.md
11-local-test-runbook.md
README.md
```

Baseline matrix now records:

- H1/H1b;
- H6/H8/H9/H10/H11;
- direct Psycopg pool availability/wait/queue/error metrics;
- factor same-vs-unique cold behavior;
- runner aligned-vs-staggered behavior;
- mixed M1/M2/M3;
- provider pressure alongside DB pressure.

Before/after matrix explicitly handles the important Candidate A possibility:

```text
DB pressure improves
but provider pressure increases
```

That is treated as a moved-bottleneck question, not hidden.

---

## Current exact runtime sequence

Use `11-local-test-runbook.md`:

```text
A. existing data/factor tests
B. pure H8/H11 factor diagnostics
C. controlled pool=2 H1 diagnostic
D. real-Uvicorn slow-provider pressure — 1 worker
E. pg_stat_activity during blocked provider wait
F. H9 timeout/cancellation behavior
G. same low-level workload — 2 data workers
H. factor macro cold single
I. factor macro cold concurrent same keys
J. factor macro cold concurrent unique price keys
K. warm factor control
L. runner aligned
M. runner stagger control
N. mixed M1/M2/M3
O. select one first production intervention
```

---

## Current status / next action

Completed without production changes:

- [x] documentation/architecture review
- [x] current #107 path map
- [x] DB lifetime and timeout-chain review
- [x] caller backpressure matrix
- [x] provider concurrency matrix
- [x] Candidate A design/deep review/unapplied patch draft
- [x] H1 deterministic diagnostic
- [x] H8/H11 pure diagnostics
- [x] H9/H10 fake-provider runtime tooling
- [x] full-stack factor macro harness
- [x] runner aligned/stagger harness
- [x] mixed issue-level harness
- [x] before/after evidence template
- [x] current upstream main re-checked at reviewed SHA
- [x] contribution branch confirmed identical to main

Still requiring a real contributor runtime:

- [ ] establish local checkout/dependencies
- [ ] start Postgres/Timescale and run migrations
- [ ] run pre-change data/factor tests
- [ ] execute H8/H11/H1 diagnostics
- [ ] execute real-Uvicorn baseline
- [ ] capture DB/provider/pool evidence
- [ ] execute factor, runner and mixed workloads
- [ ] fill baseline conclusion
- [ ] select Candidate A/B/C/D or continue investigation
- [ ] only then commit production code

At this point, adding more speculative production designs has diminishing value. The next meaningful engineering evidence is runtime data.

---

## Debugging rules

1. Change one meaningful variable at a time where possible.
2. Preserve the failing reproduction before fixing it.
3. Record exact commit SHA and worker topology for every benchmark.
4. Never stress real market-data providers for the load harness.
5. Do not interpret external-provider failure as application saturation without evidence.
6. Do not treat lower error rate as success if freshness/correctness weakened.
7. Do not treat HTTP 200 as refresh success unless expected row/timestamp progress occurred.
8. Rerun the exact same workload after the selected fix.
9. Record negative evidence and rejected hypotheses, not only the theory that eventually wins.
10. Keep contributor harnesses and notes out of the upstream production PR unless explicitly requested.
