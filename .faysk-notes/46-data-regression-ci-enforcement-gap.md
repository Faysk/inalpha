# Issue #107 — Data Regression Test CI Enforcement Gap

**Status:** confirmed from current `main` CI.  
**Purpose:** make sure a good #107 regression test is not mistaken for automatically enforced coverage when the current workflow does not run `services/data` pytest.

---

## 1. Current CI behavior

Current `.github/workflows/ci.yml` has a Python matrix:

```text
service = data, paper, research, factor, evolver
```

but that job runs only:

```text
uv sync --frozen
ruff check .
mypy . || true
```

The dedicated pytest job currently covers only:

```text
paper
evolver
```

Therefore:

```text
services/data/tests/test_*.py
```

are **not executed by the current GitHub Actions CI** merely because they are committed under the data service.

This matches `CONTRIBUTING.md`, which lists paper/evolver pytest as the CI red-line suite while still asking contributors to run relevant service tests locally.

---

## 2. Why this matters to #107

If Candidate A is selected, the strongest intended regression is approximately:

```text
test DB pool max_size = 2
4 blocked backfills all reach provider I/O
/health still gets DB capacity
```

Committing that test under `services/data/tests/` gives valuable executable documentation and local regression coverage.

But under current CI it would not automatically fail a future PR that reintroduced request-long DB ownership.

Do not write PR language such as:

```text
CI now protects this regression
```

unless the workflow is actually changed to run it.

---

## 3. Do not expand #107 automatically

The absence of data pytest in CI does **not** justify immediately editing `.github/workflows/ci.yml`.

That would change PR scope from:

```text
data-service reliability bugfix + regression test
```

to:

```text
data-service reliability bugfix + CI policy/runtime change
```

The latter may be worthwhile, but it should be deliberate.

Our working rule remains:

```text
first reproduce #107
→ select/fix measured cause
→ prove regression locally
→ then decide whether CI enforcement belongs in the same PR
```

---

## 4. Options after the fix is proven locally

### Option 1 — keep PR1 data-local

Commit the focused data regression test and report the exact local command/result in the PR.

Pros:

```text
smallest scope
no CI topology change
maintainer reviews one reliability fix
```

Con:

```text
regression is not automatically executed by current GitHub Actions
```

If chosen, say this honestly if review asks about automation.

### Option 2 — add data pytest enforcement in the same PR

Only consider this after the data test suite is proven stable locally and the maintainer is comfortable with the scope.

A useful design constraint is to preserve an already-required status context rather than create a new optional check that branch protection does not require.

For example, the existing data matrix job could conditionally run data pytest after provisioning its required Timescale/Postgres state.

However, this needs careful review because:

- the current lint matrix has no DB service;
- adding a job-level DB service would affect all matrix entries unless structured carefully;
- data tests currently use a real DB fixture;
- migrations/environment/port need to be deterministic;
- CI duration and external-network isolation need measurement;
- changing an existing required job can block unrelated PRs if flaky.

Do not implement this from static speculation.

### Option 3 — follow-up CI PR

Keep #107 focused, then propose a separate CI improvement once the new regression demonstrates the value of automated data tests.

This is often the cleanest separation if the CI change is non-trivial.

---

## 5. Branch-protection nuance

Current `main` branch protection exposes required contexts including the existing Python `data` lint/mypy matrix context.

A brand-new CI job would not automatically become a required branch-protection context merely because it exists in the workflow.

That makes a separate new job less useful as an enforcement mechanism unless the maintainer also updates branch protection.

As an external contributor we should not assume we can or should change repository protection settings.

---

## 6. PR wording if CI is unchanged

Safe wording:

```text
Added a deterministic data-service regression test and verified it locally with `uv run pytest ...`.
The repository's current CI does not run data pytest, so the PR also includes the exact local test result.
```

Avoid sounding defensive; this is simply the current project configuration.

If the maintainer prefers automated enforcement, discuss whether they want it in this PR or a follow-up.

---

## 7. Decision gate

After Candidate A (or another selected fix) exists and passes locally:

```text
Is the regression deterministic and fast?
    no → fix the test first; never put a flaky capacity test into required CI
    yes ↓

Does current data pytest suite run cleanly in a CI-like DB environment?
    unknown → measure locally / containerized first
    yes ↓

Would adding CI enforcement materially broaden or destabilize PR1?
    yes → keep PR1 focused; propose follow-up
    no  → ask/align with maintainer before changing CI policy
```

---

## Current conclusion

The #107 regression test remains worth writing if the runtime evidence selects a fix.

But **test exists** and **test is required by CI** are different claims in the current Inalpha repository.

We will preserve that distinction in implementation and PR wording.
