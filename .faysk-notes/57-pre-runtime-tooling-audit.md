# Issue #107 — Pre-Runtime Tooling Audit

**Status:** contributor tooling review before the first local execution.  
**Production impact:** none.

This audit reviews the benchmark machinery itself so we do not confuse a harness defect with Inalpha behavior.

---

## 1. Materialization helper hardening

The PowerShell and Bash materialization helpers now keep the existing branch/SHA/clean-tree gates and add syntax-only validation after copying contributor tools into the contribution checkout.

PowerShell path:

```text
materialize untracked diagnostics
→ AST-parse every materialized Python file when `python` is available
→ parse every materialized PowerShell helper with the PowerShell parser
→ only then print the diagnostic working-tree state
```

Bash/WSL path:

```text
materialize untracked diagnostics
→ verify source/destination array lengths
→ AST-parse every materialized Python file when `python` is available
→ `bash -n` every materialized shell helper
→ only then continue
```

These checks do not import project modules and do not generate provider/data-service traffic. They catch syntax/copy corruption only.

---

## 2. Safety responsibilities are layered

No single probe should be treated as the only safety boundary.

The authoritative factor-driven chain remains:

```text
issue107_slow_data_app:app
→ issue107_factor_app:app
→ issue107_target_check.py
→ PASS
→ factor/mixed/sustained load
```

`issue107_factor_app.py` refuses startup when its effective `DATA_SERVICE_URL` differs from the expected contributor fake-data URL.

`issue107_target_check.py` independently verifies:

```text
required venues are fake
required venues are not also blocked
snapshot scheduler isolation is active
factor configured data URL == checked fake-data URL
factor expected data URL == checked fake-data URL
macro is enabled when requested
```

This external no-load check remains mandatory for Stage H, N and O even when individual probes contain their own defensive checks.

---

## 3. Probe-internal guard coverage

### Sustained acceptance

`issue107_sustained_acceptance_probe.py` is the strongest self-contained guard:

- calls the base preflight;
- requires required venues to be fake;
- verifies factor target routing;
- requires macro enabled;
- requires the hardened scheduler-isolation marker;
- rejects a required venue that is reported blocked;
- requires a sufficiently large fake provider batch size.

It is the authoritative O-stage tool.

### Macro and mixed burst probes

`issue107_factor_macro_probe.py` and `issue107_mixed_workload_probe.py` contain data-target fake-venue checks, but their embedded checks are **not a substitute** for `issue107_target_check.py` because the no-load checker is what proves the factor endpoint itself is the fail-closed contributor wrapper pinned to the checked data target.

Therefore:

```text
Stage H / Stage N
→ target checker PASS first
→ only then run probe
```

Do not run those scripts directly against an arbitrary factor URL just because the data URL is fake.

### Runner / low-level data probes

`issue107_runner_poll_probe.py` and `issue107_load_probe.py` do not require factor-service. Their direct data state checks ensure workload venues are fake before load.

The current contributor data wrapper additionally reports:

```text
snapshot_scheduler_forced_disabled=1
blocked_venues=...
fake_venues=...
```

When starting these stages manually, inspect the initial safety/state output and use only the current wrapper from the notes branch. If that marker is absent, stop instead of assuming an older local copy is equivalent.

---

## 4. Sustained helper distinction

There are intentionally two sustained scripts.

### `issue107_sustained_mixed_probe.py`

This is retained as base machinery / same-key-heavy H11 stress infrastructure. It is useful for helper functions and targeted stress, but it is **not** the PR-quality sustained acceptance runner.

Its older settle path is less evidence-preserving under a hard settle timeout than the acceptance tool. Do not use it as the source of final p95 claims.

### `issue107_sustained_acceptance_probe.py`

This is the O-stage authority because it adds:

```text
unique cross-sectional symbol mode by default
missed-slot accounting
pending-cycle accounting
partial evidence preservation
explicit child-task cancellation/draining
one-worker provider/DB counter deltas
```

Final sustained evidence comes from this tool, not the base helper.

---

## 5. Fake-provider shape rechecked against `/backfill/bars`

The contributor fake can return up to 1000 synthetic bars beginning at `since` even when that extends beyond the request `to_ts`.

Current production `/backfill/bars` explicitly filters connector-returned bars to:

```text
bar.ts <= req.to_ts
```

before persistence and advances the cursor from the final retained timestamp.

Therefore the fake's large batch size does not by itself persist future bars outside the requested window. For long windows it also lets the real route exercise its normal cursor/pagination behavior.

This is important because `ISSUE107_FAKE_BARS_PER_FETCH=1000` is intended to remove artificial tiny-batch amplification, not change the route's time-window semantics.

---

## 6. What syntax validation does *not* prove

The new materialization checks intentionally stop at syntax.

They do **not** prove:

```text
imports resolve
project dependencies are installed
service startup succeeds
JWT settings match across services
Timescale migrations are present
runtime schemas still match the probes
provider wrappers install correctly
```

Those are exactly what local Stage A / preflight execution is for.

A syntax-pass is therefore a preparation signal, not runtime evidence.

---

## 7. Freeze remains in force

This audit found no reason to select or apply a production candidate before runtime.

Current state remains:

```text
Candidate A prepared = yes
Candidate A selected = no
Candidate A applied  = no
```

The next production decision still requires measured A–O evidence.

---

## Working-principle checkpoint

The harness is part of the experiment. If a tool can silently point at the wrong service, leave orphan load running, hide a timeout, or change cache/database state between comparisons, its output is not trustworthy.

So the same rule applies to contributor tooling as to production code:

> Prefer a small explicit guard over an assumption that happens to be true on the author's machine.
