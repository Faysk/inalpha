# Pre-change check ordering: materialized diagnostics contaminated Ruff scope

Status: contributor-only process note for issue #107. Not a production defect and not part of the upstream fix.

## What happened

The contributor diagnostics were materialized before the repository pre-change Ruff/pytest checks were executed.

The runbook orders these steps the other way around:

1. run pre-change repository checks,
2. then materialize contributor-only diagnostics.

Because the diagnostic files are copied directly into `services/data` and `services/factor` as untracked `.py` files, running:

```text
uv run ruff check .
```

from those service directories included the contributor probes in Ruff's recursive scan.

Observed failures were all import-order (`I001`) findings in contributor-only files:

```text
services/data/issue107_slow_data_app.py
services/factor/issue107_mixed_workload_probe.py
services/factor/issue107_runner_poll_probe.py
services/factor/issue107_sustained_mixed_probe.py
```

The PowerShell wrapper stopped immediately on Ruff failure, so the normal service pytest suites did not run in that attempt.

## Interpretation

These failures are **not evidence that current upstream/main fails Ruff**. They are also not production-code regressions.

They show that our local pre-change validation scope was contaminated by already-materialized contributor diagnostics.

The earlier consistency check did complete successfully with:

```text
passed = 19
warnings = 12
failed = 0
```

The warnings were pre-existing repository consistency warnings and were not caused by #107 code changes.

## Corrective action

Do not edit production files and do not apply Ruff `--fix` across the service directories while the probes are present.

For a clean current-main baseline, either:

- temporarily clean up the contributor diagnostics using the materialization helper's `-Cleanup` mode, run the repository checks, then re-materialize them; or
- run the baseline check only over tracked Python files.

The preferred path is cleanup -> baseline checks -> re-materialize, because it reproduces the untouched checkout exactly and avoids hand-maintaining exclusion patterns.

After the untouched baseline is recorded, re-materialize the diagnostics and run their own syntax/tests separately.

## Classification

- Upstream production bug: no.
- #107 root cause evidence: no.
- Local benchmark process mistake: yes.
- Repository contamination: no; diagnostic files remain untracked.
- Production code changed: no.

## Process lesson

Keep these phases distinct:

```text
clean checkout baseline
-> materialize diagnostics
-> diagnostic validation
-> runtime experiments
-> production candidate only after evidence
```

Do not use recursive whole-service lint as an untouched-upstream baseline after injecting contributor-only files into that service tree.
