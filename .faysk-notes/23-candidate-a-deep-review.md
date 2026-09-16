# Issue #107 — Candidate A Deep Review

**Status:** design review only. Candidate A is still not selected until runtime baseline confirms H1.

This pass checks whether narrowing `/backfill/bars` DB leases would accidentally change transaction, validation, or failure semantics in ways our first design note glossed over.

---

## 1. Current route is not one atomic transaction

It is easy to look at request-scoped `DBConn` and assume the entire backfill is one transaction. It is not.

`insert_bars()` explicitly calls:

```python
await conn.commit()
```

for every persisted batch.

Therefore current multi-batch behavior is already:

```text
latest_bar_ts SELECT
→ provider batch 1
→ UPSERT batch 1
→ COMMIT
→ provider batch 2
→ UPSERT batch 2
→ COMMIT
→ ...
```

A failure after batch 1 does not roll back batch 1 today.

Candidate A therefore does **not** split an existing request-wide atomic transaction. The durable unit is already each inserted batch.

---

## 2. Transaction lifetime and pool-lease lifetime are related but not identical

Psycopg defaults to `autocommit=False`, so `latest_bar_ts()` starts a transaction with its SELECT.

Current first phase:

```text
checkout connection
→ SELECT max(ts)       # transaction starts
→ await provider       # transaction + pool lease both remain open
```

After `insert_bars()` commits a batch, a later provider wait may no longer have an active DB transaction, but the **connection is still checked out** because route-scoped `DBConn` remains alive until the request exits.

So the primary capacity problem is broader than "idle in transaction":

```text
pool slot retained during external I/O
```

Candidate A should be described primarily as **DB lease narrowing / capacity isolation**, not as a transaction tuning patch.

---

## 3. Verified psycopg pool context semantics

The project uses `AsyncConnectionPool.connection()` through shared `get_conn()`.

Psycopg 3 pool documentation states that on normal `connection()` context exit, an open transaction is committed; on exceptional exit it is rolled back; then the connection is returned to the pool.

For Candidate A's read-only timestamp phase:

```text
async with get_conn() as conn:
    cached_latest = await latest_bar_ts(...)
# normal exit → read-only transaction finalized → connection returned
```

This is exactly the ordering we want before provider I/O.

Reference used during review:

```text
https://www.psycopg.org/psycopg3/docs/advanced/pool.html
https://www.psycopg.org/psycopg3/docs/api/pool.html
```

The repository currently requires `psycopg[binary,pool]>=3.3.0`.

---

## 4. Success-path HTTP contract remains the same

Candidate A does not intentionally alter successful response shape:

```text
venue
symbol
timeframe
bars_fetched
bars_inserted
from_ts
to_ts
```

It also leaves provider routing, timeframe validation, incremental cursor rules, UPSERT behavior and freshness untouched.

However, saying "HTTP contract is completely unchanged" is slightly too broad because dependency timing changes under failure/saturation conditions.

---

## 5. Error precedence changes under DB failure/saturation

Current route-level `DBConn` is a FastAPI dependency, so DB checkout occurs before handler business validation executes.

Conceptually today:

```text
request
→ auth/dependency resolution including DB checkout
→ handler validates venue/timeframe/span
```

With Candidate A:

```text
request
→ auth
→ handler validates venue/timeframe/span
→ short DB checkout only when incremental lookup is actually needed
```

Therefore an invalid request received while the DB pool is unavailable could behave differently:

### Current

```text
unsupported venue + DB pool unavailable
→ may wait/fail on DB dependency before venue validation
```

### Candidate A

```text
unsupported venue + DB pool unavailable
→ validation can return explicit 4xx without consuming DB capacity
```

That is arguably better resource ordering, but it is still an observable failure-precedence change and should not be hidden in review notes.

For valid requests with a healthy DB, the intended contract remains unchanged.

---

## 6. Provider failure behavior

Current provider exception path:

```text
connector.fetch_bars raises
→ BarsUpstreamUnavailableError 502
→ request-scoped DB dependency exits exceptionally
```

Candidate A:

```text
latest timestamp DB context already ended normally
→ connector.fetch_bars raises
→ BarsUpstreamUnavailableError 502
```

No bar write has occurred for that provider batch in either case.

The only transaction difference is that Candidate A finalizes the earlier read-only timestamp transaction before the provider call instead of rolling it back as part of request exception unwinding. That has no intended data effect.

Existing test `test_backfill_upstream_failure_returns_502` must remain green.

---

## 7. DB write failure behavior

Candidate A fetches provider data first, then tries to acquire a short DB lease for persistence.

If DB checkout/write fails after provider success:

```text
provider work succeeded
→ persistence failed
→ no durable progress for that batch
→ retry starts from latest committed DB timestamp
→ provider work may repeat
```

This remains recoverable because writes are idempotent and cursor state derives from committed DB rows.

It can waste provider work during a DB outage, but keeping a DB connection reserved throughout provider I/O merely to avoid that repeat would recreate the capacity coupling #107 is investigating.

---

## 8. Concurrent same-key requests

Candidate A widens the wall-clock gap between:

```text
read cached_latest
and
write fetched rows
```

Two requests can therefore observe the same starting point and fetch duplicate windows.

But the current implementation already permits overlapping same-key backfills and relies on `ON CONFLICT ... DO UPDATE` for row-level idempotency.

Candidate A may make the overlap easier to see, but it does not introduce a new correctness class.

Provider duplication is a separate capacity question (H4). Do not bundle single-flight unless measured.

---

## 9. Why direct `get_conn()` inside this route is defensible

The normal project style is `DBConn` for request-scoped DB routes.

Here the request lifetime is intentionally **not** the desired DB lifetime.

Using explicit:

```python
async with get_conn() as conn:
```

around each local DB phase communicates the actual resource boundary and uses the existing shared API without modifying `_shared`.

If selected, add a concise `why` comment such as:

```text
Keep provider I/O outside the DB lease; request-scoped DBConn would retain scarce pool capacity while waiting on external services.
```

This protects against a future style-only refactor reintroducing the problem.

---

## 10. Review checklist before applying Candidate A

- [ ] baseline proves blocked provider requests starve DB-backed endpoints;
- [ ] `> pool_size` fake-provider requests reach provider after fix;
- [ ] `/health` or `/bars` stays responsive while provider waits remain blocked;
- [ ] incremental backfill test unchanged;
- [ ] multi-batch behavior unchanged;
- [ ] upstream provider failure remains explicit 502;
- [ ] DB write failure remains explicit/non-fabricated;
- [ ] no `_shared` modification;
- [ ] ruff/mypy/tests pass;
- [ ] same workload rerun with one and two data workers;
- [ ] mixed acceptance workload reaches zero `DATA_SERVICE_UNREACHABLE` or clearly identifies the next bottleneck.
