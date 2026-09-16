# Issue #107 — Existing Inalpha Precedent: Never Hold DB Capacity Across External HTTP

**Status:** confirmed current-code design precedent.  
**Why it matters:** this substantially strengthens the architectural fit of Candidate A *if* runtime H1 evidence selects it.

During further review of `paper/live_runner.py`, the project itself states the same resource-ordering rule we independently derived for `/backfill/bars`.

---

## 1. The existing rule is explicit

Current live-runner code contains an M-1 reliability comment whose meaning is:

```text
DB reads and external FX HTTP must be strictly separated.
Never issue external requests while holding a pooled DB connection.
Otherwise slow/timeout external data under concurrent runs can exhaust the DB pool
and harm unrelated application paths.
```

This is not merely a style inference. The implementation directly follows the rule.

---

## 2. Existing PnL update shape

Current pattern:

```python
async with get_conn() as conn:
    quote_total, currency, base = await self._read_run_pnl_quote(...)

# DB connection has been returned to the pool here.
pnl = await self._convert_run_pnl_to_base(...)

async with get_conn() as conn:
    await runs_store.update_progress(...)
```

The source comment explicitly points out that the first connection is returned **before** FX conversion that may perform HTTP.

Architecturally:

```text
short DB read
→ release DB
→ external network work
→ short DB write
```

---

## 3. Existing perp-funding shape

The same module repeats the M-1 rule for funding accrual:

```text
1. short DB position read
2. release DB
3. fetch funding rate + mark through data-service HTTP
4. short DB cash/log write
```

Again, the code deliberately avoids:

```text
DB connection
→ external HTTP await
→ DB write
```

while retaining the same connection.

---

## 4. Candidate A is the same reliability pattern at another boundary

Current `/backfill/bars` is effectively the opposite:

```text
DB checkout
→ latest_bar_ts
→ external provider await
→ DB write
→ route exit / release
```

Candidate A proposes:

```text
short DB latest_bar_ts read
→ release DB
→ external provider fetch
→ short DB write
```

So if H1 is measured, Candidate A would not introduce a novel resource-management philosophy.

It would make data-service backfill follow an already documented Inalpha reliability pattern used in a high-risk live execution component.

---

## 5. Why this changes our confidence — but not the evidence gate

This finding increases confidence in **project fit**:

- explicit precedent exists;
- precedent was created specifically to prevent pool exhaustion under slow external I/O;
- it uses `get_conn()` in short scopes;
- it separates read/network/write phases exactly like Candidate A;
- it exists in live-runner code where correctness expectations are high.

It does **not** prove:

```text
/backfill DB lease is the dominant cause of #107
```

We still need the baseline.

Correct conclusion:

```text
H1 measured true
+
existing project precedent
→ Candidate A becomes both evidence-driven and architecturally native
```

Not:

```text
similar code exists elsewhere
→ implement Candidate A without measuring
```

---

## 6. Useful PR/review framing if Candidate A is selected

We should avoid saying merely:

> "I refactored DB access to improve performance."

A more precise engineering explanation would be:

```text
/backfill/bars currently retains a pooled DB connection while awaiting external market-data I/O.
Under concurrent slow backfills this couples provider latency to DB capacity.
The change narrows the connection lifetime to DB-only phases, matching the existing resource-ordering
pattern already used by live-runner around external FX/funding calls.
```

Then support it with the deterministic before/after evidence.

Do not cite internal M-1 as an authority instead of showing benchmark results; use it to explain why the implementation shape is consistent with the codebase.

---

## 7. Additional implication for the adjacent audit

This precedent also tells us how to reason about other paths we found:

```text
fresh ticker route with unused route-level DBConn
constituent snapshot fetching external members while holding DB
```

They exhibit the same resource-ordering smell.

But scope discipline remains unchanged: similar smell elsewhere does not automatically belong in #107 PR1.

Fix only the measured workload unless the maintainer explicitly wants a broader audit cleanup.

---

## Current conclusion

One of the strongest static findings so far is now:

> **The project already treats “holding a DB pool connection across potentially slow external HTTP” as a reliability anti-pattern and has production code that deliberately splits DB → network → DB phases to avoid pool exhaustion.**

This makes Candidate A a much more natural first fix *if the runtime baseline confirms H1*.