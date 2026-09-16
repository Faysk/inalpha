# Issue #107 — Local Preflight / Diagnostic Materialization Helper

**Purpose:** reduce setup mistakes when the runtime phase begins while keeping every contributor diagnostic/helper out of the actual contribution diff.

The helpers do **not** install dependencies, start Docker, run benchmarks, edit production code, or apply Candidate A. They only verify the checkout and materialize known contributor-only diagnostics plus local safety/evidence helpers as untracked files.

---

## 1. Helpers

```text
.faysk-notes/tools/prepare_issue107_local.ps1
.faysk-notes/tools/prepare_issue107_local.sh
```

Use PowerShell on Windows or Bash in WSL/Linux.

---

## 2. Safety rules built into the helpers

Before creating any diagnostic file they require:

```text
current branch = fix/data-service-saturation
working tree = clean
origin remote exists
upstream remote exists
fresh fetch of upstream/main
fresh fetch of origin/notes/issue-107
HEAD == upstream/main
```

If any condition fails, the helper stops rather than resetting/rebasing/destructively changing the checkout.

This is intentional. Upstream drift must be reviewed, not silently erased.

The helper also refuses to overwrite:

```text
an existing destination path
or
a tracked destination path
```

---

## 3. Getting the helper while staying on the contribution branch

First fetch the notes branch:

```bash
git fetch origin notes/issue-107
```

### Bash / WSL

Materialize the helper outside the repository so it never appears in `git status`:

```bash
git show origin/notes/issue-107:.faysk-notes/tools/prepare_issue107_local.sh \
  > /tmp/prepare_issue107_local.sh
bash /tmp/prepare_issue107_local.sh
```

### PowerShell

Write it to the Windows temporary directory without a UTF-8 BOM:

```powershell
$script = git show origin/notes/issue-107:.faysk-notes/tools/prepare_issue107_local.ps1
$path = Join-Path $env:TEMP 'prepare_issue107_local.ps1'
[IO.File]::WriteAllText($path, ($script -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
& $path
```

---

## 4. Files materialized

### Factor diagnostics / safety wrapper

```text
services/factor/tests/test_issue107_macro_stampede_local.py
services/factor/tests/test_issue107_live_cache_stampede_local.py
services/factor/issue107_factor_app.py
services/factor/issue107_target_check.py
services/factor/issue107_factor_macro_probe.py
services/factor/issue107_runner_poll_probe.py
services/factor/issue107_mixed_workload_probe.py
services/factor/issue107_sustained_mixed_probe.py
services/factor/issue107_sustained_acceptance_probe.py
```

`issue107_factor_app.py` is mandatory for factor-driven capacity scenarios. It refuses startup when factor's configured `DATA_SERVICE_URL` does not match the expected contributor fake data-service target. `issue107_target_check.py` then verifies both ends without generating load. See `48-factor-target-fail-closed.md` and `49-runtime-safety-order.md`.

`issue107_sustained_mixed_probe.py` is the base bounded soak helper and remains useful for H11-heavy same-key stress. `issue107_sustained_acceptance_probe.py` adds explicit cross-sectional `unique` factor keys, a `same` control, missed-slot accounting, partial backlog reporting and one-worker provider/pool counter deltas for the sustained evidence stage. See `50-sustained-load-acceptance.md` and `52-provider-isolation-and-soak-hardening.md`.

### Data diagnostics

```text
services/data/tests/test_issue107_pool_pressure_local.py
services/data/issue107_slow_data_app.py
services/data/issue107_load_probe.py
services/data/issue107_timeout_persistence_probe.py
```

`issue107_slow_data_app.py` is intentionally stricter than normal development startup:

```text
CONSTITUENT_SNAPSHOT_INDICES forced empty before importing data main
requested OHLCV venues → deterministic fake connector
other registered OHLCV venues → fail-closed blocker
```

This prevents an ordinary contributor `.env` from starting the production constituent catch-up scheduler and prevents an unexpected `/backfill/bars` venue from silently reaching a real market-data connector during load generation.

### Local safety/evidence helpers

```text
scripts/issue107_capture_env.ps1
scripts/issue107_benchmark_db.ps1
scripts/issue107_benchmark_db.sh
```

All of them are intentionally **untracked**.

`issue107_benchmark_db.*` has the benchmark DB name hard-coded to `inalpha_issue107`. It can verify the target or truncate only `public.bars` in that dedicated database; it does not accept an arbitrary database name. This is deliberate protection against accidentally clearing the contributor's ordinary `inalpha` database.

The post-fix Candidate A regression and the Candidate A patch are deliberately **not** materialized at baseline-preparation time. They belong only after H1 selects Candidate A.

---

## 5. What it does not materialize

```text
candidate_a_narrow_db_lease.patch
test_candidate_a_regression_draft.py
```

Reason:

```text
baseline first
→ decision gate
→ then materialize the selected fix/regression
```

This prevents the contributor checkout from visually mixing the expected fix with the evidence-gathering phase.

---

## 6. Tool version output

The helper prints availability/version information for:

```text
docker
uv
python
node
pnpm
```

Missing tools are reported but are not installed automatically.

Actual dependency setup remains the repository's documented `CONTRIBUTING.md` flow and the exact sequence in `11-local-test-runbook.md`.

---

## 7. Benchmark DB helper

After infra is running and migrations have been applied, verify the dedicated target before a session:

### PowerShell

```powershell
.\scripts\issue107_benchmark_db.ps1 verify
```

### Bash / WSL

```bash
bash scripts/issue107_benchmark_db.sh verify
```

For a deliberately DB-cold scenario, after the previous workload has fully stopped:

```powershell
.\scripts\issue107_benchmark_db.ps1 reset-bars
```

or:

```bash
bash scripts/issue107_benchmark_db.sh reset-bars
```

The helper:

```text
requires the infra postgres container to be running
connects only to inalpha_issue107
verifies current_database()
verifies public.bars exists
shows the row count before reset
TRUNCATEs only public.bars when reset-bars is explicitly requested
verifies row count = 0 afterward
```

This does not replace the cache-state discipline in `41-benchmark-db-state-determinism.md`; it makes the destructive part harder to perform against the wrong DB.

---

## 8. Mandatory no-load check before factor/mixed/sustained load

After starting the fake data wrapper and the factor fail-closed wrapper, run:

```text
services/factor/issue107_target_check.py
```

The checker now requires:

```text
all workload venues are fake
no required venue is simultaneously reported blocked
snapshot scheduler isolation is active
factor DATA_SERVICE_URL equals the checked fake data URL
factor wrapper expectation equals the same URL
macro enabled when requested
```

Only `issue107_target_check=PASS` permits factor/mixed/sustained load generation.

---

## 9. Cleanup

The preparation helpers only remove their known **untracked** destinations.

### Bash

```bash
bash /tmp/prepare_issue107_local.sh cleanup
```

### PowerShell

```powershell
& $path -Cleanup
```

They refuse to delete a path if Git says it is tracked.

After cleanup:

```bash
git status --short
```

should return to the contributor's ordinary checkout state.

The evidence directory created by `issue107_capture_env.ps1` lives outside the repository and is intentionally **not** deleted by this cleanup helper.

---

## 10. Why this helper exists

The runtime plan now uses several diagnostic files across data and factor services. Manually copying them one by one creates avoidable failure modes:

```text
copying an outdated notes revision
putting a tool in the wrong service environment
accidentally adding diagnostics to the production commit
benchmarking a branch that drifted from upstream
silently overwriting local work
resetting the wrong database while trying to create a cold benchmark state
starting factor against the ordinary data-service while believing the fake target is in use
forgetting the no-load target verifier before a factor/mixed benchmark
letting ordinary constituent scheduler config create unrelated real provider traffic
letting an unexpected backfill venue escape to a real connector
```

The helper removes those clerical risks while deliberately leaving the important engineering decisions manual and evidence-driven.
