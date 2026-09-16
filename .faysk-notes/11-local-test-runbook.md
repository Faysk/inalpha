# Issue #107 — Local Baseline Test Runbook

**Purpose:** exact steps to run later on the contributor machine without improvising setup or touching production behavior first.

This is contributor-only documentation. Commands are based on the repository's current `CONTRIBUTING.md`, test fixtures, and dev compose files.

---

## 1. Safety / branch check

Work only on:

```text
Faysk/inalpha:fix/data-service-saturation
```

Before setup:

```bash
git status --short
git fetch upstream
git checkout fix/data-service-saturation
git reset --hard upstream/main
git rev-parse HEAD
```

Expected reviewed baseline at the time these notes were prepared:

```text
ed01be9056776c107ab76a404c328a4fed19f529
```

If upstream has moved, stop and re-review the #107-sensitive files before using old benchmark conclusions.

Do **not** commit the contributor diagnostic copied from the notes branch.

---

## 2. Tool versions to record

Capture these in the baseline notes:

```bash
git --version
docker --version
docker compose version
uv --version
python --version
node --version
pnpm --version
```

Also record:

```text
OS / WSL version
CPU
RAM
Docker resource limits if explicitly configured
```

Performance numbers are only comparable when the execution environment is known.

---

## 3. Official local dependency setup

The repository's documented setup is:

```bash
cd packages/orchestration && pnpm i && cd ../..
for service in data paper research factor evolver; do
  (cd "services/$service" && uv sync)
done
cp .env.example .env
cp infra/.env.example infra/.env
(cd infra && docker compose up -d)
(cd infra/migrations && uv sync && uv run alembic upgrade head)
```

The current local infra example sets:

```text
POSTGRES_USER=quant
POSTGRES_PASSWORD=devpass
POSTGRES_DB=inalpha
POSTGRES_PORT=5433
```

This matches the data test fixture's default test DB URL:

```text
postgresql+psycopg://quant:devpass@localhost:5433/inalpha
```

Do not silently change the database port/password between setup and tests.

---

## 4. Pre-change baseline checks

Before running any new #107 diagnostic, prove the current checkout is healthy.

### Required project consistency

```bash
bash scripts/check-consistency.sh
```

### Data service

```bash
cd services/data
uv run ruff check .
uv run pytest
cd ../..
```

### Factor service

```bash
cd services/factor
uv run ruff check .
uv run pytest
cd ../..
```

Record:

```text
command
exit code
passed / failed / skipped counts
runtime
unexpected warnings
```

If existing upstream tests fail before our changes, preserve that output separately. Do not "fix" unrelated failures inside #107 without deciding whether they block the investigation.

---

## 5. Materialize the contributor-only deterministic diagnostic

Stay on `fix/data-service-saturation`.

Fetch the notes branch:

```bash
git fetch origin notes/issue-107
```

Copy the draft test from the notes branch without merging/cherry-picking the notes branch:

```bash
git show origin/notes/issue-107:.faysk-notes/tools/test_backfill_pool_pressure_draft.py \
  > services/data/tests/test_issue107_pool_pressure_local.py
```

Confirm it is the only temporary file:

```bash
git status --short
```

Expected:

```text
?? services/data/tests/test_issue107_pool_pressure_local.py
```

Do not `git add` it.

---

## 6. Run the pool-pressure diagnostic

```bash
cd services/data
uv run pytest -vv -s tests/test_issue107_pool_pressure_local.py
cd ../..
```

The draft contains two cases.

### Control

```text
9 blocked fake-provider backfills
→ 9/10 DB connections retained by route-scoped DBConn
→ one pool slot remains
→ /health expected to complete
```

### Pressure case

```text
10 blocked fake-provider backfills
→ 10/10 default DB connections retained
→ /health expected to wait
→ releasing fake provider lets backfills complete
→ /health then completes
```

No real market-data provider is contacted.

### Interpretation

If both cases behave as predicted:

```text
confirmed:
current route/resource ordering can starve unrelated DB-backed requests

NOT YET confirmed:
this is the dominant production root cause of #107
```

If the 10-request case does **not** block `/health`, preserve the result and investigate why. Do not modify the test until the discrepancy is understood.

---

## 7. Cleanup after diagnostic

```bash
rm services/data/tests/test_issue107_pool_pressure_local.py
git status --short
```

Expected working tree after cleanup:

```text
clean
```

The contribution branch should still contain zero #107 production changes at this point.

---

## 8. Service-level baseline after the deterministic test

Only after the test suite and deterministic diagnostic are understood:

```bash
bash scripts/dev.sh
```

First verify the services normally before load:

```text
data     :8001
paper    :8002
research :8003
factor   :8004
evolver  :8005
mastra   :4111
```

Capture normal `/health` latency before applying any load.

Then move to the contributor-side load scenarios in `03-reproduction-plan.md`:

```text
A. slow-provider/backfill pressure
B. live factor + macro fan-out
C. panel control
D. live-runner-like polling
E. mixed representative load
```

Do not start with the mixed scenario. Isolate each resource first.

---

## 9. One-worker vs two-worker discipline

The repository's production compose currently runs:

```text
data WORKERS=2
factor WORKERS=1
paper WORKERS=1
research WORKERS=1
```

Use:

```text
1 data worker
→ deterministic diagnosis / easier attribution

2 data workers
→ production-like confirmation
```

Never describe a normal `asyncio.Semaphore`/lock/cache as service-global under the two-worker topology. It is process-local unless an external coordination mechanism is introduced.

---

## 10. Evidence to save

For every run record:

```text
commit SHA
worker count
test/scenario name
request count / concurrency
duration
p50 / p95 / p99
HTTP status counts
DATA_SERVICE_UNREACHABLE count
zero-row/no-progress refresh count
DB pool symptoms
provider errors
CPU / memory where practical
notes on freshness/cutoff behavior
```

For the initial deterministic diagnostic, the most important evidence is simply:

```text
9 blocked backfills: health available? yes/no
10 blocked backfills: health blocked? yes/no
```

---

## 11. Stop conditions

Stop before implementing a production fix if:

- the baseline cannot reproduce a capacity problem;
- current upstream moved materially since the reviewed commit;
- failures are caused by local setup rather than service saturation;
- the proposed solution would require touching `_shared`, live-runner/risk paths, or a large cross-service contract without renewed scope review;
- a lower error rate would only be achieved by weakening freshness or hiding a failed refresh.

---

## 12. First implementation gate

Only after baseline evidence exists, decide among:

```text
A. shorten DB connection lifetime around provider I/O
B. add bounded admission before scarce DB checkout
C. address factor HTTP client reuse
D. another measured bottleneck
```

Do not implement all candidates together. One measured cause, one minimal intervention, same benchmark before/after.
