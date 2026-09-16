# Issue #107 — Adjacent data-service DB Lease Audit

**Status:** adjacent findings only. Do not expand PR #107 automatically.

The #107 investigation exposed a general resource-ordering question:

```text
Does a data-service request hold DB capacity while waiting on unrelated external I/O?
```

This note audits nearby paths so we do not fix `/backfill/bars` while accidentally assuming it is the only place with that shape.

---

## 1. `/backfill/bars` — directly relevant

Current route signature includes route-scoped `DBConn` and then performs provider I/O.

```text
DB checkout
→ latest_bar_ts
→ provider fetch
→ insert
→ provider fetch
→ insert
→ route returns
→ DB release
```

This is the primary #107 hypothesis already covered by Candidate A.

---

## 2. `/ticker?fresh=true` — same resource-ordering smell

`services/data/src/inalpha_data/api/ticker.py` currently declares:

```python
async def get_ticker(
    db: DBConn,
    ...
)
```

But the `fresh=true` branch does:

```text
resolve connector
→ await connector.fetch_ticker(...)
→ return live quote
```

and does **not use `db` at all** in that branch.

Because FastAPI resolves `DBConn` before entering the handler, a fresh ticker request can therefore reserve a DB connection during external provider I/O even though the DB is unnecessary for that request path.

This is especially relevant for slow providers such as yfinance, whose live ticker path can wait on synchronous Yahoo work wrapped in an executor.

### Why this is not automatically part of PR #107

The original issue's named saturation chain is factor/backfill + live-runner bar polling. Paper's live runner fetch loop uses `get_bars(fresh=True)`, not `/ticker` for each poll.

However order execution can request a fresh ticker, so this path can overlap with backfill load in a real mixed workload.

Decision:

```text
measure ticker contribution if representative workload reaches it
→ if immaterial, leave it out of PR #107
→ if material and the same minimal DB-lease fix is obvious, discuss whether to include or split
```

Do not silently broaden the first PR just because the same pattern exists.

---

## 3. Constituent snapshot — same shape, low-frequency/background

`POST /constituents/snapshot` receives route-scoped `DBConn` and delegates to `record_snapshot(db, ...)`.

`record_snapshot()` performs:

```text
await baostock.fetch_index_constituents(...)
→ DB transaction/upsert
```

So the DB lease also spans external provider I/O.

The background `ConstituentSnapshotScheduler` similarly opens `get_conn()`, checks today's snapshot, and if missing calls `record_snapshot()` while still inside that same connection context.

This is real resource coupling, but its operational profile differs strongly from #107:

- scheduler is disabled when no tracked indices are configured;
- it runs at a long interval;
- indices are processed sequentially;
- it is not part of the factor/live-runner burst described in #107.

Therefore treat it as **adjacent debt**, not a #107 scope item unless runtime evidence says otherwise.

---

## 4. `/bars` and `/health` — DB-only consumers, not offenders

`GET /bars` and `GET /health` legitimately need DB access and do not wait on external providers.

They are useful **victims/canaries** in the #107 test:

```text
external work remains blocked
+ /openapi.json stays responsive
+ /bars or /health stalls
= evidence consistent with DB-capacity starvation
```

They should not be 'optimized' to hide the symptom before the upstream resource ordering is fixed.

---

## 5. Scope rule

For PR #107:

```text
fix the measured path
not every route with a similar code smell
```

If `/backfill/bars` is enough to meet the issue acceptance target, stop there.

If mixed-load evidence shows `/ticker?fresh=true` materially consumes the same scarce pool during overload, the smallest clean follow-up may be to narrow its DB acquisition to the `fresh=false` branch. That should be justified independently rather than bundled by instinct.

---

## 6. Review implication for Candidate A

Candidate A intentionally uses `get_conn()` inside the backfill handler instead of route-scoped `DBConn` because the desired DB lifetime is shorter than the HTTP request lifetime.

That is a deliberate exception to the common route pattern, not an accidental style divergence.

The project already exposes `get_conn()` as shared infrastructure for explicitly scoped connection ownership. The implementation should include a short `why` comment so a future refactor does not 'simplify' the route back to a request-long DB dependency and reintroduce the capacity coupling.
