# Windows Alembic config encoding failure during #107 bootstrap

Status: contributor-only environment/bootstrap finding. Separate from the production fix for issue #107 unless the maintainer explicitly asks for Windows self-host/bootstrap hardening.

## Reproduction

On the Windows PowerShell contributor host, with CPython 3.12.13 and Alembic 1.18.4 from `infra/migrations/.venv`, running:

```text
uv run alembic upgrade head
```

from `infra/migrations` failed before any migration was applied. The traceback ended in Python `configparser` opening `alembic.ini` with the Windows locale codec (`cp1252`) and raising:

```text
UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d ...
```

The dedicated benchmark database `inalpha_issue107` had already been created, but verification showed `public.bars` absent, confirming migrations had not run.

## Root cause evidence

The tracked `infra/migrations/alembic.ini` is UTF-8 and contains Chinese comments near the beginning of the file. The failing Alembic/configparser path explicitly reads the config with locale encoding. On this Windows host the locale codec is CP1252, which cannot decode the UTF-8 byte sequence in those comments.

This is the same general portability class as the earlier self-host UTF-8 issue: UTF-8 repository text is being consumed through a Windows locale-dependent text reader.

## Classification

- Issue #107 capacity root cause: **no**.
- Benchmark blocker until worked around: **yes**.
- Production runtime defect: **not established**.
- Windows development/bootstrap portability bug: **credible/confirmed for this path**.
- Repository/data corruption: **none observed**; failure happened while reading Alembic configuration before migrations executed.

## Safe local workaround for #107

Do not modify the tracked `alembic.ini` on the contribution branch just to continue the benchmark.

For the local benchmark, create a temporary ASCII-only copy of the same config by removing comment lines (the non-ASCII content is comments), run Alembic with `-c <temp-file>`, then delete the temporary file. Keep the current working directory at `infra/migrations` so `script_location = .` still resolves to the repository migration directory.

This preserves all functional Alembic settings while avoiding the locale decode failure and leaves `git status` clean.

## Workaround result

The temporary ASCII-only config workaround was executed successfully on the benchmark host. Alembic advanced the dedicated `inalpha_issue107` database from the empty state through the current head (`0043_waitlist`). A direct PostgreSQL verification then returned:

```text
inalpha_issue107|bars
```

confirming that `public.bars` exists in the dedicated benchmark database. The temporary config file was removed in the `finally` block and `git status --short` remained empty afterward.

This closes the migration bootstrap blocker for #107 without changing tracked project files.

## Follow-up

If a future contribution targets Windows bootstrap portability, possible project-level fixes should be evaluated separately (for example making the config consumable without locale-dependent decoding or changing the bootstrap invocation). Do not mix that work into the #107 saturation PR.
