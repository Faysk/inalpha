# Issue #107 — Provider Isolation and Sustained-Soak Hardening

**Status:** contributor-harness correction before runtime execution.  
**Scope:** local diagnostics only; no production fix selected.

---

## 1. Why this review was necessary

The contributor benchmark deliberately generates concurrency. A harness that accidentally reaches a real market-data provider would be worse than having no benchmark at all.

Static review found two remaining ways the local test setup could mislead or create unintended traffic:

1. `issue107_slow_data_app.py` reused the normal data-service lifespan, whose constituent snapshot scheduler can run a catch-up tick immediately at startup when `CONSTITUENT_SNAPSHOT_INDICES` is configured.
2. The first sustained soak scheduler could catch up missed timing slots by injecting them close together, turning scheduler lag into an unintended burst. It also did not print before/after provider failure/cancellation deltas even though the results template expects moved-bottleneck evidence.

Both are contributor-tooling problems, not claims about the production root cause.

---

## 2. Production behavior that motivated the scheduler guard

Current data-service startup constructs and starts `ConstituentSnapshotScheduler` from `CONSTITUENT_SNAPSHOT_INDICES`.

The scheduler is disabled when that list is empty, but when configured its loop deliberately performs a catch-up `_tick()` before its first sleep.

That is correct production behavior. It is undesirable inside a controlled #107 benchmark because a contributor's ordinary root `.env` could contain tracked indices and create unrelated Baostock/provider traffic while the benchmark is supposed to use only local fakes.

Therefore the contributor wrapper now sets:

```text
CONSTITUENT_SNAPSHOT_INDICES=""
```

**before importing `inalpha_data.main`**, because the data module constructs its settings at import time.

The diagnostic state exposes:

```text
snapshot_scheduler_forced_disabled=1
```

and the no-load target checker requires it before factor/mixed load.

This does not propose changing the production scheduler.

---

## 3. Fail closed for unexpected OHLCV venues

Previously the wrapper replaced only the venues named in:

```text
ISSUE107_FAKE_VENUES
```

That protected the intended path but left other normally registered OHLCV connectors real.

The wrapper now changes the local connector registry after normal startup as follows:

```text
venue explicitly listed as fake
→ SlowIssue107Connector

other venue already registered in the OHLCV registry
→ BlockedIssue107Connector
```

The blocking connector raises before provider I/O.

The state endpoint now reports:

```text
fake_venues
blocked_venues
```

The target checker verifies that required workload venues are fake and not blocked.

This is defense in depth. The benchmark still must declare every venue it intentionally exercises as fake.

### Important boundary

This registry isolation is specifically for the OHLCV/backfill connector registry used by the #107 workload. It is not a generic claim that every possible data-service endpoint has been sandboxed.

The benchmark tools intentionally call only their documented data/factor routes.

---

## 4. Sustained scheduler: do not catch up missed slots

A capacity test should distinguish:

```text
service backlog
```

from:

```text
benchmark event-loop scheduling lag
```

If the harness is delayed by at least one whole `cycle_interval`, replaying old schedule slots immediately would create a synthetic burst that was not part of the requested open-loop workload.

The acceptance probe therefore now records two independent skip signals:

```text
cycles_skipped_pending_cap
cycles_skipped_schedule_lag
```

Rules:

- pending-cap skip = service/harness backlog reached the bounded in-flight cycle cap;
- schedule-lag skip = the generator itself missed an offered-load slot by at least one full interval;
- neither counts as successful throughput;
- missed slots are not replayed later.

If `cycles_skipped_schedule_lag` is material, the run is suspect as capacity evidence and the local machine/harness must be reviewed before attributing the result to Inalpha.

---

## 5. Sustained provider/moved-bottleneck evidence

The acceptance probe now captures data state immediately before and after the run and prints process-local deltas for:

```text
POST /backfill/bars total
GET /bars total
provider started/completed/cancelled/failed
per-venue started/completed/cancelled/failed
thread started/completed
pool requests / queued / wait-ms / errors / usage-ms
```

For `data workers=1`, these are exact for the one data worker.

For `data workers=2`, a before-state request and an after-state request can be served by different workers. If PIDs differ, the probe explicitly warns that exact deltas are invalid. Production-like two-worker confirmation must use per-PID logs/state sampling plus client-visible latency/errors rather than pretending process-local counters are container-global.

---

## 6. p95 acceptance wording

Issue #107 requests controlled p95 latency but does not provide an absolute numeric p95 target.

Therefore the contributor plan must not invent an SLO and attribute it to the project.

Until a maintainer supplies a numeric target, the evidence wording is:

```text
measured p95 under the documented workload/topology
+ before/after comparison
+ zero/changed transport failure counts
+ backlog/provider/DB evidence
```

not:

```text
p95 passed project SLO X
```

unless such an SLO is later explicitly established.

---

## 7. Updated safety chain

For factor/mixed/sustained scenarios:

```text
dedicated inalpha_issue107 DB
→ data wrapper forces constituent scheduler off
→ requested OHLCV venues become deterministic fakes
→ every other registered OHLCV venue becomes fail-closed
→ factor wrapper pins DATA_SERVICE_URL to contributor data target
→ no-load target checker verifies routing + scheduler isolation + fake venues
→ PASS
→ only then generate load
```

This is intentionally stricter than normal development startup because the test is intentionally concurrent.

---

## 8. Working-principle check

This hardening follows the contribution rules already recorded in `09-working-principles.md`:

```text
What evidence do we have?
Which invariant could this break?
Is there a smaller change that solves the same measured problem?
```

The changes here do not alter production behavior or select Candidate A/B/C/D. They only make the evidence-gathering phase safer and less likely to manufacture the wrong conclusion.
