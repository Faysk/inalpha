# Issue #107 — Candidate Fix A: Narrow the DB Lease Around Backfill

**Status:** candidate only — do not implement in `fix/data-service-saturation` until runtime evidence supports H1.  
**Scope if selected:** preferably `services/data` only.

---

## 1. Problem this candidate addresses

Current `/backfill/bars` accepts route-level `db: DBConn`.

That means one DB connection is checked out before the handler body and remains reserved while the route performs external provider I/O.

Current shape:

```text
DB checkout
→ latest_bar_ts
→ slow external fetch
→ insert
→ slow external fetch
→ insert
→ response
→ DB release
```

Candidate A changes only resource lifetime:

```text
validate / route provider
→ short DB checkout: latest_bar_ts
→ release DB
→ external fetch
→ short DB checkout: insert batch
→ release DB
→ external fetch
→ short DB checkout: insert batch
→ release DB
→ response
```

The business behavior and HTTP contract should remain unchanged.

---

## 2. Why this is attractive as a first candidate

If H1 is confirmed, this solution has several desirable properties:

- no new public error code;
- no new queue semantics;
- no guessed concurrency default;
- no factor/paper/research caller contract change;
- no `_shared` infrastructure change;
- no live-runner change;
- no provider-specific policy;
- no new dependency;
- preserves incremental backfill;
- preserves UPSERT/idempotency;
- lets ordinary read endpoints use DB capacity while external providers are slow.

It attacks a specific coupling rather than imposing a global concurrency policy.

---

## 3. Candidate code shape

This is illustrative, not a ready commit.

### Import

Current:

```python
from inalpha_shared.db import DBConn
```

Candidate:

```python
from inalpha_shared.db import get_conn
```

### Route signature

Current:

```python
async def backfill_bars(
    req: BackfillRequest,
    db: DBConn,
    _user: Annotated[User, Depends(get_current_user)],
) -> BackfillResponse:
```

Candidate:

```python
async def backfill_bars(
    req: BackfillRequest,
    _user: Annotated[User, Depends(get_current_user)],
) -> BackfillResponse:
```

### Incremental cursor lookup

Current:

```python
cached_latest = await latest_bar_ts(
    db, effective_venue, effective_symbol, req.timeframe, upto=req.to_ts
)
```

Candidate:

```python
async with get_conn() as conn:
    cached_latest = await latest_bar_ts(
        conn,
        effective_venue,
        effective_symbol,
        req.timeframe,
        upto=req.to_ts,
    )
```

The connection is then returned before `connector.fetch_bars()`.

### Persistence

Current:

```python
bars = await connector.fetch_bars(...)
n = await insert_bars(db, effective_venue, effective_symbol, req.timeframe, bars)
```

Candidate:

```python
bars = await connector.fetch_bars(...)

async with get_conn() as conn:
    n = await insert_bars(
        conn,
        effective_venue,
        effective_symbol,
        req.timeframe,
        bars,
    )
```

Since `insert_bars()` already commits the batch, the current persisted-batch boundary is retained.

---

## 4. Correctness review

### Incremental semantics

Preserved:

```text
latest persisted timestamp
→ resume from cached max
→ re-fetch last candle
→ advance cursor to to_ts
```

### Persistence semantics

Preserved:

```text
ON CONFLICT ... DO UPDATE
```

Backfill remains idempotent at the DB row level.

### Freshness

Preserved.

This candidate does not change:

- `fresh=True` caller behavior;
- requested `to_ts`;
- provider fetch windows;
- cache fallback policy;
- response fields.

### Authentication

Preserved.

The route still depends on `get_current_user`; removing `DBConn` does not remove auth.

### Service boundaries

Preserved.

`services/data` continues to use the public shared `get_conn()` helper; no service imports another service.

---

## 5. Concurrency/race review

Splitting the DB lease creates a time gap between:

```text
read cached_latest
and
persist fetched bars
```

Could another concurrent request advance the same series during that gap? Yes.

But concurrent requests can already overlap at the provider call today; the route has no per-key lock.

Resulting duplicate writes remain safe because persistence is UPSERT/idempotent.

Potential cost:

```text
request A and request B both observe same cached_latest
→ both fetch same external window
→ duplicate provider work
```

That is existing/adjacent capacity debt. Candidate A does not solve it.

Do not add single-flight in the same PR unless the runtime baseline shows duplicate same-key provider work is material to #107.

---

## 6. Transaction review

Current first phase:

```text
latest_bar_ts SELECT
→ transaction starts under psycopg default autocommit=False
→ external provider await while same connection/transaction remains scoped to route
```

Candidate A exits the connection context immediately after `latest_bar_ts`, so the pool context closes the transaction before external I/O.

This removes the first provider wait from the DB transaction lifetime as well as the pool lease lifetime.

Do not sell this PR as a transaction/VACUUM optimization unless runtime/DB evidence demonstrates that impact; the primary intended effect is capacity isolation.

---

## 7. Cost/trade-offs

### More pool checkouts per request

Current:

```text
1 connection checkout for whole route
```

Candidate:

```text
1 short checkout for latest timestamp
+ 1 short checkout per persisted batch
```

This increases checkout count but decreases checkout duration dramatically when provider I/O dominates.

The baseline should compare:

- pool wait;
- route p50/p95;
- `/bars` latency during blocked provider calls;
- throughput;
- DB connection count;
- number of external provider calls.

### Potential interleaving

Another backfill can write between batches.

Because rows are keyed and UPSERTed, this should remain logically safe, but tests must cover cursor progress and idempotency.

### Failure between provider fetch and DB checkout

If provider fetch succeeds but a DB connection cannot be acquired for persistence, the request fails without writing that batch.

On retry, incremental state remains at the last committed timestamp and the provider window is fetched again.

That is recoverable/idempotent, though potentially wasteful under DB outage.

---

## 8. Deterministic before/after regression

The contributor test already prepared gives a clean prediction.

### Before Candidate A

With default max pool size 10:

```text
10 concurrent fake provider calls blocked
→ each request already owns DBConn
→ /health cannot obtain DB connection
→ /health blocks
```

### After Candidate A

Expected:

```text
10 concurrent fake provider calls blocked
→ DB leases already released after latest_bar_ts
→ /health obtains a DB connection
→ /health returns while provider calls remain blocked
```

This is a particularly strong regression because:

- no external network is involved;
- no timing from Yahoo/FRED is required;
- the variable being tested is resource lifetime;
- the same test can be run before and after.

---

## 9. Tests if this candidate is selected

Likely upstream test additions:

- [ ] slow/blocking fake connector does not monopolize the DB pool after timestamp lookup;
- [ ] `/health` or another DB-only request remains serviceable while provider I/O is blocked;
- [ ] existing incremental second-call test remains green;
- [ ] upstream provider failure remains `502 BARS_UPSTREAM_UNAVAILABLE`;
- [ ] DB write failure still fails explicitly;
- [ ] connection is released on provider exception;
- [ ] connection is released on insert exception;
- [ ] multi-batch backfill still advances correctly;
- [ ] existing 5-venue routing tests remain green.

The exact regression should avoid relying on private shared-pool internals if endpoint-level behavior can prove the property.

---

## 10. What Candidate A does NOT solve

It does not inherently limit:

- total external provider concurrency;
- factor macro fan-out;
- yfinance queue length;
- FRED request burst rate;
- HTTP connection churn;
- duplicate same-key provider work;
- synchronized live-runner polls;
- CPU/event-loop saturation unrelated to DB capacity.

Therefore after Candidate A we must rerun the **same representative mixed benchmark**.

If DB starvation disappears but the service still saturates elsewhere, that evidence determines whether a second control is required.

---

## 11. Escalation path after Candidate A

Only if evidence requires it:

```text
A. narrow DB lease
↓
rerun benchmark
↓
provider work still overwhelms service?
    yes → evaluate admission gate before provider work
    no  → stop; do not add extra machinery
```

If an admission gate becomes necessary after A, it can then be placed without queued requests already owning DB connections.

---

## Selection gate

Choose Candidate A for implementation only if runtime evidence shows:

1. slow/in-flight backfills materially consume pool capacity;
2. unrelated DB-backed requests wait as a result;
3. releasing provider I/O from the DB lease improves that condition in the deterministic experiment;
4. no correctness regression appears in incremental/idempotency tests.

Until those conditions are measured, this remains a prepared candidate, not the selected solution.
