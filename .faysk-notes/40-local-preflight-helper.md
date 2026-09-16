# Issue #107 — Local Preflight / Diagnostic Materialization Helper

**Purpose:** reduce setup mistakes when the runtime phase begins while keeping every contributor diagnostic out of the actual contribution diff.

The helpers do **not** install dependencies, start Docker, run benchmarks, edit production code, or apply Candidate A. They only verify the checkout and materialize known contributor-only diagnostics as untracked files.

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

### Factor diagnostics

```text
services/factor/tests/test_issue107_macro_stampede_local.py
services/factor/tests/test_issue107_live_cache_stampede_local.py
services/factor/issue107_factor_macro_probe.py
services/factor/issue107_runner_poll_probe.py
services/factor/issue107_mixed_workload_probe.py
```

### Data diagnostics

```text
services/data/tests/test_issue107_pool_pressure_local.py
services/data/issue107_slow_data_app.py
services/data/issue107_load_probe.py
services/data/issue107_timeout_persistence_probe.py
```

They are intentionally **untracked**.

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

## 7. Cleanup

The helpers only remove their known **untracked** diagnostic destinations.

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

---

## 8. Why this helper exists

The runtime plan now uses several diagnostic files across data and factor services. Manually copying them one by one creates avoidable failure modes:

```text
copying an outdated notes revision
putting a tool in the wrong service environment
accidentally adding diagnostics to the production commit
benchmarking a branch that drifted from upstream
silently overwriting local work
```

The helper removes those clerical risks while deliberately leaving the important engineering decisions manual and evidence-driven.
