# Issue #107 — H9: Client Timeout vs Server Work Cancellation

**Status:** runtime hypothesis only. Static code cannot determine the real Uvicorn/ASGI disconnect behavior here.

---

## 1. Why this matters

One plausible #107 chain is:

```text
server becomes slow under capacity pressure
→ factor reaches its HTTP deadline
→ httpx raises RequestError/ReadTimeout
→ factor retries
```

Whether retries amplify pressure depends partly on what happens to the **older server request** after the client has already timed out.

Two very different behaviors are possible:

### A. Work is promptly cancelled

```text
client timeout/disconnect
→ server request task/provider wait is cancelled
→ old work releases capacity
→ retry mostly replaces old work
```

### B. Work continues after client timeout

```text
client timeout/disconnect
→ caller retries
but
old server request continues provider/DB work
→ old + new attempts overlap
→ retries amplify in-flight pressure
```

We must not assume either from framework folklore.

---

## 2. Why code inspection is insufficient

Factor maps the final `httpx.RequestError` to `DATA_SERVICE_UNREACHABLE`, but that only describes the caller side.

The data route does not explicitly poll `request.is_disconnected()` and does not install its own cancellation policy.

Actual cancellation depends on the concrete Uvicorn/Starlette/AnyIO behavior and where the request is awaiting when the peer disappears.

Therefore H9 requires a real HTTP socket experiment, not `httpx.ASGITransport`.

---

## 3. Prepared deterministic probe

Files:

```text
.faysk-notes/tools/issue107_slow_data_app.py
.faysk-notes/tools/issue107_timeout_persistence_probe.py
```

Run the fake-provider wrapper with one worker first:

```text
provider delay = 5s
client request timeout = 0.5s
attempts = 4
```

The wrapper now tracks per-process:

```text
active
started
completed
cancelled
failed
```

through a DB-free endpoint:

```text
GET /__issue107/state
```

and logs provider start/done/cancel/fail events.

No external market-data source is contacted.

---

## 4. Interpretation

### Evidence for work surviving caller timeout

```text
client sees ReadTimeout around 0.5s
AND
state immediately after shows active > 0
AND/OR
completed increases several seconds later
```

This would mean old requests can overlap newer attempts in this topology.

### Evidence for prompt cancellation

```text
client times out
AND
cancelled increases close to started
AND
active quickly returns to 0
```

Then retry amplification from abandoned server work is weaker than H1b currently fears.

### Mixed result

Some requests may cancel while others finish, especially with multiple workers or different await points. Preserve that result rather than forcing a binary conclusion.

---

## 5. Scope caution

Even if H9 is confirmed, do **not** immediately add explicit disconnect polling/cancellation to `/backfill/bars`.

Questions first:

- Is provider work safely cancellable?
- Can cancellation happen after provider data is fetched but before persistence?
- Do synchronous executor-backed providers actually stop, or only the asyncio waiter?
- Would cancellation create more duplicate provider work on retry?
- Does Candidate A already keep DB capacity healthy even if external provider work survives?

For yfinance specifically, the project already documents that timing out/cancelling the asyncio waiter cannot necessarily stop the underlying synchronous worker thread. That means cancellation semantics can be provider-specific.

H9 is primarily needed to understand the retry-pressure model, not to expand PR #107 automatically.

---

## 6. Decision impact

```text
H1 true + H9 true
→ DB leases are scarce and stale requests may overlap retries
→ Candidate A becomes even more valuable for protecting DB capacity
→ admission may still be needed if surviving external work itself becomes the next bottleneck

H1 true + H9 false
→ DB lease issue still exists, but retries replace old work more cleanly
→ Candidate A can still be sufficient

H1 false
→ H9 alone does not justify Candidate A
```

---

## 7. Acceptance discipline

Do not write in the PR:

```text
"timeouts caused retry storms because old server requests kept running"
```

unless this experiment (or equivalent production evidence) actually demonstrates it.
