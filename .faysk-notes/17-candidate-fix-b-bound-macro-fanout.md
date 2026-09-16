# Issue #107 — Candidate Fix B: Bound Live Macro Fetch Fan-Out

**Status:** fallback/secondary candidate. Do not implement unless runtime evidence shows factor macro burst remains a material contributor after the first measured bottleneck is addressed.

---

## 1. Current behavior

For live/near-now factor scoring, macro factors are fetched with:

```python
fetched = await asyncio.gather(*[_fetch_one(sid) for sid in sids])
```

The engine comment documents a daily snapshot with roughly 18 required FRED series.

Each `_fetch_one()` can reach:

```text
FactorEngine._fetch_macro_series
→ _fetch_df
→ new DataClient/httpx.AsyncClient
→ get_bars(fresh=True)
→ POST /backfill/bars
→ GET /bars
```

So one cold-cache factor request can create a large burst toward data-service.

---

## 2. What Candidate B would change

Introduce a bounded factor-side semaphore specifically around concurrent macro-series fetches.

Conceptually:

```python
fetch_sem = asyncio.Semaphore(settings.macro_fetch_concurrency)

async def _fetch_one(sid: str):
    async with fetch_sem:
        return await self._fetch_macro_series(...)
```

Potential setting:

```text
FACTOR_MACRO_FETCH_CONCURRENCY
```

No default value is selected in this document.

The issue text suggested 6–8 as an example, but our implementation value must come from measured latency/capacity trade-offs rather than copying the issue literally.

---

## 3. Why it may help

It prevents one factor request from immediately creating all macro backfill/read traffic at once.

If a limit of `N` is selected:

```text
18 series
→ ceil(18 / N) waves
```

For example only (not a recommendation):

```text
N=6 → 3 waves
```

This trades burst pressure for longer cold-cache wall time.

Because live macro data has a one-hour process cache after success, the cost is mainly on cold/expired paths.

---

## 4. What it does not solve

Candidate B protects only factor macro fan-out.

It does not protect data-service from:

- live-runner fresh polls;
- dashboard explicit backfills;
- orchestration direct backfill tools;
- paper/backtest fresh data paths;
- research fresh paths;
- multiple factor requests at the same time;
- other expensive data-service operations.

Therefore it is not a substitute for a data-boundary fix if the service itself needs generic overload protection.

---

## 5. Why Candidate A is currently tested first

Candidate A (narrow DB lease) changes the shared bottleneck behavior without changing request rates or caller contracts.

If A makes data-service stable under the representative mixed workload, adding B would be unnecessary latency/complexity.

Preferred decision sequence:

```text
measure DB/resource coupling
→ if H1 confirmed, test Candidate A
→ rerun mixed workload
→ only if macro bursts still materially harm capacity, evaluate Candidate B
```

---

## 6. Configuration vs hard-coded constant

Project precedent favors settings-driven operational limits for service behavior (e.g. web search/fetch concurrency).

A setting gives operators room to tune different hardware/deployments without code changes.

However, configuration is also API surface and maintenance cost.

If measurements show one universally safe small bound, a module constant could be simpler.

Do not decide this before the benchmark.

---

## 7. Test requirements if selected

- [ ] maximum concurrent `_fetch_macro_series` calls never exceeds configured limit;
- [ ] all requested series are still attempted;
- [ ] one failed series does not cancel the others;
- [ ] successful series still compute macro factors;
- [ ] live macro cache behavior remains unchanged;
- [ ] historical `fresh=False` semantics remain unchanged;
- [ ] cold-cache wall time remains within acceptable caller timeout;
- [ ] mixed-load data-service p95/error rate improves measurably.

A deterministic unit test can replace `_fetch_macro_series` with a blocking counter and assert peak concurrency.

---

## 8. Main trade-off

Candidate B is a classic pressure/latency exchange:

```text
lower concurrency
→ less burst pressure
→ more cold-cache latency
```

So success cannot be judged only by a lower number of concurrent requests.

Record:

```text
factor request p50/p95
macro completion ratio
peak data in-flight work
data GET/backfill p95
DATA_SERVICE_UNREACHABLE / timeout counts
```

---

## Selection gate

Select Candidate B only if baseline/after-A evidence shows:

1. cold/live macro fan-out creates a measurable capacity spike;
2. data-service remains affected even after any more fundamental scarce-resource coupling is fixed;
3. a bounded macro experiment improves service stability without making factor latency unacceptable.

Until then, this is a prepared fallback, not part of PR 1.
