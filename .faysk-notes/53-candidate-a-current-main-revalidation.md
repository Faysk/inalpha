# Issue #107 — Candidate A Revalidation Against Current `main`

**Status:** static revalidation only; Candidate A remains unapplied until runtime evidence selects it.  
**Reviewed upstream:** `ed01be9056776c107ab76a404c328a4fed19f529`.

---

## 1. Current route behavior

Current `POST /backfill/bars` declares:

```python
async def backfill_bars(req, db: DBConn, _user):
```

and then performs:

```text
latest_bar_ts(db)
→ external connector.fetch_bars(...)
→ insert_bars(db)
→ possibly repeat provider/write batches
→ route returns
```

Because `DBConn` is a FastAPI dependency backed by `get_conn()`, the connection lease spans the entire route invocation, including external provider waits.

That is the exact resource-lifetime property Candidate A would change.

---

## 2. Shared DB API does not need modification

`services/_shared/src/inalpha_shared/db.py` already exposes:

```python
@asynccontextmanager
async def get_conn():
    async with _pool.connection() as conn:
        yield conn
```

and `DBConn` itself is only a thin FastAPI dependency wrapper around the same helper.

Candidate A can therefore use the existing public helper from data-service code:

```python
from inalpha_shared.db import get_conn
```

without changing protected `_shared` infrastructure.

This also matches existing project code such as the live-runner M-1 resource-ordering pattern.

---

## 3. Proposed resource ordering

Candidate A changes only connection lifetime:

```text
current
DB checkout
→ latest_bar_ts
→ provider I/O
→ DB write
→ provider I/O...
→ release DB

candidate
DB checkout
→ latest_bar_ts
→ release DB
→ provider I/O
→ DB checkout
→ insert batch
→ release DB
→ provider I/O...
```

No provider, freshness, cursor, timeframe, auth, response-schema or retry rule is intentionally changed.

---

## 4. Transaction / commit semantics

`insert_bars()` already calls:

```python
await conn.commit()
```

after every inserted batch.

Therefore current backfill does **not** wrap the whole provider loop in one atomic DB transaction. Each successful batch is already committed independently.

Using a new short `get_conn()` lease for each completed batch does not split an existing route-wide transaction that callers currently depend on.

`latest_bar_ts()` is a read-only query. Its short lease can be returned before provider I/O.

---

## 5. Failure semantics

Candidate A should preserve:

```text
connector exception
→ BARS_UPSTREAM_UNAVAILABLE (502)

DB read/write exception
→ existing DB/server failure path

empty first provider batch
→ existing logging/zero-result behavior

cursor stuck
→ existing protective break
```

One internal failure-order difference is expected and acceptable if H1 selects the change:

- today the route-level DB dependency can make a request wait for DB capacity before entering route validation/provider logic;
- after narrowing, auth/route validation can complete before the first explicit DB checkout.

That does not weaken auth or change the documented HTTP request/response schema. It avoids reserving DB capacity for invalid/unauthorized work.

Do not add a new busy/error contract as part of Candidate A itself.

---

## 6. HTTP/API contract

Removing `db: DBConn` from the Python route signature does not remove a user-visible request field because `DBConn` is an internal FastAPI dependency, not body/query data.

The external route remains:

```text
POST /backfill/bars
BackfillRequest → BackfillResponse
```

with the same auth dependency.

Static code search found no repository callers invoking the Python route function directly with a positional `db` argument; service consumers use HTTP/client abstractions.

---

## 7. Existing tests remain structurally compatible

`services/data/tests/conftest.py` and `test_backfill_router.py` start the real data-service lifespan, which initializes the shared pool, then replace provider registry entries with fakes.

Candidate A's explicit `get_conn()` therefore uses the same initialized test pool.

Existing route tests should continue to exercise:

```text
venue routing
timeframe validation
incremental cursor behavior
explicit upstream 502 behavior
canonical market identity
real DB persistence
```

without needing a route-specific DB dependency override.

A new deterministic regression is still needed for the resource-lifetime property itself because the existing tests do not assert DB availability during blocked provider I/O.

---

## 8. Candidate regression hardening

The prepared post-fix regression now:

```text
forces pool max_size=2
forces constituent scheduler index list empty
uses four distinct fake backfills
blocks all four inside provider I/O
requires all four to reach provider before release
probes /openapi.json
probes DB-backed /health
then releases provider and verifies all backfills succeed
```

On the old route-level `DBConn` design, only two requests can reach provider with a two-connection pool, so the `all_entered` condition should fail.

After Candidate A, all four should finish their short read lease and wait at the provider while `/health` can still acquire DB capacity.

This is a property test, not a benchmark.

---

## 9. Known risk remains: accidental provider-capacity release

The current DB pool also acts as an accidental cap on the number of provider operations that can be reached concurrently.

Candidate A removes that coupling.

Therefore success requires both:

```text
DB starvation / DATA_SERVICE_UNREACHABLE improves
AND
provider failures / cancellations / no-progress do not materially worsen
```

If provider pressure becomes the next measured limit, that is evidence for a separate admission-control decision. It is not justification to keep holding DB connections across network waits.

Do not merge Candidate A with Candidate C preemptively.

---

## 10. Same-key overlap remains evidence-gated

Two concurrent requests for the same `(venue, symbol, timeframe)` can already read the same cached latest timestamp and fetch overlapping windows.

`insert_bars()` prevents duplicate rows through `ON CONFLICT`, but an unconditional update does not prove newest-observation-wins if overlapping mutable-candle fetches complete out of order.

Candidate A may increase how often same-key requests reach provider concurrently.

Therefore:

```text
if H4 shows same-key overlap is material after Candidate A
→ run deterministic completion-inversion correctness test
→ then decide whether coalescing/single-flight is required

if H4 is not material
→ keep PR1 small
```

---

## 11. Static conclusion

Against current `main`, Candidate A remains a technically coherent **minimal candidate** for H1:

```text
uses existing get_conn()
no _shared modification
no API-schema change
no freshness downgrade
no retry addition
no admission policy addition
preserves per-batch commit behavior
has a deterministic regression shape
```

But static coherence is not selection evidence.

Candidate A remains blocked on the runtime decision gate:

```text
H1 reproduced + material to representative #107 workload
→ select Candidate A

otherwise
→ do not apply it merely because the code change looks clean
```
