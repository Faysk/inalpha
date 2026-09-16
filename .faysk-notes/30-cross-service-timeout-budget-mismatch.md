# Issue #107 — Nested Cross-Service Timeout Budgets

**Status:** static timing risk; runtime cancellation behavior still belongs to H9.

---

## 1. A caller can give up before its downstream work reaches its own deadline

Paper's `FactorClient` uses a default HTTP timeout of:

```text
paper → factor = 30s
```

This client is used by `capture_factor_baseline()` and FactorPatrol for factor `/score` and `/snapshot`.

Inside a live factor request, each `DataClient` has:

```text
factor → data GET /bars default timeout = 30s
factor → data fresh POST /backfill/bars explicit timeout = 60s
```

So a live factor request can be waiting on an internal data backfill whose own timeout is **longer than the paper caller's entire factor request timeout**.

---

## 2. Startup example

For a resumed daily run with no factor lineage:

```text
paper live-run task
→ capture_factor_baseline
→ FactorClient.snapshot            [paper timeout 30s]
→ factor /snapshot
→ _score_with_series live
→ macro _compute_macro
→ concurrent _fetch_macro_series
→ factor DataClient fresh backfill [POST timeout 60s each]
```

If data-service is saturated/slow:

```text
T+30s paper may already see FACTOR_SERVICE_UNREACHABLE / timeout and give up best-effort
while
factor's internal data work may still be inside a longer deadline
```

Whether that internal work is cancelled when the paper client disconnects is a runtime question.

---

## 3. Why H9 matters at more than one hop

We initially framed H9 as:

```text
factor client times out data request
→ does data server work continue?
```

There is also a possible outer layer:

```text
paper client times out factor request
→ does factor request continue?
→ if yes, do its factor→data calls continue?
```

So abandoned work can theoretically exist at multiple service boundaries.

Do not claim this happens until measured with real Uvicorn/TCP behavior.

---

## 4. Why “just increase the paper timeout” is not a capacity fix

Changing:

```text
paper → factor 30s → 60s/90s
```

might reduce `FACTOR_SERVICE_UNREACHABLE` for baseline capture, but it would not remove data-service saturation.

It could simply keep more callers waiting longer.

Likewise, decreasing timeouts without understanding cancellation can create more retries/abandoned work.

Timeout values are not a substitute for fixing the first constrained resource.

---

## 5. Why Candidate A can improve this without touching timeout contracts

If data backfill is slow mainly because provider waits monopolize DB capacity, Candidate A can shorten unrelated data read latency and reduce the chance that factor requests reach either 30s or 60s deadlines.

That is attractive because it can improve the nested chain without changing:

- paper FactorClient timeout;
- factor DataClient timeout;
- caller retry/error contracts;
- live-runner behavior.

But this must be demonstrated before claiming it.

---

## 6. Runtime evidence to capture if the mixed workload reaches these deadlines

Use trace IDs/log timestamps where possible to reconstruct:

```text
paper factor request start
paper timeout / failure time
factor request start/end
factor → data backfill start/end
factor → data bars GET start/end
```

Questions:

1. Did paper time out before factor completed?
2. Did factor continue after the paper client deadline?
3. Did factor continue issuing/awaiting data work after that deadline?
4. Did the data request itself later time out/retry?
5. Did Candidate A move these operations below the outer deadline without timeout changes?

---

## 7. Scope rule

Deadline propagation / request cancellation across paper → factor → data would be a broader cross-service design change.

Do **not** turn #107 PR 1 into distributed cancellation/deadline propagation unless runtime evidence shows the local data-service fix cannot meet the issue target.

If needed later, treat it as an explicit architecture discussion rather than an incidental timeout tweak.
