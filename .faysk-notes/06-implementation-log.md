# Issue #107 — Implementation Log

Chronological working log. Keep this factual: what changed, what was observed, what failed, and why a decision was made.

---

## 2026-09-16

### Setup / initial review

- Created contributor fork `Faysk/inalpha`.
- Contribution branch: `fix/data-service-saturation`.
- Notes branch: `notes/issue-107`.
- Reviewed project documentation, architecture rules, CI, PR templates, security policy, service READMEs, current-state docs, factor/data behavior, and existing concurrency patterns.
- Confirmed #107 remains open.
- Confirmed current `main` already contains partial mitigation compared with the original issue wording:
  - panel fetch concurrency bounded at 16,
  - panel avoids forced per-symbol fresh backfills,
  - incremental `/backfill/bars`,
  - bounded factor GET retry/backoff.
- Identified freshness/caller-semantics risk if a future admission gate returns a non-2xx response that freshness-sensitive callers do not interpret correctly.
- Decision: no production code changes before reproducible baseline.

### Full plan alignment review

Re-read the entire working plan against current upstream code and contribution rules.

New findings that materially refine the plan:

1. **Current live macro fan-out still matters.**
   - `_compute_macro()` uses concurrent `asyncio.gather` across required FRED series.
   - A 1d macro snapshot can involve roughly 18 series.
   - Therefore live factor/macro traffic is a more important current reproduction target than panel-only traffic.

2. **`/backfill/bars` holds `DBConn` across external I/O.**
   - FastAPI resolves route-level `db: DBConn` before the handler body.
   - The route does `latest_bar_ts`, waits for provider fetches, then writes bars while retaining that checked-out connection.
   - Shared pool default is max 10 connections per process.
   - This is now hypothesis H1 and must be measured before adding a semaphore.

3. **Gate placement matters.**
   - A semaphore inside the existing handler body may be too late because queued requests can already hold DB connections.
   - Any admission design must be reviewed together with DB connection lifetime.

4. **Production data-service is multi-worker.**
   - repository production compose currently sets `data WORKERS=2`.
   - Any normal `asyncio.Semaphore`, lock or cache is process-local and duplicated per worker.
   - We must not describe a process-local gate as service-global.

5. **yfinance already serializes history fetches per process.**
   - `_FETCH_LOCK` protects Yahoo from concurrent request bursts.
   - Concurrent yfinance backfills can therefore queue at the provider layer; if they already own DB connections, this may amplify pool pressure.

6. **Dashboard already has same-key backfill coalescing.**
   - Generic data-side single-flight should only be added if duplicate work from other/cross-service callers is measured.

7. **Backfill callers have different degradation contracts.**
   - factor, paper, research, dashboard and orchestration do not all treat refresh failure identically.
   - Any new 429/503/busy response requires a caller compatibility matrix.

8. **HTTP 200 is not sufficient evidence of a successful yfinance refresh.**
   - yfinance can currently turn some provider failures into empty results; this is separately tracked by #74.
   - Benchmarks must record actual row/timestamp progress, not only status code.

9. **Benchmark harness should remain contributor tooling by default.**
   - Upstream PR should commit focused deterministic regression tests and the smallest production fix.
   - A load harness is only upstream material if it is generally useful and the maintainer wants it.

10. **Acceptance wording tightened to match #107.**
    - target representative mixed workload: zero `DATA_SERVICE_UNREACHABLE` after the fix;
    - p95 must be controlled/bounded;
    - intentional overload/backpressure is counted separately from transport failure.

Updated:

- `01-issue-107-plan.md`
- `02-request-flow-map.md`
- `03-reproduction-plan.md`
- `04-baseline-results.md`
- `05-solution-design.md`

### Active investigation — do not wait for maintainer reply

Decision: maintainer feedback is **not a blocker** for non-invasive investigation, environment preparation, tests, or baseline work. We continue now, while keeping production behavior unchanged until evidence exists.

Static verification completed in this pass:

- Confirmed `DBConn` is implemented by `_db_dep()` wrapping `get_conn()`, which holds `_pool.connection()` across the dependency scope. This confirms that the current `/backfill/bars` route retains a checked-out DB connection across provider I/O.
- Confirmed `get_engine()` creates a new `FactorEngine` per request.
- Confirmed `FactorEngine._fetch_df()` creates a new `DataClient`, and therefore a new `httpx.AsyncClient`, per fetch.
- Confirmed macro fan-out can therefore create multiple short-lived HTTP clients concurrently.
- Confirmed factor `_best_effort_backfill()` does not inspect non-2xx backfill responses; a future `429`/`503` would not automatically enter its exception path.
- Confirmed orchestration's shared TypeScript `HttpClient` does the opposite: every non-2xx becomes `HttpClientError` with upstream code/status/details preserved.
- Paper/research/dashboard remain intentionally different degradation paths, so backpressure correctness must be reviewed per caller.

Important wording discipline:

```text
confirmed lifetime behavior ≠ measured root cause
```

The DB-lifetime mechanism is now statically proven. Its contribution to #107 still requires runtime reproduction.

Created:

- `10-active-investigation.md`

### Static deepening — pool starvation chain and deterministic diagnostic

Continued code-path review while the contributor machine is offline.

Additional confirmed facts:

- `data-service` calls `init_pool()` without overriding the shared defaults: `max_size=10`, checkout timeout 30s per worker.
- `GET /health` itself requires `DBConn` before it can run `SELECT 1`.
- production compose runs `data` with `WORKERS=2` and probes `/health` with a short Docker healthcheck timeout.
- factor `DataClient` uses a 30-second HTTP timeout for `GET /bars`; its GET path retries `httpx.RequestError` up to 3 times.
- therefore pool wait and caller timeout are aligned closely enough to form a plausible retry-amplification path to `DATA_SERVICE_UNREACHABLE`.
- yfinance's per-process `_FETCH_LOCK` can queue requests behind provider serialization while those requests still own route-scoped DB connections.
- FRED uses `asyncio.to_thread` and has no connector-side admission gate, making current macro fan-out a useful second workload after the synthetic test.

Refined hypotheses:

```text
H1  backfill retains scarce DB capacity across slow provider I/O
H1b DB-pool wait reaches factor's HTTP timeout, turning capacity pressure into
    RequestError/retries and eventually DATA_SERVICE_UNREACHABLE
```

Neither is yet called a measured root cause.

Prepared a deterministic contributor-only diagnostic:

```text
.faysk-notes/tools/test_backfill_pool_pressure_draft.py
```

It uses a fake blocking connector and no external network. The control/pressure comparison is:

```text
9 blocked backfills  -> one pool slot remains -> /health should complete
10 blocked backfills -> all default pool slots occupied -> /health should block
```

This is intended to be copied temporarily into `services/data/tests/` and run against the unmodified baseline. It is not upstream PR material as-is.

### Static capacity model / caller contract review

Continued without touching the contribution branch.

New static conclusions:

1. **Cold live macro traffic is numerically close to the DB ceiling.**
   - A live macro cache miss can fan out to roughly 18 FRED series.
   - Production data has 2 workers × max 10 DB connections per worker.
   - With perfect balancing, 18 fresh series is roughly 9 requests per worker, leaving only ~1 DB slot per worker while provider I/O is in flight.
   - This is a capacity model, not proof of real scheduler/accept distribution.

2. **A modest overlap can exceed the per-worker pool even under ideal balance.**
   - Example model: 18 macro + 4 live polls = 22 backfill-shaped requests, ~11/worker if perfectly balanced.
   - Uneven worker distribution can saturate one worker earlier.

3. **Macro is bursty in current `main`.**
   - live macro cache TTL is one hour, so the 18-series path is strongest on cache miss/restart/expiry rather than continuously by itself.
   - This reinforces the need for mixed-load reproduction instead of treating the original June traffic description as unchanged.

4. **Live runner can still generate synchronized fresh traffic.**
   - each running strategy has its own asyncio task;
   - default per-account maximum is 10 runs;
   - each poll uses `get_bars(fresh=True)` = backfill + read;
   - the main poll loop has no jitter, so same-timeframe runs can align.

5. **`/health` can fail before its local DB-error fallback executes.**
   - `DBConn` dependency resolution happens before the handler's `try` around `SELECT 1`;
   - pool checkout timeout can therefore surface as generic `500 INTERNAL_ERROR` rather than `db="error"`.
   - health remains a useful pool-starvation canary but is not pure liveness.

6. **Psycopg transaction lifetime makes current coupling slightly worse.**
   - default autocommit is false;
   - `latest_bar_ts()` SELECT starts a transaction;
   - the first external provider wait can occur while that transaction and pool lease are still open.
   - this is a verified behavior/property, not yet a measured production impact claim.

7. **Backpressure cannot be designed server-only.**
   - factor ignores a plain non-2xx response from its best-effort POST unless an exception is raised;
   - paper explicitly parses non-2xx but `get_bars(fresh=True)` deliberately degrades to cache;
   - live runner inherits paper semantics;
   - orchestration fails explicitly on non-2xx.
   - choosing 429/503 therefore changes caller behavior differently across components.

Prepared:

- `12-static-capacity-model.md`
- `13-caller-backpressure-matrix.md`
- `14-candidate-fix-a-narrow-db-lease.md`

Candidate A is intentionally **not selected yet**. It is a ready design for the smallest likely fix if the 9-vs-10 diagnostic confirms H1:

```text
short DB checkout for latest_bar_ts
→ release DB
→ external provider I/O
→ short DB checkout for persistence
```

The strongest reason to test it first is compatibility: if it solves the representative workload, we can improve capacity **without adding a new HTTP busy contract, guessed concurrency limit, factor change, live-runner change, or `_shared` change**.

### Current next actions

- [x] continue static path verification without waiting for maintainer reply
- [x] confirm exact `DBConn` dependency lifetime
- [x] confirm factor HTTP client lifetime
- [x] confirm factor vs orchestration non-2xx semantics
- [x] confirm `/health` shares the same DB pool dependency
- [x] map 30s DB-pool checkout vs 30s factor HTTP timeout interaction
- [x] prepare deterministic 9-vs-10 pool-pressure diagnostic
- [x] build current static per-worker capacity model
- [x] map live-runner fresh poll behavior and lack of jitter
- [x] map backpressure semantics across callers
- [x] prepare minimal Candidate A without committing production code
- [ ] establish runnable contributor environment
- [ ] run pre-change `data` and `factor` tests
- [ ] run deterministic slow-provider reproduction
- [ ] capture one-worker baseline
- [ ] capture production-like two-worker baseline
- [ ] test live factor + macro fan-out
- [ ] add runner-like traffic only after isolated paths are understood
- [ ] record baseline before any production code change

Maintainer feedback remains useful for scope/deployment context, but is no longer an idle-work gate.

---

## Log entry template

### YYYY-MM-DD — short title

**Context**

```text
What were we trying to do?
```

**Change / command**

```text
What did we change or run?
```

**Observed result**

```text
What actually happened?
```

**Evidence**

```text
logs / metrics / test output / commit
```

**Conclusion**

```text
What does this prove or rule out?
```

**Next action**

```text
What should happen next?
```

---

## Debugging rules

1. Change one meaningful variable at a time where possible.
2. Preserve failing reproduction before fixing it.
3. Record exact commit SHA and worker topology for benchmark runs.
4. Do not interpret an external provider outage as application saturation without evidence.
5. Do not treat a lower error rate as success if freshness/correctness changed.
6. Do not treat HTTP 200 as a successful refresh unless expected data/timestamp progress occurred.
7. Rerun the same benchmark after the fix; do not compare unrelated scenarios/topologies.
8. Record negative evidence and rejected hypotheses, not only the theory that eventually wins.
