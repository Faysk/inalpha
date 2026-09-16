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

### Current next actions

- [x] continue static path verification without waiting for maintainer reply
- [x] confirm exact `DBConn` dependency lifetime
- [x] confirm factor HTTP client lifetime
- [x] confirm factor vs orchestration non-2xx semantics
- [ ] establish runnable contributor environment
- [ ] run pre-change `data` and `factor` tests
- [ ] build deterministic slow-provider reproduction
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
