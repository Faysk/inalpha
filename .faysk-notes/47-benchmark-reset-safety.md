# Issue #107 — Benchmark Reset Safety

**Status:** runtime-preparation guard.  
**Purpose:** make the only destructive benchmark operation — clearing persisted bars for a cold-state comparison — fail closed against the dedicated `inalpha_issue107` database.

---

## 1. Why this exists

Cold/warm comparisons require persistent bar state to be controlled independently from the factor process cache.

The benchmark therefore sometimes needs:

```sql
TRUNCATE TABLE public.bars;
```

That is safe only when the target is the disposable benchmark DB:

```text
inalpha_issue107
```

The contributor's ordinary `inalpha` database may contain useful local data and must not be treated as disposable merely because it is not committed to Git.

---

## 2. Helpers

Prepared contributor-only helpers:

```text
tools/issue107_benchmark_db.ps1
tools/issue107_benchmark_db.sh
```

The preflight materializer copies them to:

```text
scripts/issue107_benchmark_db.ps1
scripts/issue107_benchmark_db.sh
```

They are intentionally untracked and must not enter the upstream PR.

---

## 3. Fail-closed design

The helpers deliberately do **not** accept a database-name argument.

The target is hard-coded to:

```text
inalpha_issue107
```

Before a reset they require:

```text
infra postgres service is running
psql can connect to inalpha_issue107
current_database() == inalpha_issue107
public.bars exists
```

Only the explicit `reset-bars` action performs a destructive statement.

The helper then verifies:

```text
count(public.bars) == 0
```

after the truncate.

If any check fails, it exits without deliberately targeting another database.

---

## 4. Usage

### Verify only

PowerShell:

```powershell
.\scripts\issue107_benchmark_db.ps1 verify
```

Bash / WSL:

```bash
bash scripts/issue107_benchmark_db.sh verify
```

This changes nothing.

### Reset bars for a DB-cold scenario

Run only after the previous workload has fully stopped.

PowerShell:

```powershell
.\scripts\issue107_benchmark_db.ps1 reset-bars
```

Bash / WSL:

```bash
bash scripts/issue107_benchmark_db.sh reset-bars
```

Expected evidence:

```text
benchmark_database=inalpha_issue107
bars_table_ready=True/true
bars_count_before=<N>
bars_count_after=0
```

Capture that output with the scenario evidence when the cold state matters.

---

## 5. What this helper does not do

It does not:

```text
create the database
run migrations
restart factor
delete factor process cache
truncate any other table
accept arbitrary SQL
accept an arbitrary DB target
modify tracked files
upload results
```

Database creation/migrations remain explicit setup steps in `11-local-test-runbook.md` and `41-benchmark-db-state-determinism.md`.

---

## 6. Benchmark-state rule remains two-dimensional

A successful reset proves only:

```text
data DB bars = cold
```

It does not prove:

```text
factor process cache = cold
```

For cold factor scenarios the sequence remains:

```text
stop/restart factor
→ reset benchmark bars
→ verify count = 0
→ run exactly one cold scenario
```

For an intentional warm control, do neither reset.

---

## Current conclusion

The benchmark plan needs destructive state control, but there is no reason that operation should rely on manually retyping a database name correctly every time.

This helper turns the rule:

> never truncate the contributor's ordinary database

into an executable guard rather than a reminder.
