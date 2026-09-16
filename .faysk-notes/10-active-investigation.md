# Issue #107 — Active Investigation

**Status:** active while maintainer feedback is pending.  
**Rule:** continue non-invasive investigation and baseline preparation; do not change production behavior before reproducible evidence exists.

---

## 1. Decision

We are **not blocking engineering work on the maintainer reply**.

The maintainer's response can still change scope or priorities, but useful low-risk work continues now:

```text
static code-path verification
→ local environment preparation
→ pre-change tests
→ deterministic reproduction
→ baseline evidence
```

Production behavior remains unchanged until the failure is reproduced and the first constrained resource is identified.

---

## 2. Static findings now confirmed from code

### DB connection lifetime

`DBConn` is implemented as a FastAPI dependency backed by:

```text
_db_dep()
→ get_conn()
→ async with _pool.connection()
→ yield connection
```

Because `/backfill/bars` accepts `db: DBConn`, that checked-out connection remains scoped to the route invocation unless the route is restructured.

Current backfill flow is therefore effectively:

```text
checkout DB connection
→ latest_bar_ts()
→ external connector.fetch_bars()
→ insert_bars()
→ possibly repeat provider fetch/write loop
→ route returns
→ DB connection released
```

This confirms the **lifetime behavior**. It does **not** yet prove that DB-pool pressure is the root cause of #107.

### Factor client lifetime

`get_engine()` creates a new `FactorEngine` for each factor request.

`FactorEngine._fetch_df()` then does:

```text
async with DataClient(...) as dc
→ DataClient creates httpx.AsyncClient
→ get_bars()
→ client closes
```

Macro factor fan-out calls `_fetch_df()` concurrently for multiple required FRED series.

Therefore short-lived factor→data HTTP clients are real current behavior and remain a measurable connection-churn hypothesis.

### Factor fresh-backfill status behavior

Factor's `_best_effort_backfill()` awaits:

```text
POST /backfill/bars
```

but does not call `raise_for_status()` or otherwise inspect the returned HTTP status.

So a future HTTP `429` / `503` from `/backfill/bars` would not automatically enter the exception path in this helper. The code would continue to `GET /bars` afterward.

This is an important compatibility constraint for any admission-control design.

### Other caller behavior

Current caller behavior differs by component:

- **paper**: explicit `backfill_bars()` converts non-2xx responses into `DataServiceError`; `get_bars(fresh=True)` catches refresh failure and then continues to read bars.
- **research**: best-effort backfill intentionally degrades to DB-cached data.
- **dashboard**: stale/empty chart refresh is best-effort and already has process-local same-key coalescing.
- **orchestration**: shared TypeScript `HttpClient` throws `HttpClientError` on any non-2xx and preserves upstream error code/status/details.

Therefore a new busy/backpressure response cannot be evaluated only at the data-service route. Caller semantics are part of correctness.

---

## 3. What is confirmed vs still hypothetical

### Confirmed

- route-scoped `DBConn` holds a pool connection across the current `/backfill/bars` handler lifetime;
- pool default is 10 connections per process;
- production compose currently configures two data workers;
- yfinance serializes `history()` calls per process;
- factor creates short-lived `httpx.AsyncClient` instances through `_fetch_df()`;
- live macro factor fetches can fan out concurrently;
- dashboard already coalesces same-key chart backfills;
- factor/research best-effort backfill semantics differ from orchestration's explicit HTTP-error semantics.

### Still hypotheses

- DB-pool exhaustion is the first resource that causes #107;
- shortening DB lifetime alone fixes the representative workload;
- a backfill admission gate is necessary;
- connection pooling in factor materially affects p95/error rate;
- cross-service duplicate backfills are frequent enough to justify data-side single-flight;
- live-runner synchronization is still a significant contributor after current mitigations.

Do not write PR language that treats any item in the second list as proven until runtime evidence exists.

---

## 4. Immediate runtime sequence

Once the contributor machine has the repository locally:

```text
1. verify exact upstream commit
2. start unmodified stack
3. run existing data/factor tests
4. establish one-worker diagnostic run
5. reproduce slow-provider/backfill pressure with fake/delayed connector
6. inspect DB-pool behavior and request latency
7. repeat with production-like data WORKERS=2
8. exercise live factor + macro fan-out
9. add runner-like traffic only after isolated scenarios are understood
10. record baseline before any production change
```

---

## 5. First decision gate

After the initial deterministic reproduction, choose **one** first intervention based on evidence:

```text
DB connection retained across slow I/O is material
→ investigate shortening DB checkout lifetime

expensive provider work itself saturates first
→ investigate bounded admission before scarce-resource checkout

caller connection churn is material
→ investigate safe HTTP connection reuse

none of the above explains failure
→ keep investigating; do not force the planned solution
```

---

## 6. Current stance

We continue working while feedback is pending, but we separate:

```text
work that improves understanding / reproduction
from
work that changes upstream production behavior
```

The first category proceeds now. The second requires evidence and still remains subject to maintainer feedback before the PR is finalized.
