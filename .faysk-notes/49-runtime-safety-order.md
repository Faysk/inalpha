# Issue #107 — Runtime Safety Order

**Status:** authoritative safety sequence for local factor/mixed/sustained capacity runs.  
**Purpose:** make the benchmark fail closed at every boundary before synthetic load is generated.

This note supersedes older startup snippets in earlier harness notes where they conflict with the safety sequence below.

---

## 1. Why layered checks are necessary

For factor-driven load there are several independent boundaries:

```text
probe
→ factor-service
→ data-service
→ OHLCV connector registry
→ provider
```

There is also data-service background startup behavior that can generate provider traffic independently of the probe.

It is not enough to verify only one boundary.

A fake data-service on `:18001` does not protect us if factor was accidentally started with:

```text
DATA_SERVICE_URL=http://localhost:8001
```

Likewise, correctly routed factor does not protect us if a required venue is still real or an ordinary contributor `.env` enables the startup constituent snapshot scheduler.

Therefore the contributor harness verifies routing and also hardens the data target itself.

---

## 2. Step 1 — start the hardened fake data wrapper

Use only:

```text
services/data/issue107_slow_data_app.py
```

For macro:

```text
ISSUE107_FAKE_VENUES=binance,fred
```

For mixed/sustained:

```text
ISSUE107_FAKE_VENUES=binance,fred,baostock,yfinance
```

Before importing the real data app, the wrapper forces:

```text
CONSTITUENT_SNAPSHOT_INDICES=""
```

so the production scheduler's startup catch-up tick cannot create unrelated real provider traffic from local `.env` state.

After normal startup:

```text
requested OHLCV venues
→ SlowIssue107Connector

other already-registered OHLCV venues
→ BlockedIssue107Connector
→ raises before provider I/O
```

The wrapper exposes:

```text
GET /__issue107/state
```

including:

```text
fake_venues
blocked_venues
snapshot_scheduler_forced_disabled
worker pid
provider counters
HTTP counters
pool stats
```

Absence of that endpoint is an unsafe target.

This registry isolation covers the OHLCV/backfill registry exercised by #107. It is not a claim that every unrelated data-service endpoint has been sandboxed; the benchmark tools must call only their documented routes.

---

## 3. Step 2 — start factor through the fail-closed wrapper

Use only:

```text
services/factor/issue107_factor_app.py
```

with:

```text
DATA_SERVICE_URL=http://127.0.0.1:18001
ISSUE107_EXPECT_DATA_URL=http://127.0.0.1:18001
```

Do **not** start `inalpha_factor.main:app` directly for factor/mixed/sustained capacity scenarios.

The wrapper refuses startup when factor's configured data URL differs from the expected contributor target.

It exposes:

```text
GET /__issue107/config
```

with non-secret routing metadata only.

---

## 4. Step 3 — run the no-load target verifier

The same checker now supports both factor-driven and data-only scenarios.

### Macro-only

From `services/factor`:

```bash
uv run python issue107_target_check.py \
  --data-url http://127.0.0.1:18001 \
  --factor-url http://127.0.0.1:18004 \
  --required-venues binance,fred \
  --min-fake-bars-per-fetch 1000 \
  --require-macro
```

### Mixed / sustained

```bash
uv run python issue107_target_check.py \
  --data-url http://127.0.0.1:18001 \
  --factor-url http://127.0.0.1:18004 \
  --required-venues binance,fred,baostock,yfinance \
  --min-fake-bars-per-fetch 1000 \
  --require-macro
```

### Runner-only

Factor-service is not required:

```bash
uv run python issue107_target_check.py \
  --data-url http://127.0.0.1:18001 \
  --required-venues binance,baostock,yfinance \
  --min-fake-bars-per-fetch 1000 \
  --data-only
```

### Low-level backfill

```bash
uv run python issue107_target_check.py \
  --data-url http://127.0.0.1:18001 \
  --required-venues binance \
  --data-only
```

The checker performs only contributor diagnostic GETs. It does not call:

```text
/score
/backfill/bars
/bars
```

Required result:

```text
issue107_target_check=PASS
```

If it fails, do not run load.

---

## 5. What the verifier checks

Data-side checks always require:

```text
data /__issue107/state exists
at least one required workload venue is supplied
all required workload venues are fake
no required workload venue is reported blocked
snapshot scheduler is forced disabled
fake batch size meets --min-fake-bars-per-fetch when requested
```

Factor-driven mode additionally requires:

```text
factor /__issue107/config exists
factor.data_service_url == checked data URL
factor.expected_data_url == checked data URL
macro_enabled == true when --require-macro is used
```

This catches both:

```text
probe checks fake :18001
but factor internally calls ordinary :8001
```

and:

```text
factor/data routing is correct
but local data startup/background config could still escape to a real provider
```

before synthetic concurrency is generated.

`--data-only` deliberately skips factor lookup only after all data-side isolation checks pass.

---

## 6. Sustained acceptance adds its own duplicate guard

`issue107_sustained_acceptance_probe.py` still assumes the no-load target checker was run first, but it independently refuses load if:

```text
snapshot scheduler isolation is absent
or
a required workload venue is blocked instead of fake
```

Its base preflight also verifies factor routing and macro state.

This is defense in depth, not a replacement for the explicit pre-run target checker.

---

## 7. Runner-only scenarios

`issue107_runner_poll_probe.py` calls data directly and does not use factor.

Runner-only scenarios do not require the factor wrapper, but they must use the hardened data wrapper and fake every requested runner venue.

Before load, run the target checker in `--data-only` mode. This proves the current wrapper's scheduler-isolation marker and fake/blocked venue state without requiring factor-service.

Do not run the probe against ordinary `inalpha_data.main:app` merely because the script itself checks venue names; the hardened wrapper also prevents background scheduler leakage and blocks unexpected OHLCV venues.

---

## 8. Low-level backfill scenarios

The generic low-level load probe calls data directly.

Before load, run the same checker with:

```text
--required-venues binance --data-only
```

The low-level probe still has its own embedded fake-Binance check; the explicit no-load verifier is the authoritative pre-run gate because it also checks scheduler isolation and blocked/fake consistency.

Factor wrapper is irrelevant to these low-level scenarios.

---

## 9. Safety order in one view

For macro/mixed/sustained scenarios:

```text
start dedicated benchmark DB
→ verify/reset only inalpha_issue107
→ start hardened issue107_slow_data_app
→ scheduler forced off
→ requested venues fake / other OHLCV registry venues blocked
→ start issue107_factor_app
→ run issue107_target_check.py
→ require PASS
→ only then run workload
```

For runner-only:

```text
dedicated benchmark DB
→ hardened issue107_slow_data_app with all runner venues fake
→ issue107_target_check.py --data-only
→ require PASS
→ run workload
```

For low-level data:

```text
dedicated benchmark DB
→ hardened issue107_slow_data_app with binance fake
→ issue107_target_check.py --required-venues binance --data-only
→ require PASS
→ run workload
```

---

## 10. Production-scope rule

None of this contributor benchmark hardening belongs in the production fix as-is:

```text
/__issue107/state
/__issue107/config
X-Issue107-Worker-Pid
X-Issue107-Factor-Worker-Pid
ISSUE107_EXPECT_DATA_URL
BlockedIssue107Connector
forced benchmark-only scheduler disable
issue107_target_check.py
```

These exist only to make deliberate local concurrency safe and reproducible.

---

## Current conclusion

The benchmark must establish this path before it is allowed to measure capacity:

```text
probe
→ intended factor wrapper (when used)
→ intended hardened fake data wrapper
→ required deterministic fake connectors
→ no startup scheduler provider traffic
→ unexpected OHLCV venues fail closed
```

A benchmark result is not useful if we cannot first prove what system it exercised or if the measurement itself can escape to real providers.

See `52-provider-isolation-and-soak-hardening.md` and `57-pre-runtime-tooling-audit.md` for the static reviews behind these guards.
