# Issue #107 — `pg_stat_activity` Diagnostic

**Purpose:** obtain DB-side evidence for H1 without modifying project instrumentation or `services/_shared`.

This is contributor-only runtime guidance.

---

## 1. Question

During the deterministic fake-provider wait, does PostgreSQL actually observe data-service connections sitting in an open transaction after `latest_bar_ts()`?

Static code predicts:

```text
DBConn checkout
→ SELECT max(ts)
→ provider sleep
```

with Psycopg default `autocommit=False`.

During that first provider sleep, the last DB command has completed but the transaction has not been finalized, so PostgreSQL should normally show those sessions as:

```text
idle in transaction
```

This is stronger evidence than inferring pool occupancy only from HTTP latency.

---

## 2. Isolate the data-service sessions

For this diagnostic, run only the fake data-service workload where practical.

Give its DB connections a unique `application_name` through a temporary environment override rather than editing `.env` permanently.

Local default URL is:

```text
postgresql+psycopg://quant:devpass@localhost:5433/inalpha
```

Diagnostic override:

```text
postgresql+psycopg://quant:devpass@localhost:5433/inalpha?application_name=issue107-data
```

Example Bash/WSL:

```bash
DATABASE_URL='postgresql+psycopg://quant:devpass@localhost:5433/inalpha?application_name=issue107-data' \
ISSUE107_PROVIDER_DELAY_S=10 \
uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 1
```

PowerShell:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://quant:devpass@localhost:5433/inalpha?application_name=issue107-data'
$env:ISSUE107_PROVIDER_DELAY_S = '10'
uv run uvicorn issue107_slow_data_app:app --host 127.0.0.1 --port 18001 --workers 1
```

Restore/clear the temporary environment override after the diagnostic.

---

## 3. Snapshot query

While fake backfills are blocked, query Postgres:

```sql
SELECT
    pid,
    application_name,
    state,
    wait_event_type,
    wait_event,
    now() - xact_start AS xact_age,
    now() - state_change AS state_age,
    left(query, 120) AS last_query
FROM pg_stat_activity
WHERE datname = current_database()
  AND application_name = 'issue107-data'
ORDER BY pid;
```

Using the repository's local Docker Postgres:

```bash
docker exec -it inalpha-postgres \
  psql -U quant -d inalpha -c "SELECT pid, application_name, state, wait_event_type, wait_event, now()-xact_start AS xact_age, now()-state_change AS state_age, left(query,120) AS last_query FROM pg_stat_activity WHERE datname=current_database() AND application_name='issue107-data' ORDER BY pid;"
```

Grouped view:

```sql
SELECT
    state,
    wait_event_type,
    wait_event,
    count(*) AS sessions,
    max(now() - xact_start) AS oldest_xact
FROM pg_stat_activity
WHERE datname = current_database()
  AND application_name = 'issue107-data'
GROUP BY state, wait_event_type, wait_event
ORDER BY sessions DESC;
```

---

## 4. Expected current-main signal

With one worker and ten unique backfills blocked on their **first** fake provider fetch:

```text
~10 data-service DB sessions
state = idle in transaction
last query resembles SELECT max(ts) ... FROM bars
xact_start remains non-null and ages while provider sleep continues
```

Exact connection count may differ during pool startup/races; save what actually appears.

The key property is not the number 10 by itself. It is:

```text
provider work is waiting outside PostgreSQL
while PostgreSQL sessions remain in transaction because the HTTP request still owns DBConn
```

---

## 5. Expected after Candidate A, if selected

During the same provider-blocked phase:

```text
latest_bar_ts short context exits
→ transaction is finalized
→ connection returns to pool
→ provider wait occurs without an open DB transaction
```

Therefore we should no longer see one `idle in transaction` session per blocked provider request.

Idle pool connections may still appear as:

```text
state = idle
xact_start = NULL
```

That is normal and must not be confused with checked-out/open-transaction capacity retention.

---

## 6. Important limitation

`pg_stat_activity` cannot always tell whether a plain `idle` connection is currently checked out to application code or simply sitting available in the Psycopg pool.

For the **baseline first provider wait**, `idle in transaction` gives a much stronger signal because `latest_bar_ts()` has already executed a SELECT and the route has not finalized that transaction.

For later post-commit provider waits, PostgreSQL may show `idle` even though the HTTP request still retains the connection. That is why this DB-side view complements rather than replaces:

```text
9-vs-10 endpoint diagnostic
+ /openapi non-DB control
+ /health or /bars DB-backed canary
```

---

## 7. Do not fix by hiding the metric

If `idle in transaction` is observed, do not respond by enabling autocommit globally in `_shared` just to make the state disappear.

That would alter transaction semantics across every Python service and is far outside #107.

The issue-specific question is resource lifetime around external provider work, not a repo-wide database mode change.

---

## 8. Evidence to record

Before load:

```text
state counts:
connection count:
```

During 9 blocked backfills:

```text
state counts:
idle-in-transaction count:
oldest xact age:
health result:
```

During 10 blocked backfills:

```text
state counts:
idle-in-transaction count:
oldest xact age:
openapi result:
health result:
```

After provider release:

```text
state counts:
idle-in-transaction count:
```

If Candidate A is selected, collect the exact same snapshots after the patch.
