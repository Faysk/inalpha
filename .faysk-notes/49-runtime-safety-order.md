# Issue #107 — Runtime Safety Order

**Status:** authoritative safety sequence for local factor/mixed capacity runs.  
**Purpose:** make the benchmark fail closed at every boundary before any synthetic load is generated.

This note supersedes older startup snippets in earlier harness notes where they conflict with the safety sequence below.

---

## 1. Why a three-layer check is necessary

For factor-driven load there are three separate routing decisions:

```text
probe
→ factor-service
→ data-service
→ provider connector
```

It is not enough to verify only one of them.

A fake data-service on `:18001` does not protect us if factor was accidentally started with:

```text
DATA_SERVICE_URL=http://localhost:8001
```

Likewise, a correctly routed factor process does not protect us if the data wrapper forgot to replace one of the venues used by the workload.

Therefore the safety sequence verifies all three boundaries before `/score` or `/backfill/bars` load is allowed.

---

## 2. Step 1 — start the fake data wrapper

Use only:

```text
services/data/issue107_slow_data_app.py
```

For the macro harness:

```text
ISSUE107_FAKE_VENUES=binance,fred
```

For the mixed harness:

```text
ISSUE107_FAKE_VENUES=binance,fred,baostock,yfinance
```

The wrapper exposes:

```text
GET /__issue107/state
```

and the load probes must treat absence of that endpoint as an unsafe target.

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

Do **not** start `inalpha_factor.main:app` directly for factor/mixed capacity scenarios.

The wrapper refuses startup if factor's actual configured data URL differs from the expected contributor target.

It exposes:

```text
GET /__issue107/config
```

with non-secret routing metadata only.

---

## 4. Step 3 — run the no-load target verifier

Before generating any factor-driven capacity load, run from `services/factor`:

### Macro-only scenario

```bash
uv run python issue107_target_check.py \
  --data-url http://127.0.0.1:18001 \
  --factor-url http://127.0.0.1:18004 \
  --required-venues binance,fred \
  --require-macro
```

### Mixed scenario

```bash
uv run python issue107_target_check.py \
  --data-url http://127.0.0.1:18001 \
  --factor-url http://127.0.0.1:18004 \
  --required-venues binance,fred,baostock,yfinance \
  --require-macro
```

This script performs only contributor diagnostic GET requests. It does not call:

```text
/score
/backfill/bars
/bars
```

and does not contact any market-data provider.

Required result:

```text
issue107_target_check=PASS
```

If the checker fails, **do not run the workload**. Fix the local routing/configuration first.

---

## 5. What the verifier checks

It requires:

```text
data /__issue107/state exists
all required venues are listed as fake
factor /__issue107/config exists
factor.data_service_url == the checked data URL
factor.expected_data_url == the checked data URL
macro_enabled == true when --require-macro is used
```

This catches the dangerous split-brain setup:

```text
probe checks fake :18001
but
factor internally calls ordinary :8001
```

before any synthetic concurrency is generated.

---

## 6. Runner-only scenarios

`issue107_runner_poll_probe.py` calls the data-service directly and does not use factor.

Therefore runner-only L/M scenarios do not require the factor wrapper, but they still require the data wrapper to fake every requested venue. The runner probe already refuses to run when required venues are missing from `fake_venues`.

---

## 7. Low-level backfill scenarios

The Stage-D generic load probe calls data directly.

It already fails closed unless:

```text
/__issue107/state is available
AND
binance is fake
```

So the factor wrapper is irrelevant to Stage D/F.

---

## 8. Safety order in one view

For macro/mixed scenarios:

```text
start dedicated benchmark DB
→ verify/reset only inalpha_issue107
→ start issue107_slow_data_app
→ verify fake venues
→ start issue107_factor_app
→ run issue107_target_check.py
→ require PASS
→ only then run macro/mixed load
```

For runner-only scenarios:

```text
start dedicated benchmark DB
→ start issue107_slow_data_app with all runner venues fake
→ runner probe validates fake venues
→ run load
```

For low-level data scenarios:

```text
start dedicated benchmark DB
→ start issue107_slow_data_app with binance fake
→ load probe validates contributor state endpoint + fake Binance
→ run load
```

---

## 9. Production-scope rule

None of these contributor safety endpoints/helpers belongs in the production fix:

```text
/__issue107/state
/__issue107/config
X-Issue107-Worker-Pid
X-Issue107-Factor-Worker-Pid
ISSUE107_EXPECT_DATA_URL
issue107_target_check.py
```

They exist only to make a deliberately concurrent local benchmark safer and reproducible.

---

## Current conclusion

The runtime phase now has an explicit fail-closed routing chain.

The benchmark must prove:

```text
probe → intended factor wrapper → intended fake data wrapper → fake providers
```

before it is allowed to measure capacity. A benchmark result is not useful if we cannot first prove what system it actually exercised.
