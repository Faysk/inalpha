# Issue #107 — Factor Target Fail-Closed Guard

**Status:** runtime safety requirement for factor/mixed probes.  
**Purpose:** prevent an otherwise-safe synthetic benchmark from accidentally sending factor-driven load to the ordinary data-service and therefore to real market-data providers.

---

## 1. Safety gap discovered during probe review

The factor macro and mixed probes already validate that the explicitly supplied contributor `--data-url` exposes:

```text
/__issue107/state
```

and that all required venues are fake.

However, factor-service has its own configured:

```text
DATA_SERVICE_URL
```

A contributor could accidentally do this:

```text
fake data wrapper running on :18001
factor started with ordinary DATA_SERVICE_URL=http://localhost:8001
probe given --data-url http://127.0.0.1:18001
```

The probe's direct safety check would pass, but `/score` would make factor call the ordinary data-service on `:8001`.

That is unacceptable for a capacity harness because it could hit real Binance/FRED providers.

---

## 2. Contributor-only factor wrapper

Prepared:

```text
tools/issue107_factor_app.py
```

Materialized location:

```text
services/factor/issue107_factor_app.py
```

Run this app instead of `inalpha_factor.main:app` for factor/mixed #107 benchmarks.

The wrapper changes no factor business behavior. It only adds a safety boundary and non-secret diagnostics.

---

## 3. Startup guard

The wrapper compares:

```text
FactorSettings.data_service_url
```

with:

```text
ISSUE107_EXPECT_DATA_URL
```

whose safe default is:

```text
http://127.0.0.1:18001
```

After trivial trailing-slash normalization, the values must be equal or the process refuses to import/start.

Recommended startup:

### PowerShell

```powershell
$env:DATABASE_URL = $env:ISSUE107_DATABASE_URL
$env:DATA_SERVICE_URL = "http://127.0.0.1:18001"
$env:ISSUE107_EXPECT_DATA_URL = "http://127.0.0.1:18001"
$env:FACTOR_MACRO_ENABLED = "true"
uv run uvicorn issue107_factor_app:app --host 127.0.0.1 --port 18004 --workers 1
```

### Bash / WSL

```bash
DATABASE_URL="$ISSUE107_DATABASE_URL" \
DATA_SERVICE_URL=http://127.0.0.1:18001 \
ISSUE107_EXPECT_DATA_URL=http://127.0.0.1:18001 \
FACTOR_MACRO_ENABLED=true \
uv run uvicorn issue107_factor_app:app \
  --host 127.0.0.1 --port 18004 --workers 1
```

Do not use the ordinary factor app for the capacity probes after this guard was introduced.

---

## 4. Diagnostic endpoint

The wrapper exposes:

```text
GET /__issue107/config
```

with only non-secret information:

```text
pid
data_service_url
expected_data_url
macro_enabled
service_name
```

It also adds:

```text
X-Issue107-Factor-Worker-Pid
```

on responses.

This gives factor-driven probes a future direct way to verify the factor→data target before issuing `/score` load.

---

## 5. Layered safety model

For factor/mixed benchmarks the intended safety chain is now:

```text
data wrapper
→ fake required provider venues

factor wrapper
→ DATA_SERVICE_URL must equal contributor fake data URL

probe
→ verify contributor endpoints/config before workload
```

The first two layers are now prepared. The probes should treat absence of the contributor factor endpoint as an unsafe target rather than assuming the factor process was started correctly.

Until that probe-side check is integrated, the authoritative runbook rule is:

> factor/mixed scenarios must be started with `issue107_factor_app:app`, never the ordinary factor app.

---

## 6. Why this belongs in contributor tooling only

Production Inalpha should not expose internal service URLs merely for this benchmark.

The wrapper exists solely because contributor capacity tests deliberately generate concurrency and therefore need stronger target validation than normal manual development traffic.

Do not upstream:

```text
/__issue107/config
X-Issue107-Factor-Worker-Pid
ISSUE107_EXPECT_DATA_URL
```

as part of the #107 production fix.

---

## Current conclusion

A fake data-service is not enough if the factor process can still point somewhere else.

The benchmark is only safe when both ends of the cross-service path are verified:

```text
probe → factor → intended fake data-service → fake providers
```

This guard turns that routing assumption into an executable startup check.
