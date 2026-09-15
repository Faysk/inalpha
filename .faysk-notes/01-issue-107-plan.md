# Inalpha Issue #107 — Technical Plan

**Issue:** https://github.com/mirror29/inalpha/issues/107  
**Repository:** https://github.com/mirror29/inalpha  
**Contribution branch:** `fix/data-service-saturation`  
**Notes branch:** `notes/issue-107`  
**Reviewed upstream baseline:** `main` at `ed01be9056776c107ab76a404c328a4fed19f529`  
**Status:** aligned discovery plan / awaiting maintainer confirmation  
**Last updated:** 2026-09-16

---

## 1. Goal

Resolve the sustained-load failure mode described in #107:

> `data-service` becomes saturated when factor/panel activity, concurrent refresh/backfill work, and background live-runner polling overlap, causing requests to slow down or become unreachable.

The issue's validation target is the anchor for this contribution:

```text
representative agent + live-runner mixed load
→ no DATA_SERVICE_UNREACHABLE
→ controlled/bounded p95 latency
```

The goal is **not** to survive arbitrary/unbounded load or increase concurrency blindly. The system should have a clear supported workload envelope and degrade deliberately beyond it rather than failing through connection refusal/timeouts.

The data path should become:

- measurable,
- bounded,
- predictable under sustained load,
- resistant to retry amplification,
- operationally understandable,
- correct with respect to financial freshness.

The first upstream implementation should remain deliberately small.

---

## 2. Current-state findings

Upstream `main` has not changed since the reviewed commit above. Issue #107 was opened in June 2026, and part of its original proposed mitigation has already landed.

### Already present

- `FactorEngine.panel_score()` bounds symbol fetch concurrency with `_PANEL_FETCH_CONCURRENCY = 16`.
- Multi-symbol custom factor scoring reuses the same bound.
- Cross-sectional panel scoring deliberately avoids forced per-symbol backfills and reads DB-cached bars.
- `/backfill/bars` performs incremental continuation from the latest persisted bar.
- factor `DataClient.get_bars()` has bounded retry/backoff for connection-level GET failures.
- structured logging and `trace_id` already exist.
- bounded concurrency via `asyncio.Semaphore` is already a normal project pattern.
- the dashboard already performs **process-local same-key backfill coalescing** for its bars endpoint.

### Still-relevant fan-out

The original issue's factor-side fan-out is not completely gone.

For live/current daily/weekly factor scoring, macro factors can request the required FRED series concurrently using `asyncio.gather`. A 1d snapshot can involve roughly 18 macro series. Each uncached live macro fetch can reach the factor data client with `fresh=True`, which may trigger `/backfill/bars`.

So the current reproduction should prioritize **live factor + macro fan-out**, not assume the already-bounded panel path is still the dominant source.

### Critical resource-lifetime finding

`POST /backfill/bars` currently receives `db: DBConn` as a FastAPI dependency. That means a DB connection is checked out for the lifetime of the route invocation. The route then:

```text
DB latest_bar_ts query
→ external provider fetch (possibly slow/serialized)
→ DB insert
→ external provider fetch ...
```

The shared pool defaults to `max_size=10` **per process**.

Production compose currently configures `data-service` with:

```text
WORKERS=2
```

Therefore sustained backfills may consume scarce DB connections while waiting on external network/provider work. This is now a first-class hypothesis for #107 and must be measured before simply adding a semaphore.

### Provider serialization can amplify the above

The yfinance connector intentionally serializes `history` fetches per process behind `_FETCH_LOCK` and a minimum request interval. That is correct for Yahoo rate-limit/data quality, but it means concurrent yfinance backfill requests can queue at the provider layer.

If those requests have already checked out `DBConn`, they can occupy DB pool slots while waiting for the provider lock.

This is a hypothesis about the saturation mechanism, not yet a declared root cause.

### Caller behavior is not uniform

`/backfill/bars` is used by multiple components with different degradation semantics:

- **factor**: best-effort refresh before `GET /bars`; current helper does not automatically convert every non-2xx backfill response into an exception.
- **paper**: `backfill_bars()` raises on non-2xx, but `get_bars(fresh=True)` catches refresh failures and then reads bars.
- **research**: best-effort refresh is intentionally allowed to degrade to DB-cached bars.
- **dashboard**: stale/empty display path performs same-key coalescing and intentionally falls back to existing bars if refresh fails.
- **orchestration**: can call the data backfill endpoint directly through its data client.

Any new overload status must therefore be checked against a **caller compatibility matrix**. We must not assume one failure policy is correct for every caller.

### Known benchmark confounder

The yfinance connector currently catches some fetch failures and can return an empty result, which `/backfill/bars` may treat as a completed request with zero fetched rows rather than an HTTP error. This is tracked separately in upstream issue #74.

For #107 benchmarking, HTTP `200` alone is not enough to count a refresh as successful. Record zero-row/no-progress results and provider error logs separately. Do not expand this PR into fixing #74 unless it blocks the #107 solution.

---

## 3. Scope

### In scope

- `services/data`
- `services/factor` only if measurements or overload semantics require a caller fix
- reproducible contributor-side load/reliability tooling
- service-to-service HTTP behavior relevant to #107
- DB-connection lifetime around backfill
- admission control / backpressure if justified
- retry semantics relevant to sustained overload
- minimal observability needed to prove the cause/fix
- deterministic regression tests
- live-runner scheduling only if measurements show it remains a major contributor after data-side protection

### Out of scope for the first pass

- factor formula changes
- trading strategy changes
- research/debate changes
- unrelated freshness/error-semantics debt such as issue #74 unless it directly blocks #107
- whole-system redesign
- distributed queues/locks without evidence
- horizontal scaling as the first solution
- worker-count tuning by guesswork
- new telemetry infrastructure by default
- large unrelated refactors

---

## 4. Success criteria

Exact p95 thresholds/workload size should be finalized after baseline measurement or maintainer input.

For the agreed representative workload:

- [ ] Reproducible mixed-load scenario exists.
- [ ] Baseline and fixed p50/p95/p99 latency are recorded.
- [ ] Request/error/result-class counts are recorded.
- [ ] `DATA_SERVICE_UNREACHABLE` count is **zero after the fix** under the target mixed workload.
- [ ] p95 is bounded/repeatable rather than growing without control.
- [ ] Expensive in-flight work and DB-pool pressure are observable enough to explain the result.
- [ ] Backfill work is bounded if measurements show it needs bounding.
- [ ] Overload beyond the supported envelope does not create unbounded work or retry storms.
- [ ] Intentional backpressure is distinguished from transport failure/timeouts.
- [ ] Same-key duplicate work is removed only if proven significant across callers.
- [ ] Existing data/factor correctness tests remain green.
- [ ] Financial freshness semantics are preserved.
- [ ] No financial correctness behavior changes silently.

---

# 5. Implementation strategy

## Phase 0 — Reproduce before changing production code

### Objective

Verify whether current `main` still reproduces the failure class from #107 and identify the first saturated resource.

### Environment discipline

Run two kinds of tests:

1. **single-process deterministic diagnostics** — easier to isolate pool/gate behavior;
2. **production-like data topology** — `WORKERS=2`, without `--reload`, because current production compose uses two data workers.

Do not use `--reload` behavior as evidence for sustained production capacity. The issue explicitly distinguishes transient reload blips from sustained overload.

### Work

- [ ] Start supported local stack.
- [ ] Confirm services healthy.
- [ ] Record exact commit SHA and topology.
- [ ] Run existing data/factor tests before changes.
- [ ] Build contributor-side load harness using existing dependencies where possible.
- [ ] Run workloads individually.
- [ ] Run mixed workload.
- [ ] Capture logs, latency distribution, DB-pool symptoms and provider behavior.

### Workload A — backfill capacity / slow-provider diagnostic

Use fake/delayed connectors first so provider latency is deterministic and no public API is stressed.

Concurrency ramp:

```text
1
2
4
8
12
16
```

Important observations:

- checked-out/waiting DB connections,
- requests waiting behind provider serialization,
- health/bars latency while backfills are active,
- time until first timeout/connection error.

This workload is specifically intended to test whether DB connections are being held across slow external I/O.

### Workload B — live factor + macro fan-out

Exercise a current/live daily or weekly factor path with macro factors enabled so the current FRED gather behavior is represented.

Measure:

- number of factor→data calls,
- number of backfills,
- short-lived HTTP client count/connection churn where practical,
- data-service latency/errors,
- macro degradation count,
- DB-pool pressure.

This is more representative of the still-unbounded factor fan-out described by the original #107 than panel-only traffic.

### Workload C — factor panel control

Run representative panel requests:

```text
~10 symbols
~50 symbols
~300 symbols where meaningful/supported
```

Treat this primarily as a **control/current-state validation** because the path already has concurrency 16 and avoids per-symbol forced backfill.

### Workload D — live-runner-like polling

Prefer the actual runner if setup is practical; otherwise emulate its fresh-bar cadence.

Representative counts:

```text
1
4
up to 10 runs/account where practical
```

The current configured per-account cap defaults to 10; production may also have multiple accounts, so maintainer deployment context still matters.

### Workload E — mixed

Combine the workloads that baseline evidence identifies as relevant, especially:

```text
live factor/macro activity
+ expensive backfills
+ live-runner polling
```

Panel traffic may be included as a control but should not be forced into the mix if it no longer contributes materially.

### Benchmark discipline

For deterministic local scenarios:

- warm up before recording where useful,
- use a fixed request count or duration,
- collect enough samples for p95 to be meaningful,
- repeat representative runs (target 3 repetitions where practical),
- keep commit/topology/hardware/config identical before vs after,
- report variability rather than cherry-picking the best run.

### Baseline fields

```text
scenario
topology / worker count
duration
total_requests
successful HTTP responses
successful refreshes / rows progressed
zero-row or no-progress backfills
failed_requests
DATA_SERVICE_UNREACHABLE count
intentional busy/backpressure count
HTTP 5xx count
timeout count
p50
p95
p99
max latency
peak in-flight expensive work
DB pool checked-out / wait / timeout symptoms
pg_stat_activity state if available
CPU
memory
provider-specific errors
```

### Phase exit

Do not tune concurrency until we can state which resource saturates first and why.

---

## Phase 1 — Use existing observability first

### Objective

Explain the baseline with the least production-code instrumentation possible.

The project already has request duration/status logs, structured logging and trace IDs. Start there plus external benchmark/DB observations.

Only add targeted production log fields if the existing evidence cannot distinguish the cause.

Candidate fields if needed:

```text
backfill_wait_ms
backfill_in_flight
provider_fetch_ms
db_latest_lookup_ms
db_write_ms
total_request_ms
provider / venue
result class
```

Do not introduce Prometheus/OpenTelemetry just for PR 1 unless the maintainer asks.

### Phase exit

For the representative slow/failing request, we can explain where the time/capacity went.

---

## Phase 2 — Fix the first proven capacity boundary

### Objective

Apply the smallest change supported by baseline evidence.

There are two closely related candidates, and measurements decide ordering.

### Candidate A — shorten DB connection lifetime around external I/O

Current route-level `DBConn` keeps a pool connection checked out while external provider work runs.

If this is proven to be a material bottleneck, restructure the backfill flow so DB connections are acquired only for DB phases, for example conceptually:

```text
validate
→ short DB checkout: latest_bar_ts
→ release DB
→ provider fetch
→ short DB checkout: insert/commit
→ release DB
→ repeat
```

Do not choose exact implementation until transaction/correctness behavior is tested.

### Candidate B — bounded backfill admission

If expensive in-flight backfills themselves are the limiting resource, add a configurable **per-worker process-local** gate.

Potential settings:

```text
DATA_BACKFILL_MAX_CONCURRENCY
DATA_BACKFILL_QUEUE_TIMEOUT_S
```

Do not call this a service-global gate: production currently runs two data workers, so a process-local limit of `N` permits roughly up to `2 × N` in-flight operations across the container.

### Critical gate-placement constraint

A semaphore added only inside the current route body **after `db: DBConn` has already been resolved** can still leave queued requests holding DB pool slots.

Therefore, if admission control is implemented, verify that waiting for capacity happens **before scarce DB checkout**, or refactor DB acquisition so queued requests do not hold a DB connection.

This is a hard design review item for #107.

### Global vs provider-specific

Start with the smallest process-local model justified by measurements.

Per-provider isolation should only be added if the baseline proves provider starvation/monopolization. Note that yfinance already has its own per-process serialization for correctness/rate limiting.

---

## Phase 3 — Same-key request coalescing / single-flight

Only implement if duplicate work remains significant **across services/callers** after measuring it.

The dashboard already coalesces same-key in-flight backfills process-locally, so do not present single-flight as a novel universal fix without measuring other callers.

Candidate data-side key:

```text
(venue, canonical_symbol, timeframe)
```

Questions before implementation:

- Which callers produce duplicates?
- How often do identical refreshes overlap?
- How do different `from_ts` / `to_ts` windows interact?
- Should followers re-check persisted freshness after the leader completes?
- How are leader failure/cancellation propagated?
- Does process-local coordination help enough with two data workers?

Do not introduce Redis/distributed locking without evidence.

---

## Phase 4 — Factor→data HTTP client lifetime

### Objective

Determine whether connection churn materially contributes to #107.

Current factor fetches can create many short-lived `DataClient` / `httpx.AsyncClient` instances, including concurrent macro fetches.

Compare current behavior with a safe reusable transport/client design only if measurements justify it.

Measure:

- p50/p95,
- connection errors,
- total request duration,
- socket/connection churn where practical,
- resource use.

### Security rule

Do not create a global client that permanently stores one user's bearer token.

If reuse is introduced, preserve per-request Authorization isolation.

---

## Phase 5 — Explicit backpressure and caller compatibility

### Objective

If capacity waiting needs a timeout, make overload intentional and machine-readable rather than turning it into transport failure.

Potential result concept:

```json
{
  "code": "DATA_SERVICE_BUSY",
  "message": "backfill capacity temporarily exhausted",
  "details": {"retryable": true}
}
```

HTTP status (`429` vs `503`) must follow project semantics and actual caller behavior.

Before adding any new status, complete this matrix:

| Caller | Refresh semantics | Current non-2xx behavior | Allowed degradation | Change required? |
|---|---|---|---|---|
| factor | current/live freshness-sensitive | verify exact path | must not silently present stale as current | TBD |
| paper | execution/live/backtest varies | refresh error caught in `get_bars` | depends on caller | TBD |
| research | best-effort enrichment | degrades to DB cache | partial/degraded is intentional | TBD |
| dashboard | display best-effort | catches refresh failure | cached display allowed | likely none |
| orchestration | explicit tool/client call | verify | explicit error expected | TBD |

Avoid retry amplification:

```text
overload
→ immediate retries
→ more overload
```

---

## Phase 6 — Live-runner scheduling/throttling

Only touch the live-runner path if data-side fixes do not sufficiently resolve the representative mixed workload.

Possible improvements if evidence supports them:

- jitter/staggered wakeups,
- polling concurrency limit,
- market-hours-aware scheduling,
- priority distinction between interactive/background traffic.

Because `CONTRIBUTING.md` classifies live-runner changes as high-risk/staging work, this should preferably remain a separate follow-up unless #107 cannot be solved without it.

---

## Phase 7 — Validation and regression tests

### Deterministic regression coverage

Potential tests depending on chosen fix:

- [ ] slow connector does not monopolize DB pool unexpectedly
- [ ] DB connection is not held while waiting for admission/provider work, if connection lifetime is changed
- [ ] configured concurrency limit is never exceeded
- [ ] gate releases on success
- [ ] gate releases on exception
- [ ] cancellation does not leak capacity
- [ ] queue timeout/error semantics are correct
- [ ] provider failure semantics are preserved
- [ ] caller freshness behavior remains correct
- [ ] same-key behavior if single-flight is included
- [ ] two independent keys/providers are not accidentally serialized unless intended

Use fake/delayed connectors, not public-provider stress.

### Before/after evidence

Run the same benchmark/topology before and after and record:

| Metric | Baseline | After | Change |
|---|---:|---:|---:|
| `DATA_SERVICE_UNREACHABLE` | TBD | target 0 | TBD |
| success rate | TBD | TBD | TBD |
| intentional backpressure | N/A | TBD | TBD |
| p50 | TBD | TBD | TBD |
| p95 | TBD | TBD | TBD |
| p99 | TBD | TBD | TBD |
| DB pool pressure | TBD | TBD | TBD |
| peak expensive in-flight ops | TBD | TBD | TBD |
| CPU / memory | TBD | TBD | TBD |

---

# 6. Likely files involved

Do not pre-commit to all of these; this is the candidate set.

Initial data-service scope:

```text
services/data/src/inalpha_data/api/backfill.py
services/data/src/inalpha_data/config.py            # only if new settings are needed
services/data/tests/test_backfill_router.py
services/data/tests/test_api.py                     # only if API semantics change
services/data/README.md                             # only if operator-facing config changes
```

Potential factor scope only if caller semantics/pooling require it:

```text
services/factor/src/inalpha_factor/data_client.py
services/factor/src/inalpha_factor/engine.py
services/factor/tests/test_data_client.py
```

Paper/research/dashboard/orchestration should be inspected for compatibility, but should **not** be changed merely because they call backfill.

Protected/shared infrastructure remains untouched unless explicitly agreed.

---

# 7. Proposed PR strategy

Avoid one giant PR.

### PR 1 — smallest proven #107 fix + deterministic regression tests

Target only what baseline evidence requires, likely within `services/data` if possible.

Include in the PR description:

- exact baseline reproduction,
- before/after evidence,
- correctness/freshness checks,
- deterministic regression coverage.

The contributor load/benchmark harness does **not** need to be committed upstream by default. Keep it in our notes/local tooling unless it is small, generally reusable, and the maintainer wants it in the repository.

### Follow-up PRs only if evidence requires them

- caller-side freshness/backpressure semantics,
- cross-service duplicate-work suppression,
- factor HTTP pooling,
- live-runner scheduling.

If PR 1 becomes multi-service or touches live-runner/shared infrastructure, pause and re-align with the maintainer and likely use `staging` according to `CONTRIBUTING.md`.

---

# 8. Risks

### Gate added too late

A semaphore inside the current handler can queue requests **after** they already acquired `DBConn`, leaving pool exhaustion unchanged.

Mitigation: prove acquisition order and ensure waiting occurs before DB checkout, or shorten DB connection lifetime.

### Lower concurrency stabilizes service but destroys latency

Mitigation: sweep values; measure queue wait separately; choose from evidence.

### Queueing only moves the problem

Mitigation: bounded wait, explicit overload semantics, observable wait time.

### Process-local gate is mistaken for global capacity

Mitigation: document worker count and effective aggregate capacity; production currently uses two data workers.

### Shared HTTP client leaks credentials

Mitigation: never bind one user's Authorization token to a cross-user singleton.

### Single-flight serves stale/wrong window data

Mitigation: include window/freshness semantics in design and re-check persisted state after leader completion.

### Benchmark treats HTTP 200/zero bars as success

Mitigation: count refresh progress and provider logs, especially for yfinance; do not conflate issue #74 with #107.

### Load test harms public providers

Mitigation: deterministic delayed/fake connectors first; low-volume real integration only.

---

# 9. Questions for maintainer

Ask only when needed; do not dump all questions at once.

Highest-value questions after baseline or before implementation:

- Does the deployed data service currently match the repository production topology (`WORKERS=2`, single container), or is it different?
- Is `DATA_SERVICE_UNREACHABLE` still observed on the current deployed commit?
- Is there a concrete p95 target / representative concurrency level already used operationally?
- Which provider/workload currently causes the most pain?
- If the fix remains data-service-local, is direct PR → `main` preferred?
- If caller semantics require a factor/paper/live-runner change, should we route through `staging`?

---

# 10. Decision log

### D-001 — Treat #107 as a problem statement, not a literal implementation spec

Current `main` already contains some mitigations added after the issue was opened.

### D-002 — Measure before tuning

No concurrency value will be chosen solely by intuition.

### D-003 — Protect the shared data boundary first

Prefer solving the shared resource/capacity problem before adding more caller retries.

### D-004 — Keep PR 1 small

Single-flight, pooling and live-runner scheduling are follow-ups unless baseline evidence makes them necessary.

### D-005 — Preserve freshness semantics

A reliability fix is invalid if it makes stale data look current.

### D-006 — Admission waiting must not consume the resource it is meant to protect

Do not queue behind a semaphore while already holding `DBConn`. Gate placement / DB connection lifetime must be reviewed together.

### D-007 — Treat process-local limits honestly

With production `WORKERS=2`, a process-local semaphore is not a service-global limit.

### D-008 — Benchmark tooling is contributor evidence by default

Commit focused regression tests upstream; only commit a general load harness if it is clearly useful to the project.

---

# 11. Work log

## 2026-09-16

- [x] Read issue #107 and maintainer request.
- [x] Confirm upstream `main` remains at `ed01be9056776c107ab76a404c328a4fed19f529`.
- [x] Review project documentation, contribution rules, business invariants, tests, CI and security boundaries.
- [x] Create contributor fork and isolated notes/contribution branches.
- [x] Confirm current panel mitigation (`_PANEL_FETCH_CONCURRENCY = 16`, no forced panel backfill).
- [x] Confirm current macro path still uses concurrent FRED gather for live macro factors.
- [x] Confirm `/backfill/bars` holds route-level `DBConn` across provider fetch work.
- [x] Confirm shared DB pool default max is 10 connections per process.
- [x] Confirm production data compose uses two Uvicorn workers.
- [x] Confirm yfinance serializes history fetches per process.
- [x] Confirm dashboard already coalesces same-key backfills process-locally.
- [x] Map major backfill callers and identify different degradation semantics.
- [ ] Maintainer confirms technical direction.
- [ ] Establish runnable environment.
- [ ] Run pre-change data/factor tests.
- [ ] Build deterministic reproduction.
- [ ] Capture baseline.

---

# 12. Immediate next steps

Once the maintainer direction is confirmed:

1. Verify contribution branch still matches upstream SHA.
2. Start the supported stack unchanged.
3. Run existing data/factor tests.
4. Reproduce DB-pool/provider pressure with a delayed fake connector in a single-process diagnostic.
5. Repeat the representative scenario with production-like `data WORKERS=2`.
6. Exercise live factor macro fan-out and mixed runner traffic.
7. Record baseline in `04-baseline-results.md`.
8. Identify the first saturated resource.
9. Write only the chosen design in `05-solution-design.md`.
10. Implement the smallest justified change.
11. Repeat the exact same benchmark/topology.
12. Prepare a focused Draft PR with `Fixes #107` and before/after evidence.

---

## Working principle

> Stabilize by measurement, and never queue while already holding the scarce resource you are trying to protect.
