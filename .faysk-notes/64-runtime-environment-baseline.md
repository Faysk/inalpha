# Issue #107 — Local runtime environment baseline

Status: contributor-only benchmark metadata for the local #107 investigation. Not upstream project documentation and not intended for the production PR unless benchmark methodology/details are requested.

## Captured tool versions

Captured before materializing any #107 diagnostic load:

```text
git            2.54.0.windows.1
Docker Engine  29.8.0 (build 88096ef)
Docker Compose 5.5.1
uv             0.12.2 (46ead6098, 2026-08-05, x86_64-pc-windows-msvc)
python         3.13.7 (current shell default)
node           22.23.1
pnpm           12.3.4 (global/current shell default)
```

Repository state immediately before this capture:

```text
branch = fix/data-service-saturation
working tree = clean
HEAD = ed01be9056776c107ab76a404c328a4fed19f529
upstream/main remote verified at the same SHA
full self-host stack stopped
```

## Reproducibility differences to control

These are environment differences, not Inalpha bugs:

- Node 22 matches the CI reference family.
- The current shell's Python is 3.13.7. The services declare `requires-python >=3.12`, while Ruff/mypy are configured for Python 3.12 semantics. For #107 benchmark parity, service virtual environments should be created explicitly with Python 3.12 rather than silently benchmarking on 3.13.
- The current global pnpm is 12.3.4, while the reviewed project/CI workflow uses the pnpm 11 family. Use an explicit pnpm 11 invocation for orchestration dependency setup rather than changing benchmark results with an accidental major-version drift.
- Docker Compose is v5.5.1, newer than the older runbook compatibility wording. The #107 harness uses basic compose operations; keep the exact version in evidence and only treat this as a problem if a concrete behavior difference appears.

## Benchmark rule

Do not silently normalize these differences after results are collected. Any runtime result intended for before/after comparison must record the actual interpreter/package-manager/container tooling used. Before the first baseline, pin Python and pnpm to the intended benchmark versions so the same versions can be reused for the candidate run.

No production code change is justified by any item in this note.
