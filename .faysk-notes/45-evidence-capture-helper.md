# Issue #107 — Evidence Capture Helper

**Purpose:** create a local result session outside the Git working tree and record enough environment/revision metadata to make before/after numbers interpretable.

Tool:

```text
.faysk-notes/tools/issue107_capture_env.ps1
```

The helper does **not** run benchmarks, change code, expose environment variables, upload files, or modify Git state.

---

## 1. Materialize it outside the repository

While on `fix/data-service-saturation`:

```powershell
git fetch origin notes/issue-107
$script = git show origin/notes/issue-107:.faysk-notes/tools/issue107_capture_env.ps1
$path = Join-Path $env:TEMP 'issue107_capture_env.ps1'
[IO.File]::WriteAllText($path, ($script -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
```

This keeps the helper itself out of `git status`.

---

## 2. Start a baseline evidence session

```powershell
& $path -Kind baseline -Label one-worker
```

It creates a sibling directory to the repo:

```text
../inalpha-issue107-results/YYYYMMDD-HHMMSS-baseline-one-worker/
```

with:

```text
00-environment.txt
notes.md
```

The manifest records:

```text
local timestamp
branch
HEAD
upstream/main
HEAD == upstream/main
short git status
git/docker/compose/uv/python/node/pnpm versions
Windows version/build
CPU
RAM
Docker runtime CPU/memory summary where available
```

It deliberately does **not** dump environment variables or secrets.

---

## 3. Start a Candidate-A comparison session later

Only after the baseline selects and implements Candidate A:

```powershell
& $path -Kind candidate -Label candidate-a
```

Keep baseline and candidate outputs in separate session directories.

Never overwrite the baseline results with a later rerun.

---

## 4. Capture command output

Use `Tee-Object` so evidence is written while remaining visible in the terminal.

Example after `$sessionDir` has been printed by the helper:

```powershell
Push-Location services/data
uv run pytest -vv -s tests/test_issue107_pool_pressure_local.py 2>&1 |
  Tee-Object -FilePath 'C:\path\to\session\C-h1-pool2.txt'
Pop-Location
```

Use the stable filenames in `44-runtime-execution-manifest.md`.

For long-running Uvicorn processes, keep the server console/log separately from the probe output; both can matter for worker PID, cancellation and provider-start evidence.

---

## 5. Manual fields

`00-environment.txt` leaves these intentionally blank:

```text
data_workers
factor_workers
provider_mode
provider_delay_s
fake_bars_per_fetch
factor_cache
data_bars
scenario
```

Fill them for the relevant session/scenario rather than trying to infer them later from memory.

---

## 6. Safety behavior

For a baseline session, if:

```text
HEAD != upstream/main
```

it prints a warning.

The stronger hard-stop remains the separate preflight helper in `40-local-preflight-helper.md`; evidence capture does not reset/rebase/stash anything automatically.

Results stay outside the repo and are never uploaded by this helper.

Before sharing any result publicly, manually inspect it for secrets/private paths even though the helper itself avoids environment-value dumps.

---

## 7. Why keep raw outputs

The final PR will contain a concise before/after summary, not thousands of lines of benchmark logs.

Raw local evidence is still useful because it lets us later verify:

```text
which revision was tested
which worker topology was used
whether an exception was ReadTimeout vs ConnectError
whether provider/pool signals moved together
whether one run was an outlier
whether a claimed negative result was actually measured
```

That supports concise PR language without relying on memory or cherry-picking the best run.
