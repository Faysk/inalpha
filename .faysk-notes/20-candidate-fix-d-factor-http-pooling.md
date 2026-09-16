# Issue #107 — Candidate Fix D: Reuse Factor → Data HTTP Connections

**Status:** low-priority candidate. Do not implement unless runtime evidence shows connection churn materially affects latency/errors after the primary data-service capacity issue is understood.

---

## 1. Current behavior

`get_engine()` creates a new `FactorEngine` per incoming factor request.

Within the engine, `_fetch_df()` currently does:

```python
async with DataClient(self._settings.data_service_url, self._token) as dc:
    bars = await dc.get_bars(...)
```

Each `DataClient` constructs its own:

```python
httpx.AsyncClient(...)
```

and closes it when `_fetch_df()` returns.

During a cold live macro request, `_compute_macro()` can call `_fetch_df()` concurrently for many FRED series. That means one logical factor request may create many independent HTTP client/pool lifecycles.

This is a verified code property; whether it is performance-significant is still unmeasured.

---

## 2. Why connection reuse might help

A longer-lived HTTPX client can reuse:

```text
TCP connections
HTTP keep-alive
client connection pool state
socket resources
```

Potential improvements:

- lower connection setup overhead;
- fewer short-lived sockets;
- less local ephemeral-port/socket churn;
- better latency for bursty multi-series reads.

But none of these should be assumed to be #107's primary bottleneck.

---

## 3. Security constraint: never globalize a user's bearer token

Current factor dependency extracts the incoming request's bearer token and stores it on that request's `FactorEngine`.

A naïve singleton like:

```python
httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"})
```

must **not** be reused globally across requests/users.

That could leak one request's credentials into another request and would become especially dangerous in future multi-tenant deployment.

### Safe direction if selected

Separate:

```text
shared transport/client lifecycle
from
per-request Authorization header
```

For example conceptually:

```python
shared_client = httpx.AsyncClient(base_url=..., trust_env=False, timeout=...)

await shared_client.get(
    "/bars",
    headers={"Authorization": f"Bearer {request_token}"},
    params=...,
)
```

The token must remain request-scoped.

---

## 4. Possible lifecycle model

If selected, factor's FastAPI lifespan is the natural owner of a process-local data-service HTTP client.

Conceptual lifecycle:

```text
factor worker startup
→ create shared httpx.AsyncClient
→ store in app.state / explicit dependency
→ factor requests reuse connections
→ worker shutdown
→ aclose shared client
```

`get_engine()` would receive/inject the shared client plus the request token.

`FactorEngine`/`DataClient` would use the shared client without owning/closing it per fetch.

This is a larger refactor than Candidate A and therefore should have measured justification.

---

## 5. Alternative: shared transport rather than shared authenticated client

Another possible design is sharing an `httpx.AsyncHTTPTransport`/pool while constructing lightweight request clients around it.

Before choosing that approach, verify HTTPX transport ownership/close semantics carefully; accidental closing of a shared transport from one client could break all requests.

A single process-owned `AsyncClient` with per-request headers is conceptually simpler if project conventions permit it.

---

## 6. Trace propagation opportunity — do not mix automatically

Factor currently does not explicitly forward the data-service request's `X-Trace-Id` from the incoming request.

A client-lifecycle refactor could make trace propagation easier, but trace propagation is an independent behavior change.

Do not bundle it into Candidate D unless it is required to operate/debug the fix and can be tested clearly.

Avoid expanding #107 into a generic observability refactor.

---

## 7. How to prove connection churn is material

Before implementation, compare current vs a temporary pooling experiment while holding provider/DB behavior constant.

Useful evidence:

```text
factor request p50/p95/p99
number of TCP connections established
TIME_WAIT/socket count where practical
HTTPX connection errors/pool waits
CPU
wall-clock time of cold macro fan-out
```

Use a local/fake data-service endpoint first so external provider variability does not dominate.

If connection reuse changes little, reject Candidate D for #107.

---

## 8. Test requirements if selected

- [ ] connection/client lifecycle is process-owned and closes on shutdown;
- [ ] different bearer tokens are sent only on their own requests;
- [ ] no Authorization header is retained globally from a prior request;
- [ ] no-token request remains no-token and fails closed at data-service where expected;
- [ ] concurrent requests with different tokens do not cross-contaminate headers;
- [ ] existing GET retries/error mapping remain unchanged unless explicitly redesigned;
- [ ] fresh/backfill semantics remain unchanged;
- [ ] factor test suite remains green;
- [ ] measured p95/error improvement justifies the additional lifecycle complexity.

A dedicated concurrency test should inspect headers received by a fake local data server for two simultaneous tokens.

---

## 9. Scope/risk

Likely touched files if selected:

```text
services/factor/src/inalpha_factor/main.py
services/factor/src/inalpha_factor/deps.py
services/factor/src/inalpha_factor/engine.py
services/factor/src/inalpha_factor/data_client.py
services/factor/tests/...
```

That is still one service, but significantly larger than the likely Candidate A data-route change.

Do not combine A + D into one first PR merely because both are performance-related. Separate causal evidence and review surface are preferable.

---

## Selection gate

Choose Candidate D only if:

1. DB/provider capacity is controlled enough to isolate client behavior;
2. short-lived factor clients create measurable connection/socket/latency overhead;
3. a safe shared-client experiment materially improves the representative workload;
4. auth isolation has explicit regression tests.

Otherwise document connection churn as observed debt and leave it out of #107.
