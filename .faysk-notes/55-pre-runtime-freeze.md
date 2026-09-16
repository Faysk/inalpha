# Issue #107 — Pre-Runtime Freeze

**Status:** static preparation frozen pending contributor-machine execution.  
**Production impact:** none.

---

## 1. Why freeze now

The investigation has reached the point where additional static solution design is more likely to add noise than evidence.

We now have enough material to execute the issue safely and reproducibly:

```text
project/architecture rules understood
→ current #107 paths mapped
→ hypotheses separated from facts
→ fake-provider/runtime safety hardened
→ dedicated benchmark DB/reset discipline prepared
→ short mechanism diagnostics prepared
→ mixed burst reproduction prepared
→ sustained representative acceptance prepared
→ Candidate A reviewed but intentionally unapplied
```

The next useful information must come from runtime measurements.

---

## 2. Cross-document consistency check

At freeze time the authoritative runtime documents agree on the same flow:

```text
11-local-test-runbook.md
44-runtime-execution-manifest.md
49-runtime-safety-order.md
50-sustained-load-acceptance.md
51-sustained-results-template.md
```

The execution sequence is:

```text
A    untouched repository checks
B    H8/H11 structural diagnostics
C    deterministic H1 pool=2 proof
D    one-worker real-TCP capacity transition
E    PostgreSQL + Psycopg pool evidence
F    H9/H10 cancellation/thread persistence
G    two-data-worker confirmation
H-K  factor macro single/same/unique/warm
L-M  runner aligned/staggered
N    mixed M1/M2/M3 burst reproduction
O1   sustained cross-sectional acceptance
O2   sustained same-key stress control
O3   optional runner stagger control
→ baseline decision record
→ choose one smallest production intervention or none
```

Short transition probes may report observed latency but are not the final p95 evidence. O1 is the primary sustained issue-level workload.

---

## 3. Runtime safety chain frozen

Before factor/mixed/sustained load:

```text
dedicated DB = inalpha_issue107
→ contributor data wrapper
→ startup constituent scheduler forced disabled
→ every intended workload OHLCV venue is fake
→ other registered OHLCV venues are fail-closed blocked
→ contributor factor wrapper pinned to fake data URL
→ issue107_target_check.py
→ PASS
→ only then generate load
```

The benchmark must not contact real market-data providers under load.

The acceptance harness also explicitly cancels and drains its spawned local request tasks before final state sampling, so settle-timeout evidence is not knowingly contaminated by orphan load-generator work.

---

## 4. Materialization consistency

The PowerShell/Bash preflight helpers materialize the baseline/runtime diagnostics required by the runbook as **untracked** files.

They intentionally do not materialize:

```text
candidate_a_narrow_db_lease.patch
test_candidate_a_regression_draft.py
```

Those remain behind the baseline decision gate.

This preserves a clean distinction:

```text
baseline tooling
!=
expected production fix
```

---

## 5. Candidate A status at freeze

Candidate A remains the strongest prepared hypothesis if H1 is measured, because current `/backfill/bars` retains a route-level DB lease across provider I/O and the project already contains a DB→HTTP→DB resource-ordering precedent elsewhere.

But the freeze state is deliberately:

```text
prepared = yes
selected = no
applied = no
```

Runtime can still reject Candidate A.

If H1 is not material, do not force it merely because the patch is ready.

---

## 6. Production branch gate

The contribution branch must remain identical to fresh upstream before baseline execution.

Expected pre-baseline state:

```text
fix/data-service-saturation
HEAD == upstream/main
no production commits
no tracked contributor diagnostics
```

If upstream moves, this freeze is invalidated for sensitive paths and those paths must be re-reviewed before executing/comparing results.

---

## 7. What can unfreeze static work

Do not continue adding speculative candidate architecture before runtime.

Static/tooling work may resume before the baseline only if one of these occurs:

1. upstream `main` changes in a #107-sensitive path;
2. a concrete defect/inconsistency is found in the benchmark harness or runbook;
3. the maintainer changes the requested scope/constraints;
4. local preflight reveals an environment incompatibility that prevents executing the documented experiment safely.

Otherwise, the next action is execution.

---

## 8. Evidence needed to leave the baseline gate

Before selecting production code, record enough evidence to answer:

```text
What resource degrades first?
Does that degradation connect to DATA_SERVICE_UNREACHABLE / observed slowness?
Does DB-backed health degrade while DB-free OpenAPI remains responsive?
Does provider pressure rise before or after DB pressure?
Do timeouts leave older work active?
Are H6/H8/H11 materially amplifying the representative workload?
Does O1 reproduce sustained failure/backlog with useful p95 samples?
Which hypotheses received negative evidence?
```

Only then choose the smallest intervention.

---

## Working-principle checkpoint

The static phase closes with the same rule used throughout the contribution:

> Resolve #107 without moving the failure to another resource, weakening freshness, changing unrelated contracts, or making the measurement system itself the source of the result.

At this point, restraint is part of the engineering work: **measure next; do not pre-optimize the answer.**
