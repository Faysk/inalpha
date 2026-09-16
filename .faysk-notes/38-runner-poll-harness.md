# Issue #107 — Live-Runner Poll Alignment Harness

**Status:** prepared contributor diagnostic; no production behavior changed.

**Purpose:** reproduce the current live-runner data traffic shape and measure whether synchronized polls materially increase data-service pressure.

---

## 1. Current production path being reproduced

`LiveRunnerManager._fetch_latest_bar()` currently creates a short-lived paper `DataClient` and calls:

```text
get_bars(... fresh=True, limit=5)
```

Paper `DataClient.get_bars(fresh=True)` performs:

```text
POST /backfill/bars      # best effort
→ GET /bars              # actual read
```

The live runner therefore contributes two data-service requests per fresh poll under the ordinary successful path.

Its lookback is:

```text
max(timeframe_seconds * 5, 7200)
```

and the returned bars are filtered to the latest closed bar before the strategy sees them.

This diagnostic intentionally reproduces only the network/freshness part of that path. It does **not** execute strategy code, risk checks, orders or fills.

---

## 2. Why synchronization is a real hypothesis

Each running strategy owns an independent asyncio task.

After a successful iteration the current loop does:

```text
await asyncio.sleep(poll_s)
```

with no per-run jitter.

On paper-service startup, persisted running rows are read and `manager.start(run)` is called for each. `start()` creates a task immediately, so several resumed runs can begin close together and remain approximately phase-aligned when they share a poll interval.

That makes the original #107 suggestion to stagger live-runner work testable, but not yet proven necessary.

We call this **H6**:

```text
aligned runner polls
→ concentrated fresh backfill/read burst
→ greater DB/provider pressure than the same request count spread over a short interval
```

---

## 3. Tool

```text
.faysk-notes/tools/issue107_runner_poll_probe.py
```

The default workload family mirrors the issue description:

```text
BTC/USDT
BNB/USDT
A-share
Japan / yfinance
+ additional crypto/A-share/JP keys
```

All requested venues must be replaced by the contributor fake data wrapper before the probe starts.

The probe refuses to run if a requested venue is not fake.

---

## 4. Important fake-provider fidelity rule

Do **not** run this probe with the fake wrapper default of one returned bar per provider call.

The real connectors normally return batches. A one-bar fake would turn the five-bar live lookback into several artificial provider calls and exaggerate pressure.

Use:

```text
ISSUE107_FAKE_BARS_PER_FETCH=1000
```

The probe enforces at least 10 synthetic bars per provider call and recommends 1000.

---

## 5. Exact one-worker experiment

First use one data worker because process-local provider/pool counters are then exact.

Example data wrapper:

```bash
ISSUE107_FAKE_VENUES=binance,baostock,yfinance \
ISSUE107_FAKE_BARS_PER_FETCH=1000 \
ISSUE107_PROVIDER_MODE=async \
ISSUE107_PROVIDER_DELAY_S=0.5 \
uv run uvicorn issue107_slow_data_app:app \
  --host 127.0.0.1 --port 18001 --workers 1
```

Aligned run:

```bash
uv run python issue107_runner_poll_probe.py \
  --data-url http://127.0.0.1:18001 \
  --runs 8 \
  --rounds 1 \
  --stagger-ms 0
```

Controlled stagger:

```bash
uv run python issue107_runner_poll_probe.py \
  --data-url http://127.0.0.1:18001 \
  --runs 8 \
  --rounds 1 \
  --stagger-ms 100
```

Then repeat with the exact same fake delay, DB state and run count.

A second useful stagger is 250 ms if 100 ms produces an ambiguous result.

---

## 6. What the probe records

Per simulated run:

```text
backfill HTTP status / transport exception / machine code
bars HTTP status / transport exception / machine code
bars returned
end-to-end poll latency
```

Data-wrapper cumulative deltas:

```text
POST /backfill/bars count
GET /bars count
provider calls total
provider calls by venue
DB pool request count
DB queue count
DB wait milliseconds
DB pool errors
DB usage milliseconds
```

While the wave is running it also samples the DB-free wrapper state endpoint and records peak/current values such as:

```text
provider active max
provider active max per venue
POST /backfill/bars in-flight max
GET /bars in-flight max
pool requests waiting max
pool available min
thread active max
```

This is stronger than inferring peak pressure only from final counters.

---

## 7. Isolation limits

The generic fake connector deliberately **does not** reproduce provider-specific locks such as the real yfinance serialization rule.

That is intentional for H6:

```text
constant provider behavior
+ same total caller work
+ only change request alignment
```

If alignment is material under this controlled provider, we can later test provider-specific interaction separately.

Do not interpret this harness as a yfinance-specific throughput benchmark.

---

## 8. Interpretation matrix

### Strong H6 signal

```text
stagger=0:
  materially higher pool waiting / lower available capacity / worse p95 / errors

same workload with small stagger:
  materially lower peak pressure and better latency/error behavior
```

Then runner staggering remains a plausible secondary intervention.

### Weak/no H6 signal

```text
aligned and staggered runs behave similarly
```

Do not modify live-runner scheduling for #107 unless a more representative mixed workload contradicts this result.

### Candidate A removes both cases

If current main fails both aligned/staggered while Candidate A makes both healthy, then the runner schedule may only be a trigger exposing the data-service DB lifetime flaw.

In that case keep the first PR focused on Candidate A.

---

## 9. Two-worker confirmation

After the deterministic one-worker experiment, rerun with data `--workers 2`, matching repository production topology.

Caveat:

```text
/__issue107/state
```

is process-local. One request can sample worker A and the next worker B.

For two-worker runs:

- use response PID headers and server logs;
- do not sum/compare state deltas as though they came from one global counter;
- the primary output becomes external latency/error behavior plus per-PID evidence.

---

## 10. Later integration scenario

This harness is not the complete paper-service restart path.

Real resume additionally does:

```text
concurrent _build_session()
→ fresh warmup bars
→ capture_factor_baseline()
→ first live poll
```

`29-runner-resume-factor-burst-shape.md` documents the baseline/factor conditions.

The next higher-fidelity step is a mixed factor + runner workload against the same fake data wrapper, before deciding whether we need an actual seeded paper restart integration test.
