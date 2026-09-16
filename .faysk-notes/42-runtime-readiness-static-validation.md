# Issue #107 — Runtime Readiness Static Validation

**Status:** completed static preflight against current reviewed upstream before local execution.  
**Reviewed upstream:** `ed01be9056776c107ab76a404c328a4fed19f529`.

**Purpose:** verify that prepared diagnostics match current schemas, auth rules, test conventions, venue/timeframe support, service startup behavior and benchmark-safety requirements before runtime.

This note does **not** replace execution. It reduces avoidable false negatives and unsafe harness behavior.

---

## 1. Revision state

At this pass:

```text
mirror29/inalpha:main = ed01be9056776c107ab76a404c328a4fed19f529
Faysk/main            = same reviewed baseline
fix/data-service-saturation = identical to Faysk/main
production commits on contribution branch = 0
```

Before execution, fetch fresh `upstream/main` again. If upstream moved, this validation becomes historical and #107-sensitive paths must be re-read before comparing numbers.

---

## 2. Data pytest integration model matches diagnostics

Current data tests use:

```text
pytest-asyncio / asyncio_mode=auto
integration marker
real application lifespan
real shared DB pool
connector registry replacement with fakes
```

That matches the intended model of:

```text
test_backfill_pool_pressure_draft.py
test_candidate_a_regression_draft.py
```

The tests are not creating a completely artificial dependency graph merely to demonstrate H1.

The post-Candidate-A regression additionally patches the constituent scheduler's parsed index list to empty so local root environment state cannot create unrelated background provider work during the property test.

---

## 3. Authentication assumptions

Data-service requires a valid bearer JWT with signature/expiry and `sub`.

The contributor tools generate normal local service-style JWTs using the shared local `JWT_SECRET`. They do not embed secrets in notes/results.

Factor read routes receive the probe token and the normal FactorEngine/DataClient path forwards it to data-service. This exercises current factor→data auth propagation instead of bypassing it.

The factor fail-closed wrapper changes routing verification only; it does not relax production auth behavior.

---

## 4. Factor request/response schemas match probes

Current `/catalog` exposes fields used by macro selection:

```text
factor_id
source
available
```

Current `ScoreRequest` accepts:

```text
venue
symbol
timeframe
as_of
lookback_bars
horizon_bars
quantiles
factor_ids
```

Current `ScoreResponse` exposes:

```text
bars_used
factors
```

The sustained O1 tool can therefore vary symbols across concurrent `/score` requests without violating schema semantics. `symbol` is an ordinary required string and synthetic Binance-format keys are accepted by the fake connector path.

The macro probes intentionally pass explicit macro factor IDs to isolate macro fan-out while retaining the normal instrument-price fetch required by scoring.

---

## 5. Runner venue/timeframe presets are valid

Runner-like workload uses `1h` for:

```text
binance
baostock
yfinance
```

Current `/backfill/bars` routing supports these combinations.

The simulated lookback is short enough not to intentionally trip Baostock's 1h lookback cap or other long-history constraints.

The Japanese examples correctly use `yfinance` symbols such as `7203.T`; the current Baostock connector explicitly says JP routing should use yfinance after the old AkShare Japan path was removed.

Therefore runner requests should reach the fake provider phase rather than fail validation for an invalid venue/timeframe combination.

---

## 6. Fake-provider batch size

`/backfill/bars` advances its cursor from the final provider row and fetches up to 1000 rows per batch.

Long factor windows with a fake that returns only one row would manufacture hundreds of provider loops.

For factor/mixed/sustained work the harness therefore requires:

```text
ISSUE107_FAKE_BARS_PER_FETCH >= 1000
```

The probes fail before load when this condition is not satisfied.

This keeps the benchmark focused on Inalpha concurrency rather than fake-provider pagination artifacts.

---

## 7. Environment loading and dedicated DB

Root/service settings allow process environment variables to override root `.env` values.

The runtime plan uses that to pin:

```text
DATABASE_URL → inalpha_issue107
DATA_SERVICE_URL → contributor fake data target
ISSUE107_EXPECT_DATA_URL → same fake data target
```

The DB reset helpers are hard-coded to `inalpha_issue107` and reset only `public.bars` after verifying the connected DB/table.

A factor restart clears process cache only. DB-cold state still requires the dedicated bars reset.

---

## 8. Important safety gap found: normal data lifespan can run background provider work

Static review of current `data.main` + `scheduler.py` found:

```text
ConstituentSnapshotScheduler.start()
→ when tracked indices exist
→ create _loop()
→ _loop immediately calls _tick()
→ provider-backed constituent catch-up can run before first sleep
```

`CONSTITUENT_SNAPSHOT_INDICES` defaults empty in current DataSettings, so ordinary default dev startup is safe from this scheduler. But a contributor's existing root `.env` could legitimately enable it.

A load harness cannot depend on that accidental local setting.

The contributor `issue107_slow_data_app.py` now sets:

```text
CONSTITUENT_SNAPSHOT_INDICES=""
```

**before importing `inalpha_data.main`**, ensuring settings are constructed with the scheduler disabled.

`/__issue107/state` reports:

```text
snapshot_scheduler_forced_disabled=1
```

and `issue107_target_check.py` requires it before factor/mixed/sustained load.

This is benchmark-only isolation; production scheduler behavior is unchanged.

---

## 9. Provider isolation hardened beyond required fake list

Earlier wrapper logic replaced only venues explicitly named in `ISSUE107_FAKE_VENUES`.

That protected intended requests but left other normally registered OHLCV connectors real.

The wrapper now runs the normal lifespan for real DB/startup fidelity, then rewrites the OHLCV registry:

```text
explicitly requested workload venue
→ SlowIssue107Connector

other registered OHLCV venue
→ BlockedIssue107Connector
→ raises before provider I/O
```

The diagnostic state exposes both:

```text
fake_venues
blocked_venues
```

The target checker refuses a configuration where a required workload venue is missing from fake venues or overlaps the blocked list.

This isolation applies to the OHLCV/backfill connector registry used by #107. It is not a generic sandbox for every unrelated data-service endpoint; benchmark tools remain constrained to documented routes.

---

## 10. Factor→data routing fails closed

A separate safety gap was already fixed: checking fake `--data-url` was insufficient if factor itself still pointed to ordinary `:8001`.

`issue107_factor_app.py` now refuses startup unless:

```text
FactorSettings.data_service_url == ISSUE107_EXPECT_DATA_URL
```

and exposes only non-secret routing metadata at `GET /__issue107/config`.

`issue107_target_check.py` verifies:

```text
data contributor endpoint exists
required fake/blocked state is safe
scheduler isolation active
factor contributor endpoint exists
factor configured URL == checked data URL
factor expected URL == checked data URL
macro enabled where required
```

Only `issue107_target_check=PASS` permits factor-driven load.

---

## 11. Sustained load generator review

The first sustained helper had two limitations:

1. same-key factor requests per cycle were useful H11 stress but not the canonical cross-sectional shape;
2. a delayed open-loop scheduler could catch up old slots close together and create an artificial burst.

The acceptance-oriented tool now uses:

```text
--factor-symbol-mode unique  # default O1
--factor-symbol-mode same    # O2 stress control
```

and never replays a slot missed by at least one whole cycle interval.

It reports separately:

```text
cycles_skipped_pending_cap
cycles_skipped_schedule_lag
cycles_pending_after_settle
cycle_task_errors
```

Material schedule-lag skips are a harness/machine warning, not automatically service capacity evidence.

---

## 12. Sustained moved-bottleneck metrics

The O-stage acceptance probe now captures before/after data state and prints one-worker deltas for:

```text
POST backfill / GET bars counts
provider start/completion/cancel/fail totals
per-venue provider totals
thread started/completed
DB pool requests/queued/wait-ms/errors/usage-ms
```

and samples provider/pool/HTTP in-flight peaks throughout the run.

For two workers, process-local state cannot be treated as service-global. The probe warns on before/after PID mismatch; production-like confirmation uses per-PID evidence plus client-visible latency/errors.

This closes a measurement gap in the moved-bottleneck rule:

```text
DB failures improve
but provider failures increase
→ not automatically success
```

---

## 13. Percentile claim guard

Issue #107 asks for controlled p95 but supplies no numeric p95 threshold.

Static readiness therefore defines only the measurement discipline:

```text
30s smoke
→ stable longer run (e.g. 60s)
→ at least 3 repetitions
→ preserve all repetitions
→ separate percentiles by operation
```

Do not invent a numeric SLO in the PR.

D/N short samples can report observed latency but do not support a strong sustained p95 claim.

---

## 14. Candidate A static revalidation

Current main still declares route-level:

```text
backfill_bars(..., db: DBConn, ...)
```

and the route uses that same lease for `latest_bar_ts`, external provider waits and `insert_bars` batches.

Shared infrastructure already exposes public `get_conn()`; no `_shared` code change is needed for Candidate A.

`insert_bars()` explicitly commits each batch, so current backfill is not one route-wide atomic transaction. Narrowing DB leases would preserve the existing per-batch durability boundary.

Existing backfill integration tests start the real lifespan/shared pool and replace registry connectors, so explicit `get_conn()` inside the route remains structurally compatible with test wiring.

The post-fix regression has been hardened to disable the constituent scheduler and test the property with pool=2/four blocked provider requests.

Full reasoning is in `53-candidate-a-current-main-revalidation.md`.

Candidate A remains **unselected** until H1 is reproduced and material under representative workload.

---

## 15. Same-key overlap / correctness guard remains open

Current persistence uses unconditional `ON CONFLICT ... DO UPDATE`.

Concurrent same-key backfills can already fetch overlapping windows; Candidate A could make concurrent provider access more frequent by removing DB capacity as an accidental gate.

If H4 shows material same-key overlap, run deterministic completion-inversion correctness evidence before deciding whether single-flight/coalescing is necessary.

If overlap is immaterial, keep PR1 focused.

Do not preemptively add a generic lock.

---

## 16. Two-worker Baostock caveat

Production data compose uses two workers, while current Baostock source documents caveats around persistent Baostock login/session state and process/fork behavior. Its A-share market fetch path also has process-local source throttling.

Our fake two-worker benchmark is valid for data-service process/pool/request-capacity confirmation, but it does **not** prove real Baostock provider session correctness at two workers.

Do not turn fake-provider capacity evidence into a claim about real provider fork safety.

---

## 17. What is now statically ready

Checked/prepared:

```text
branch/SHA isolation
data/factor test wiring
auth/JWT propagation
factor catalog/score schema
runner venue/timeframe presets
fake batch semantics
root/service env precedence
dedicated benchmark DB/reset safety
startup constituent scheduler isolation
unexpected OHLCV venue blocking
factor→data fail-closed routing
no-load target checker
short H1/H8/H9/H10/H11 diagnostics
macro/runner/mixed workloads
O1/O2 sustained workload shape
open-loop missed-slot handling
provider/DB moved-bottleneck counters
Candidate A current-main compatibility
```

Still intentionally unproven until contributor runtime:

```text
H1   provider wait materially starves DB capacity?
H1b  does that become caller timeout/retry/DATA_SERVICE_UNREACHABLE?
H6   does runner alignment materially amplify pressure?
H8   is macro same-key cold duplication material end-to-end?
H9   does timed-out client work overlap retries?
H10  does thread-backed provider work become a first constraint?
H11  is whole-score cold stampede material end-to-end?
H4   is same-key duplicate refresh material enough for capacity/correctness?
O1   does representative sustained mixed load reproduce the issue?
```

That is the intended static stopping point: further production design without runtime numbers would be speculation rather than progress.
