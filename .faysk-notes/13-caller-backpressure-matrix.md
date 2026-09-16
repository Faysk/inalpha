# Issue #107 — Backfill Caller / Backpressure Compatibility Matrix

**Status:** static compatibility review.  
**Purpose:** make sure a future data-service admission-control or busy-response design does not silently break freshness or caller behavior.

---

## Why this matters

A server-side capacity gate can be technically correct and still be a bad project change if callers interpret its response incorrectly.

The relevant question is not only:

```text
What should /backfill/bars return under pressure?
```

It is also:

```text
What will every caller do next?
```

The current project intentionally has different degradation contracts across factor, paper, research, dashboard, and orchestration.

---

## Matrix

| Caller | Refresh behavior | Non-2xx backfill behavior | What happens after refresh failure | #107 concern |
|---|---|---|---|---|
| `factor.DataClient` | `fresh=True` calls `_best_effort_backfill()` before `GET /bars` | Current helper does **not inspect HTTP status**; only transport/raised exceptions enter warning path | Continues to `GET /bars` | A new `429/503` could be silently ignored and stale cache read as if refresh had been attempted successfully |
| `paper.DataClient` | `fresh=True` calls explicit `backfill_bars()` | Explicit method converts non-2xx to `DataServiceError` | `get_bars()` catches refresh exception, logs, then reads cached bars | Busy is visible in logs but caller deliberately degrades to cache |
| `research.DataClient` | Mostly `fresh=False`; explicit fresh paths may backfill | Best-effort/degraded semantics | Continues with cached data where designed | Should preserve explicit degradation, not convert research outages into hard failure unnecessarily |
| dashboard bars BFF | Refreshes only when chart data is empty/stale | Refresh is best-effort | Re-reads DB bars; chart may remain stale | Already has process-local same-key coalescing; do not duplicate functionality blindly |
| orchestration TypeScript client/tool | Explicit tool/API call | Shared HTTP client throws on non-2xx and preserves upstream status/code/details | Tool fails explicitly unless higher layer handles it | `DATA_SERVICE_BUSY` could be represented cleanly here |
| paper live runner | Uses `paper.DataClient.get_bars(... fresh=True)` each poll | Same as paper client | Cached bars may be returned; dedupe usually prevents processing the same old bar again | Overload can become “no progress” rather than direct crash, but repeated polling still contributes load |

---

## 1. Factor is the most important compatibility trap

Current factor helper:

```text
fresh=True
→ POST /backfill/bars
→ HTTP response status is not checked
→ GET /bars
```

Only an actual Python exception from the POST enters `factor_backfill_failed` logging.

Therefore if we add:

```text
429 DATA_SERVICE_BUSY
```

or:

```text
503 DATA_SERVICE_BUSY
```

without changing factor semantics, `httpx` will return a normal Response object and factor will continue to `GET /bars`.

This creates a possible failure shape:

```text
capacity gate rejects refresh intentionally
→ factor treats POST as completed
→ reads old cached bars
→ live score/snapshot may continue
```

This is especially sensitive because current factor code explicitly treats near-now/as_of=None requests as `fresh=True` for financial-freshness reasons.

### Rule

If the chosen #107 solution introduces intentional non-2xx backpressure on `/backfill/bars`, factor compatibility must be part of the same design review.

That does **not** automatically mean factor must hard-fail. It means the degradation must be deliberate and observable rather than accidental.

---

## 2. Paper has explicit error parsing but intentionally degrades

`paper.DataClient.backfill_bars()` checks `r.status_code >= 400` and converts upstream errors to `DataServiceError` with the upstream code/status/body.

However `paper.DataClient.get_bars(fresh=True)` wraps the refresh in:

```text
try backfill
except → warning
continue to GET /bars
```

So paper's contract is intentionally:

```text
refresh preferred
cache fallback allowed
```

For historical/backtest and live-runner callers this behavior is part of the current design.

A new busy error will therefore be logged and degraded rather than automatically stopping the caller.

---

## 3. Live runner: overload may become no-progress

The live runner polls fresh bars through the paper client.

If refresh fails but old DB bars are still readable:

```text
GET /bars returns same last closed bar
→ last_bar_ts dedupe sees no new bar
→ runner sleeps and polls again
```

This is safer than processing stale data as a new bar, but operationally it can still create a bad loop:

```text
overload
→ refresh fails
→ cached read succeeds
→ sleep
→ synchronized retry by several runners
```

So a capacity fix should measure **request rate after degradation**, not only errors.

Potential future jitter/staggering remains a follow-up only if the data-service boundary fix does not sufficiently control this behavior.

---

## 4. Dashboard already implements one form of duplicate-work control

The dashboard bars route already coalesces in-flight same-key chart backfills using an in-process Promise map.

Therefore a generic server-side single-flight mechanism must be justified by duplication observed from **other callers or cross-service overlap**.

Do not cite dashboard duplicate traffic as a reason for data-side single-flight without measurements.

---

## 5. Orchestration is easiest to make explicit

The TypeScript shared HTTP client treats non-2xx responses as errors and preserves upstream response information.

That means a future stable error such as:

```json
{
  "code": "DATA_SERVICE_BUSY",
  "message": "backfill capacity temporarily exhausted",
  "details": {"retryable": true}
}
```

can be surfaced clearly through orchestration.

But choosing the code/status is still a product/API decision. Do not add it solely because orchestration can handle it.

---

## 6. `429` vs `503` — decision criteria, not preference

### `429 Too Many Requests`

Semantically fits request-rate/admission limits, especially if the caller could retry later.

Potential issue:

- project already has rate-limited semantics that may imply external/user quota rather than internal capacity;
- live runner currently classifies `InalphaError` 4xx as deterministic/non-retryable in some paths.

A `429` propagated into a path that applies the live-runner retry classifier could therefore be interpreted as **do not retry**, which may be wrong for temporary capacity pressure.

### `503 Service Unavailable`

Semantically fits temporary service capacity/unavailability and is generally retryable by infrastructure callers.

Potential issue:

- clients that best-effort degrade may hide it unless logs/metrics are sufficient;
- uncontrolled caller retries can recreate a retry storm.

### Current conclusion

Do not choose between 429/503 until we know:

1. whether the first fix even needs an explicit busy response;
2. which caller path will receive it;
3. whether that caller's retry classifier treats the code correctly.

---

## 7. Compatibility requirements for any admission-control PR

If the final fix returns intentional overload responses, verify at minimum:

- [ ] factor fresh path does not silently misrepresent rejected refresh as successful freshness;
- [ ] paper/live runner does not classify temporary capacity as a permanent strategy error;
- [ ] orchestration preserves a stable machine-readable code;
- [ ] dashboard degradation remains understandable;
- [ ] retry behavior is bounded;
- [ ] no caller converts a temporary busy state into aggressive immediate retry;
- [ ] historical `fresh=False` reads are not unnecessarily blocked by backfill capacity;
- [ ] successful responses still mean what they meant before the change.

---

## 8. Preferred path if DB-lifetime fix is sufficient

If runtime evidence shows that simply releasing DB capacity during external I/O solves the representative workload, that is attractive because it may avoid changing the `/backfill/bars` HTTP contract at all.

Then:

```text
same endpoint
same success/error semantics
same callers
less scarce-resource coupling
```

This has a much smaller compatibility surface than introducing a new busy response.

That is one reason candidate Fix A (narrow DB lease) should be tested before we assume a new backpressure API is required.

---

## Working rule

> Capacity behavior is part of the API contract when callers make freshness and retry decisions from the response.

We should not make overload explicit on the server while accidentally making it implicit again in the client.
