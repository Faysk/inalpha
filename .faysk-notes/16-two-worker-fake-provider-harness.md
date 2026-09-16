# Issue #107 — Two-Worker Fake-Provider Harness

**Purpose:** reproduce #107's capacity shape against a real Uvicorn process model without stress-testing any external market-data provider.

This harness is contributor-only and must not be merged into the upstream PR as-is.

---

## 1. Why add this after the in-process pytest diagnostic

The 9-vs-10 pytest diagnostic proves one narrow mechanism in a single process:

```text
route-scoped DBConn + blocked provider I/O → DB pool starvation
```

Production compose, however, runs `data` with two Uvicorn workers.

The second harness adds:

```text
real TCP/HTTP
real Uvicorn worker distribution
real per-worker DB pools
real request middleware / trace ids
fake slow provider
```

while still avoiding Yahoo, FRED, Binance, Alpaca, or Baostock network traffic.

---

## 2. Files

From the notes branch:

```text
.faysk-notes/tools/issue107_slow_data_app.py
.faysk-notes/tools/issue107_load_probe.py
```

The first wraps the normal data-service app and swaps the `binance` connector *after normal lifespan startup* with a fake connector that does only:

```text
asyncio.sleep(delay)
→ return one deterministic OHLCV bar
```

The second sends concurrent unique-symbol backfills and probes `/health` while the fake provider calls are sleeping.

---

## 3. Copy without merging notes

From repository root, while still on `fix/data-service-saturation`:

```bash
git fetch origin notes/issue-107

git show origin/notes/issue-107:.faysk-notes/tools/issue107_slow_data_app.py \
  > services/data/issue107_slow_data_app.py

git show origin/notes/issue-107:.faysk-notes/tools/issue107_load_probe.py \
  > services/data/issue107_load_probe.py

git status --short
```

Expected temporary untracked files:

```text
?? services/data/issue107_load_probe.py
?? services/data/issue107_slow_data_app.py
```

Do not `git add` them.

---

## 4. Start the fake data service — one worker first

Ensure local Postgres + migrations are ready and the root `.env` exists.

From `services/data`:

```bash
ISSUE107_PROVIDER_DELAY_S=5 \
uv run uvicorn issue107_slow_data_app:app \
  --host 127.0.0.1 \
  --port 18001 \
  --workers 1
```

Windows PowerShell equivalent:

```powershell
$env:ISSUE107_PROVIDER_DELAY_S = "5"
uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 1
```

The wrapper uses the normal data-service DB/config/lifespan, but backfill requests for venue `binance` are handled by the local fake connector.

Watch logs for:

```text
issue107_fake_provider_installed pid=...
issue107_fake_provider_start pid=...
issue107_fake_provider_done pid=...
```

---

## 5. One-worker pressure probe

In a second terminal, from `services/data`:

```bash
uv run python issue107_load_probe.py \
  --base-url http://127.0.0.1:18001 \
  --backfills 20 \
  --health-probes 10 \
  --health-timeout 1.0
```

Suggested first one-worker expectations on unmodified code:

```text
first ~10 backfills reach fake provider and retain DB connections
remaining requests queue for DB pool capacity
health probes frequently time out / slow while all 10 slots are retained
```

Exact timing is evidence, not an assertion.

---

## 6. Production-like two-worker run

Stop the one-worker Uvicorn process and restart:

```bash
ISSUE107_PROVIDER_DELAY_S=5 \
uv run uvicorn issue107_slow_data_app:app \
  --host 127.0.0.1 \
  --port 18001 \
  --workers 2
```

PowerShell:

```powershell
$env:ISSUE107_PROVIDER_DELAY_S = "5"
uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 2
```

Then:

```bash
uv run python issue107_load_probe.py \
  --base-url http://127.0.0.1:18001 \
  --backfills 40 \
  --health-probes 12 \
  --health-timeout 1.0
```

Why 40?

```text
2 workers × 10 DB connections = ~20 active DB leases maximum
40 unique blocked backfills gives enough pressure to saturate both workers even if request
acceptance is not perfectly balanced.
```

This is local fake traffic, not external provider load.

---

## 7. What the probe records

It deliberately preserves concrete transport exception types:

```text
ReadTimeout
ConnectTimeout
ConnectError
PoolTimeout
...
```

instead of mapping all transport problems to `DATA_SERVICE_UNREACHABLE`.

It prints:

```text
status counts
HTTPX exception-type counts
upstream machine-code counts
p50 / p95 / p99 / max latency
successful backfills with actual rows fetched
```

Every request also receives an explicit `X-Trace-Id`:

```text
issue107-bf-...
issue107-health-...
```

so request logs can be correlated with the load generator.

---

## 8. Important client-side control

The probe explicitly configures an HTTPX client connection limit larger than the generated concurrency.

This is important because otherwise we could accidentally reproduce:

```text
load-generator HTTP connection pool starvation
```

instead of:

```text
data-service capacity starvation
```

Always verify that the test client itself is not the bottleneck.

---

## 9. Before/after use with Candidate A

If the single-process diagnostic confirms H1 and Candidate A is selected, run this exact two-worker scenario:

```text
BEFORE candidate A
same fake delay
same worker count
same backfill count
same health probe settings

AFTER candidate A
same everything
```

Expected mechanism if Candidate A works:

### before

```text
provider-sleeping requests retain DB pool capacity
→ health/read traffic waits
```

### after

```text
provider-sleeping requests release DB pool after short lookup
→ many provider calls can remain in flight
→ DB-only health/read traffic stays responsive
```

The provider delay itself should remain ~5 seconds. We are not trying to make the fake provider faster; we are trying to prevent its latency from monopolizing unrelated DB capacity.

---

## 10. Worker distribution evidence

The fake connector logs process PID on every provider start/done.

Save those logs.

They let us answer:

```text
Were requests distributed across both workers?
Did one worker receive a disproportionate share?
Did health probes correlate with a worker whose local DB pool was full?
```

Do not assume a perfect 50/50 split in analysis.

---

## 11. Cleanup

Stop Uvicorn, then from repository root:

```bash
rm services/data/issue107_slow_data_app.py
rm services/data/issue107_load_probe.py
git status --short
```

PowerShell:

```powershell
Remove-Item services/data/issue107_slow_data_app.py
Remove-Item services/data/issue107_load_probe.py
git status --short
```

Contribution branch should return to clean state.

---

## 12. Limitations

This harness proves capacity/resource behavior, not full provider realism.

It does not model:

- Yahoo's process-local serialization exactly;
- FRED response-size/network behavior;
- external rate limits;
- factor HTTP-client churn;
- actual live-runner scheduling;
- real market-data freshness.

That is intentional.

The sequence is:

```text
first isolate DB/resource coupling deterministically
→ then add real current caller patterns at low/safe load
```

---

## Success criterion for this harness

The harness is useful if it can answer this narrow question reproducibly:

> Does slow external backfill work prevent unrelated DB-backed data-service requests from receiving capacity, and does the chosen fix remove that coupling under both one-worker and two-worker topology?
