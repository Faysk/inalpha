# Issue #107 — Implementation Log

Chronological working log. Keep this factual: what changed, what was observed, what failed, and why a decision was made.

---

## 2026-09-16

### Setup / review

- Created contributor fork `Faysk/inalpha`.
- Contribution branch: `fix/data-service-saturation`.
- Notes branch: `notes/issue-107`.
- Reviewed project documentation, architecture rules, CI, PR templates, security policy, service READMEs, current-state docs, factor/data behavior, and existing concurrency patterns.
- Confirmed #107 remains open.
- Confirmed current `main` already contains partial mitigation compared with the original issue wording:
  - panel fetch concurrency bounded at 16,
  - panel avoids forced per-symbol fresh backfills,
  - incremental `/backfill/bars`,
  - bounded factor GET retry/backoff.
- Identified freshness/caller-semantics risk if a future admission gate returns a non-2xx response that `fresh=True` callers do not interpret.
- Decision: no production code changes before reproducible baseline.

### Pending

- [ ] maintainer confirms proposed technical direction
- [ ] sync to latest upstream main
- [ ] establish runnable environment
- [ ] run pre-change tests
- [ ] build reproduction harness
- [ ] capture baseline

---

## Log entry template

### YYYY-MM-DD — short title

**Context**

```text
What were we trying to do?
```

**Change / command**

```text
What did we change or run?
```

**Observed result**

```text
What actually happened?
```

**Evidence**

```text
logs / metrics / test output / commit
```

**Conclusion**

```text
What does this prove or rule out?
```

**Next action**

```text
What should happen next?
```

---

## Debugging rules

1. Change one meaningful variable at a time where possible.
2. Preserve failing reproduction before fixing it.
3. Record exact commit SHA for benchmark runs.
4. Do not interpret an external provider outage as application saturation without evidence.
5. Do not treat a lower error rate as success if freshness/correctness changed.
6. Rerun the same benchmark after the fix; do not compare unrelated scenarios.
