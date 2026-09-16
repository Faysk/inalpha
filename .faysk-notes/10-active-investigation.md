# Issue #107 — Active Investigation

**Status:** static preparation is substantially complete; next gate is runtime evidence on the contributor machine.  
**Rule:** continue non-invasive investigation and baseline preparation; do not change production behavior before reproducible evidence selects the first intervention.

---

## 1. Current position

We are **not waiting for maintainer feedback to perform low-risk diagnosis**, but we are also not pre-committing to a fix.

Current path:

```text
static code-path verification       ✅
controlled diagnostics prepared     ✅
full-stack fake-provider harnesses   ✅
issue-level mixed workload prepared ✅
production contribution branch clean ✅

next:
local environment
→ pre-change tests
→ deterministic reproduction
→ baseline evidence
→ first decision gate
```

`Faysk/inalpha:fix/data-service-saturation` remains identical to `main`; all diagnostics/design work lives only on `notes/issue-107`.

Reviewed upstream baseline remains:

```text
ed01be9056776c107ab76a404c328a4fed19f529
```

If upstream moves before runtime execution, re-review the #107-sensitive paths before trusting old conclusions.

---

## 2. Strongest confirmed static mechanism

### `/backfill/bars` retains DB capacity across external I/O

`DBConn` is backed by:

```text
_db_dep()
→ get_conn()
→ async with _pool.connection()
→ yield connection
```

Because `/backfill/bars` declares route-level `db: DBConn`, the current ordering is effectively:

```text
checkout DB connection
→ latest_bar_ts()
→ await external connector.fetch_bars()
→ insert_bars()
→ possibly repeat external fetch/write loop
→ route returns
→ connection returned to pool
```

This proves the **resource lifetime**. It does not prove that it is the dominant runtime cause of #107.

### The route is already durable per batch

`insert_bars()` commits each persisted batch explicitly.

Therefore Candidate A would not split one request-wide transaction; that atomicity does not exist today.

The first `latest_bar_ts()` SELECT can additionally leave a read transaction open during the first provider wait under normal Psycopg autocommit behavior. After a batch commit, later waits may not be `idle in transaction`, but the pool lease still remains reserved.

Primary wording remains:

```text
pool slot retained across external I/O
```

not merely:

```text
idle in transaction
```

---

## 3. Capacity / timeout chain to reproduce

Shared pool defaults:

```text
min_size = 2
max_size = 10
timeout = 30s
```

Data service uses those defaults.

Both `/bars` and `/health` are DB-backed through `DBConn`.

Factor `GET /bars` also uses an approximately 30-second HTTP timeout and retries `httpx.RequestError` up to three attempts.

Plausible H1/H1b chain:

```text
slow/fanned-out backfills
→ DB leases retained while provider work waits
→ per-worker DB pool becomes unavailable
→ unrelated /bars or /health waits
→ HTTP deadline and DB checkout deadline race around ~30s
→ ReadTimeout and/or server INTERNAL_ERROR
→ factor may retry transport failure
→ DATA_SERVICE_UNREACHABLE after bounded attempts
```

This chain is statically plausible; runtime evidence must determine whether it is the first constraint in the representative workload.

---

## 4. Project precedent now strongly supports Candidate A's shape

The paper live runner already contains an explicit resource-ordering rule for external HTTP:

```text
short DB read
→ release DB
→ external HTTP
→ short DB write
```

Its comments explain the exact concern: concurrent slow external calls must not monopolize scarce DB pool connections.

That is the same engineering principle as Candidate A for `/backfill/bars`:

```text
short latest-bar lookup
→ release DB
→ provider fetch
→ short persistence checkout
```

This is useful project-fit evidence **if H1 is measured**. It does not replace the baseline requirement.

---

## 5. Current traffic multipliers

### H8 — macro-key cold stampede

Macro cache behavior is:

```text
cache get
→ await data work
→ cache put
```

There is no same-key in-flight coalescing.

Current default daily/weekly macro shape is:

```text
26 macro factor specs
→ 18 unique FRED series
```

Several simultaneous cold requests can duplicate those same macro/date keys before the first caller populates cache.

### H11 — whole live-score cold stampede

The outer live score cache follows the same normal cache pattern: lookup, await work, then put.

Identical concurrent live score requests can therefore all miss together and each perform the main price fetch/compute path.

H8 and H11 are separate:

```text
H11 = duplicate entire score-key work
H8  = duplicate macro-key work inside score/snapshot paths
```

Pure unit diagnostics have been prepared for both, but materiality belongs to the service-level harness.

### Factor connection churn

Each request gets a new `FactorEngine`; `_fetch_df()` creates/closes a new `DataClient`, and therefore a new HTTPX client, per fetch.

This is confirmed behavior but remains low-priority H3 until measured.

---

## 6. Live runner contribution is now precisely modeled

Paper is intentionally single-process.

On startup with resume enabled:

```text
list_all_running()
→ manager.start(run) for each row
→ one asyncio task per run
→ concurrent _build_session()
→ fresh warmup bars
→ capture_factor_baseline()
→ first live poll
```

Normal `_fetch_latest_bar()` does:

```text
fresh=True
→ POST /backfill/bars (best effort)
→ GET /bars limit=5
```

After each iteration the loop sleeps `poll_s` with no per-run jitter. Similar-timeframe tasks started close together can therefore remain approximately phase-aligned.

This is H6. We will measure it rather than immediately adding jitter.

Factor baseline fan-out is conditional:

```text
candidate has factor lineage
→ score only lineage ids

no lineage
→ snapshot default factor universe
→ daily/weekly + cold macro can reach full 18-series FRED shape
```

Periodic `FactorPatrol` itself is less bursty because missing baselines and grouped score work are performed sequentially inside the patrol task.

---

## 7. Provider behavior that can amplify or move the bottleneck

### yfinance

Process-local serialized history fetches behind `_FETCH_LOCK`, minimum interval, timeout, and dedicated bounded executor.

Current ordering can therefore look like:

```text
request A owns DB + provider lock
request B owns DB + waits provider lock
request C owns DB + waits provider lock
```

### baostock / Tencent

Also has provider serialization/throttling and thread-backed work. Cancellation semantics differ from pure async waits because the underlying synchronous thread may survive cancellation.

### FRED

Uses thread-backed provider work and currently has no data-service admission gate, which makes live macro fan-out a useful controlled workload.

### Important moved-bottleneck rule

If Candidate A releases DB capacity successfully, more requests may reach provider work concurrently.

That is why all before/after harnesses record both:

```text
DB pool pressure
AND
provider in-flight/error pressure
```

A lower DB wait accompanied by a new provider failure cliff is not a complete success.

---

## 8. Caller/backpressure compatibility constraint

A future busy response cannot be designed only at `/backfill/bars`.

Current semantics differ:

- **factor:** best-effort POST does not inspect non-2xx status, then continues to `GET /bars`;
- **paper:** explicit backfill parses non-2xx into `DataServiceError`, but `get_bars(fresh=True)` catches refresh failure and still reads bars;
- **research/dashboard:** intentional best-effort/cache degradation in relevant paths;
- **orchestration:** non-2xx becomes explicit HTTP client error.

Therefore Candidate C (admission/backpressure) remains secondary until evidence says it is required.

A plain 429/503 could change freshness behavior differently for different callers.

---

## 9. Adjacent findings kept out of PR1 by default

`GET /ticker?fresh=true` still declares route-level `DBConn` even though its fresh branch only awaits external ticker I/O.

Constituent snapshot paths can also overlap DB leases and external work.

These are valid adjacent resource-ordering findings, but not automatic #107 scope.

Do not broaden the first contribution just because the same smell exists elsewhere.

---

## 10. Deterministic diagnostics now prepared

### H1 — controlled DB pool mechanism

```text
.faysk-notes/tools/test_backfill_pool_pressure_draft.py
```

Own test pool:

```text
max_size = 2
```

Control:

```text
1 blocked backfill
→ one slot remains
→ /health succeeds
```

Pressure:

```text
2 blocked backfills
→ both slots retained
→ /openapi.json remains responsive
→ /health remains blocked until provider release
```

This intentionally replaces the earlier 9-vs-10 draft idea; the pool=2 boundary is deterministic and independent of normal pool tuning.

### Candidate A regression draft

```text
pool max_size = 2
4 blocked provider waits
```

Post-fix property:

```text
all 4 reach provider I/O
while
/health can still acquire DB capacity
```

### H8 / H11 pure factor diagnostics

```text
test_macro_cache_stampede_draft.py
test_factor_live_cache_stampede_draft.py
```

No data service, provider or DB required.

### H9 / H10 real-TCP fake-provider diagnostics

```text
issue107_slow_data_app.py
issue107_timeout_persistence_probe.py
```

Async and thread-backed fake modes distinguish cooperative cancellation from underlying synchronous work that can outlive the async waiter.

---

## 11. Full-stack harnesses prepared

### Factor macro harness

```text
36-safe-full-stack-macro-harness.md
issue107_factor_macro_probe.py
```

Real factor→data localhost HTTP, real data DB path, fake Binance/FRED.

Compare:

```text
cold single
cold concurrent same symbol
cold concurrent unique price keys
warm same keys
```

### Runner polling harness

```text
38-runner-poll-harness.md
issue107_runner_poll_probe.py
```

Real data HTTP/DB path, fake crypto/A-share/JP providers.

Compare exact same work with:

```text
stagger=0 ms
stagger=100 ms
```

The probe samples provider, HTTP in-flight and Psycopg pool state while the wave is active.

### Mixed issue-level harness

```text
39-mixed-workload-harness.md
issue107_mixed_workload_probe.py
```

Combines:

```text
cold live factor/macro burst
+ runner-like fresh polls
+ DB-backed /health probes
+ DB-free /openapi controls
```

Experiments:

```text
M1  cold factor same-symbol + aligned runner
M2  cold factor unique price keys + aligned runner
M3  cold factor same-symbol + 100ms runner stagger
```

This becomes the main before/after acceptance workload once isolated mechanisms are understood.

---

## 12. Exact runtime sequence

Use `11-local-test-runbook.md` as the executable checklist:

```text
A. existing data/factor tests
B. pure H8/H11 diagnostics
C. controlled pool=2 H1 diagnostic
D. real-Uvicorn slow-provider pressure — 1 data worker
E. pg_stat_activity during blocked provider wait
F. H9 client-timeout/cancellation behavior
G. same low-level fake workload — 2 data workers
H. live factor + macro: cold single
I. live factor + macro: cold concurrent same keys
J. live factor + macro: cold concurrent unique price keys
K. immediate warm factor control
L. runner-like aligned polls
M. runner-like stagger control
N. mixed M1/M2/M3 baseline
O. select one first production intervention
```

Do not start with the mixed scenario. The isolated steps tell us *why* it fails.

---

## 13. First decision gate

After baseline evidence:

```text
H1 material
→ Candidate A: narrow DB lease

DB healthy but provider work saturates
→ Candidate C: bounded admission before scarce-resource checkout

H8/H11 materially amplify representative load after primary data behavior is fixed
→ factor-side single-flight and/or bounded fan-out

H3 connection churn material
→ safe process-owned HTTP client with request-scoped auth

H6 still materially changes failures after Candidate A
→ consider runner scheduling/jitter with maintainer alignment

none explains it
→ keep investigating; do not force a planned solution
```

Candidate A remains the least contract-changing first intervention **only if runtime H1 evidence selects it**.

---

## 14. Current boundary

Static preparation can still be refined, but there is now diminishing value in adding more hypothetical machinery before executing the prepared tests.

The next meaningful evidence requires:

```text
local repository checkout
Docker/Postgres/Timescale
service processes
real localhost HTTP
```

Until then:

```text
do not apply candidate_a_narrow_db_lease.patch

do not commit production code

do not invent concurrency defaults

do not weaken freshness
```

The contribution branch stays clean so the eventual diff starts from measured evidence rather than accumulated speculation.
