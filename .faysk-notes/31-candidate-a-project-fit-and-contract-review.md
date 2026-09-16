# Issue #107 — Candidate A Project Fit and Observable Contract Review

**Status:** static review only. Candidate A is still unselected until runtime H1 evidence exists.

This pass asks a narrower question than the earlier Candidate A design review:

> If runtime evidence selects DB-lease narrowing, does the proposed code shape fit the existing project style and what observable behavior could change even if the public request/response schema does not?

---

## 1. Direct `get_conn()` inside an API route already has project precedent

The shared helper documents itself primarily for background/non-FastAPI contexts, but current project code also uses it directly inside factor API endpoints.

Example pattern in `services/factor/src/inalpha_factor/api/candidates.py`:

```python
async def propose_candidate(...):
    ...
    async with get_conn() as conn:
        ...
```

So Candidate A's intended shape:

```python
async with get_conn() as conn:
    cached_latest = await latest_bar_ts(...)

# external provider await with no DB lease

async with get_conn() as conn:
    await insert_bars(...)
```

is not a new architectural idiom for Inalpha and does not require changing `_shared`.

This reduces review risk compared with inventing a new connection-factory dependency solely for #107.

---

## 2. Current data tests do not rely on overriding the DB dependency

`services/data/tests/conftest.py` starts the real data-service lifespan and therefore the real shared DB pool. Connector behavior is replaced through the connector registry, not through a `DBConn` dependency override.

This matters because replacing route-level `DBConn` with explicit `get_conn()` would bypass FastAPI dependency overrides for the DB connection if such tests existed.

Current data tests do not appear to depend on that pattern.

The prepared #107 regression therefore controls pool size by patching the `init_pool` symbol used by `inalpha_data.main.lifespan`, then exercises the real shared pool.

That is closer to the production connection path than mocking `get_conn()` itself.

---

## 3. Authentication remains independent

`get_current_user` verifies the bearer JWT from shared settings and does not need a database connection.

Candidate A removes only the route's `DBConn` dependency. It does **not** remove or weaken:

- bearer-token validation;
- JWT algorithm restrictions;
- expiration checks;
- `token_use=session` rejection;
- `sub` claim requirement.

So the resource-lifetime change does not weaken the route's authentication boundary.

---

## 4. Public API schema should remain unchanged

`DBConn` is an internal FastAPI dependency, not a request field or response field.

Removing it from the route signature should not change:

- `POST /backfill/bars` request JSON;
- `BackfillResponse`;
- auth header contract;
- error JSON shape by itself;
- OpenAPI request/response schema visible to callers.

Still compare generated OpenAPI before/after if practical; do not rely only on reasoning.

---

## 5. There is a real error-precedence change to acknowledge

Today the DB dependency is resolved before the route body can run its own venue/timeframe/span checks.

Candidate A would defer the first DB checkout until after those pure validation/routing steps.

Therefore under simultaneous DB unavailability and an invalid backfill request, observable error precedence may change from roughly:

```text
DB dependency cannot acquire connection
→ generic service failure
```

into:

```text
route validates request first
→ deterministic validation/unsupported-venue error
```

For valid requests, Candidate A still needs DB and will still fail explicitly if no connection can be acquired.

This precedence change is arguably cleaner, but it is still a behavior change and should not be hidden in review language.

Do **not** add a new DB-unavailable error code in the same PR unless runtime evidence or maintainer feedback requires it; that would expand the contract surface unnecessarily.

---

## 6. Candidate A increases checkout count while reducing checkout duration

Current route:

```text
1 DB checkout for the whole request
```

Candidate A:

```text
1 short checkout for latest_bar_ts
+ 1 short checkout for each persisted provider batch
```

The route hard-limits estimated request size to 50,000 bars and fetches in batches of at most 1,000.

Static upper bound for a maximally batched request is therefore approximately:

```text
1 initial lookup + up to 50 persistence checkouts = up to 51 DB acquisitions
```

This is a deliberate trade:

```text
more acquisitions
but
much shorter ownership periods
```

Runtime before/after must therefore record both:

- DB wait/availability for unrelated requests;
- backfill total latency/throughput.

If acquisition overhead becomes material, measure it before redesigning. Do not optimize it preemptively.

---

## 7. Reacquisition may improve fairness, but do not claim it without measurement

A long backfill currently owns one connection for its entire external-I/O lifetime.

Candidate A re-enters the pool only when it has actual DB work.

That should give unrelated DB reads more opportunities to acquire a slot, but exact queue fairness belongs to the pool implementation/runtime and should be evidenced rather than asserted in the PR.

The endpoint-level regression (`slow provider calls coexist with responsive /health`) is the preferred proof.

---

## 8. Transaction/failure behavior remains compatible

`insert_bars()` already:

- uses `ON CONFLICT ... DO UPDATE`;
- commits each batch explicitly;
- returns the input row count.

Candidate A therefore does not split one request-wide atomic transaction; the route is already durable per batch.

If a provider fetch succeeds and the subsequent DB checkout/write fails:

```text
that fetched batch is not committed
→ next retry resumes from the last durable timestamp
→ provider work may be repeated
```

This is recoverable under the current idempotent persistence model.

---

## 9. Preferred upstream test shape if Candidate A is selected

Keep the production diff focused and put the invariant in an integration regression.

A clean test property is:

```text
pool max_size = 2
4 unique backfills reach a blocked fake provider
while
/health can still acquire DB and return 200
```

This avoids coupling the test to the ordinary production default of 10 connections.

Possible location:

```text
services/data/tests/test_backfill_capacity.py
```

rather than expanding venue-routing tests with capacity concerns. Final placement should follow maintainer preference; the important part is the tested property.

The test should use the normal lifespan/shared pool and fake provider registry, matching current data-test conventions.

---

## 10. Review checklist before turning the patch into a commit

If H1 selects Candidate A:

- [ ] verify `get_conn()` direct route use remains accepted on current upstream;
- [ ] run current backfill router tests unchanged;
- [ ] add deterministic small-pool capacity regression;
- [ ] verify auth failures still behave identically;
- [ ] compare OpenAPI route contract;
- [ ] verify invalid venue/timeframe/span behavior;
- [ ] document the DB-outage/error-precedence nuance if observed;
- [ ] measure backfill latency/throughput for multi-batch requests;
- [ ] verify provider failure still maps to `BARS_UPSTREAM_UNAVAILABLE`;
- [ ] verify DB write failure does not create fake success;
- [ ] rerun the provider-capacity checks from note 28 so the bottleneck is not merely moved.

---

## Current conclusion

From static project-fit review, Candidate A is structurally compatible with existing Inalpha patterns and can remain a `services/data`-local change.

The main non-obvious trade-offs are:

1. more short DB acquisitions per multi-batch request;
2. error precedence can improve/change because DB checkout moves after pure validation;
3. provider concurrency may become more visible once DB is no longer accidentally limiting it.

None of those invalidate Candidate A, but all belong in the before/after evidence if runtime selects it.