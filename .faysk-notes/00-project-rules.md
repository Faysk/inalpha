# Inalpha — Project Conventions and Business Rules

**Purpose:** contributor-side notes for working on `mirror29/inalpha`, especially issue #107.  
**Contribution branch:** `fix/data-service-saturation`  
**Notes branch:** `notes/issue-107`  
**Reviewed baseline:** `main` around `ed01be9056776c107ab76a404c328a4fed19f529`  
**Last reviewed:** 2026-09-16

> This file is not upstream documentation and should not be included in the PR unless explicitly requested.

---

## 1. Source-of-truth order

When docs disagree, use this order:

1. Current code and tests
2. `docs/04-current-state.md`
3. `docs/01-architecture-overview.md`
4. `AGENTS.md` / `CLAUDE.md`
5. `CONTRIBUTING.md`
6. Service README for the service being changed
7. `docs/00-context.md`
8. `docs/03-kernel-design.md` for design background/history

`docs/03-kernel-design.md` contains historical material; current-state docs/code win.

---

## 2. What Inalpha is

Inalpha is an **AI-agent orchestration × quantitative research** framework.

It is not:

- a plug-and-play strategy product,
- a generic LangChain/AutoGen wrapper,
- a real-money trading platform.

Real-money trading remains intentionally out of scope. The project is alpha-stage and explicitly warns against using real trading capital.

---

## 3. Architecture

### Entry/UI

- `apps/dashboard`: authenticated Operator Console / BFF
- `apps/web`: public static site
- Mastra dev tooling: orchestration debugging/traces

### Orchestration

`packages/orchestration` (TypeScript / Mastra)

Responsibilities include:

- agent routing,
- thin tool adapters,
- identity propagation,
- hooks and permissions,
- plan/approve/execute flows,
- scheduling,
- skills,
- error normalization,
- observability.

**Rule:** tools are thin adapters; Python services own domain/business logic.

### Python services

| Service | Port | Responsibility |
|---|---:|---|
| `data` | 8001 | market data, fundamentals, news, web, FX, constituents, persistence |
| `paper` | 8002 | backtests, paper execution, risk, live runner, strategy state |
| `research` | 8003 | analyst fan-out, debate, synthesis |
| `factor` | 8004 | factor computation/effectiveness/panel/discovery |
| `evolver` | 8005 | owner-scoped strategy evolution and audit |

Persistence: PostgreSQL 17 + TimescaleDB.

---

## 4. Service-boundary invariants

Do not create service import coupling to solve operational problems.

Conceptually:

```text
data   ✗ import other domain services
factor ✗ import paper
paper  ✗ import research
```

Cross-service interaction should remain HTTP/MCP.

For #107 specifically:

- `data-service` must remain generic and unaware of factor-specific business logic,
- factor/paper callers may be improved, but no direct import dependency should be introduced.

---

## 5. Core business invariants

### One strategy code path

Backtest and paper/live behavior should use the same strategy logic, with infrastructure differences such as clock/gateway rather than duplicate strategy implementations.

### Centralized data

Core services consume financial data through `data-service`; they should not independently scrape providers as a workaround.

### No direct LLM order path

The expected order sequence is:

```text
trade.create_plan
→ trade.approve_plan
→ trade.execute_plan
```

LLM reasoning must not bypass permissions, hooks, approval tokens, risk, or persisted audit facts.

### Risk is deterministic

Financial/risk hard constraints belong in code/configuration, not prompts.

### Explicit human boundaries

Examples:

- strategy evolution creates candidates but does not auto-promote/start/trade,
- factor candidate registration remains human-controlled,
- cost-bearing actions require explicit approval,
- live execution requires explicit lifecycle actions.

---

## 6. Financial freshness is a hard rule

Freshness is not just performance tuning.

Important rules:

- current-market analysis should use current/fresh data,
- historical/as-of analysis uses historical semantics (`fresh=False`),
- latest timestamp matters; bar count alone does not prove freshness,
- if current data cannot be refreshed, the system should expose degradation/cutoff rather than silently present stale data as current,
- point-in-time correctness must not be weakened to reduce load.

Therefore a #107 fix must **not** simply change live/current calls from `fresh=True` to `fresh=False`.

---

## 7. Failure semantics

Recurring project rule:

```text
real absence ≠ provider failure
```

The project prefers explicit structured failure states over fake success.

Shared HTTP error shape:

```json
{
  "code": "STABLE_MACHINE_CODE",
  "message": "human-readable message",
  "details": {}
}
```

Stable codes are used by callers/agents to decide whether to retry, degrade, or surface an error.

For #107, any new overload/backpressure result must be designed with the caller behavior in mind.

---

## 8. Observability pattern

Python services already use:

- `structlog`,
- JSON request logs,
- `trace_id`,
- `X-Trace-Id` request/response handling,
- request duration/status logging.

First preference for #107: reuse this before introducing a new telemetry stack.

Potential observation: factor's `DataClient` does not appear to explicitly propagate a caller trace ID to data-service. If cross-service trace correlation becomes necessary, prefer a local client change rather than modifying protected `_shared` infrastructure without maintainer agreement.

---

## 9. Existing concurrency/reliability style

Bounded concurrency is already a normal project pattern.

Examples:

- factor panel fetches: `_PANEL_FETCH_CONCURRENCY = 16`,
- research LLM concurrency via `asyncio.Semaphore`,
- data web search uses configured semaphore + overall timeout,
- live runner/evolver use resource/run caps.

Typical design shape:

```text
configurable limit
+ bounded work
+ timeout
+ explicit status/error
+ observability
```

This makes server-side admission control a natural candidate for #107 **if measurements confirm the need**.

---

## 10. Caching rules

The project uses caching carefully:

- live factor cache TTL is bounded by financial freshness constraints,
- historical `as_of` paths do not use the same live cache semantics,
- empty/failure results should not poison cache,
- future multi-tenant/private dimensions must be represented in cache keys.

General rule:

> Never make an outage or incomplete result sticky by caching it as valid market evidence.

---

## 11. Current #107-relevant behavior

Already present in current `main`:

- `FactorEngine.panel_score()` uses bounded concurrency,
- `_PANEL_FETCH_CONCURRENCY = 16`,
- multi-symbol custom scoring reuses bounded concurrency,
- panel evaluation deliberately avoids forced per-symbol fresh backfills,
- `/backfill/bars` performs incremental continuation from persisted latest bars,
- factor `DataClient.get_bars()` has bounded connection-level retry/backoff.

So issue #107 should be treated as a **current capacity problem statement**, not implemented literally from its June wording.

---

## 12. Important #107 caller interaction

Current live factor path is roughly:

```text
factor current/live score
→ DataClient.get_bars(fresh=True)
→ best-effort POST /backfill/bars
→ GET /bars
```

The current best-effort backfill helper handles transport exceptions, but does not automatically raise on every HTTP non-2xx status.

This matters if we add `429` or `503` overload responses.

A naive design could become:

```text
fresh=True
→ POST /backfill returns busy
→ caller ignores HTTP status
→ GET cached bars
→ stale result is presented as current
```

That would violate the project's freshness rule.

Therefore any backpressure response must be paired with caller semantics that preserve correctness.

---

## 13. Database/resource model

Shared async Postgres pool defaults are roughly:

```text
min_size = 2
max_size = 10
timeout = 30s
```

For #107, distinguish:

- admission wait,
- DB-pool wait,
- provider/network latency,
- DB write latency,
- client connection churn.

Avoid holding scarce DB capacity while waiting on slow external I/O where possible.

---

## 14. Process/deployment caveat

Generic Python images run Uvicorn with configurable workers, but some state/connectors are process-local. Baostock explicitly warns about multi-worker/fork behavior.

A process-local semaphore may therefore be valid for the current deployment shape, but before calling it a global capacity guarantee we should confirm the maintainer's production topology.

---

## 15. Testing style

The repository prefers deterministic tests that isolate the responsibility under test.

`services/data/tests/test_backfill_router.py` is a good model:

- fake connectors,
- no stress against real providers,
- explicit routing/error assertions,
- provider failure must not become fake success.

For #107:

- use fake/delayed connectors for concurrency tests,
- never hammer public market APIs as a load test,
- use controlled integration/load tests separately.

Python service conventions:

- Python >= 3.12
- Ruff
- mypy configured strict
- pytest + pytest-asyncio
- line length 100
- lint families include `E`, `F`, `I`, `UP`, `B`, `ASYNC`, `RUF`

---

## 16. CI reality

PR CI currently covers broad build/type/lint/smoke checks, while required Python pytest coverage is stronger for `paper` and `evolver` than for `data`/`factor`.

For #107 we should still explicitly run and report:

```bash
cd services/data && uv run pytest
cd services/factor && uv run pytest
```

if those services are touched.

Passing required CI alone is not enough evidence for a reliability fix.

---

## 17. Git and collaboration conventions

Default collaboration language: **English**.

Branch naming:

```text
feature/*
fix/*
test/*
docs/*
chore/*
```

Current contribution branch:

```text
fix/data-service-saturation
```

Commit format:

```text
<type>(<scope>): <description>
```

Examples:

```text
test(data): add backfill concurrency regression coverage
fix(data): bound concurrent backfill operations
perf(factor): reuse data-service connections
docs(data): document backfill capacity settings
```

One logical change per commit.

---

## 18. GitHub labels

The repository uses labels in issue triage.

Verified label patterns include service/domain labels such as `data` and type labels such as `enhancement`/`bug`.

Issue #107 currently has no label attached in the issue metadata we inspected.

For a future #107 PR/triage, likely relevant existing labels are:

```text
data
enhancement
```

Do not invent upstream labels in the fork. If we cannot apply upstream labels, leave that to `@mirror29` or mention the intended category in the PR body.

---

## 19. PR process

Architecture/cross-service changes should be discussed before implementation.

For #107 the maintainer explicitly requested a technical proposal, so the work is aligned directionally. Still, keep scope controlled.

The upstream PR template expects:

- English title/body,
- `Fixes #107` for the bug/fix link,
- affected service and change type,
- logical commits,
- `bash scripts/check-consistency.sh`,
- explicit note if hard constraints were touched,
- testing/repro evidence,
- no unapproved modifications to protected areas such as `services/_shared/`, `.mastra/`, or private docs.

All paths are CODEOWNED by `@mirror29`.

A focused data-service fix may target `main`; if work expands into shared infrastructure, large cross-service changes, live-runner core behavior, etc., ask whether `staging` is preferred.

---

## 20. Security

Do not publicly disclose vulnerabilities involving:

- permission bypass,
- secrets/tokens,
- unauthorized order placement,
- service-to-service privilege escalation,
- sensitive supply-chain/security issues.

Use the repository's private security process.

Never commit secrets/private data to this public notes branch.

---

## 21. License

Project license: **AGPL-3.0-only**.

Submitted code is distributed under the same license. New dependencies must be license-compatible.

---

## 22. Engineering culture we should mirror

Recurring project values:

### Evidence before claims

```text
merged code ≠ proven fix
```

Use tests, reproducible runs, logs, and before/after measurements.

### Explicit degradation over fake certainty

If data is incomplete or unavailable, expose that fact.

### Deterministic guardrails over prompts

Security/risk/cost/approval constraints belong in code and persisted state.

### Narrow changes before clever architecture

Do not introduce distributed locks, queues, telemetry stacks, per-provider scheduling, etc. until evidence shows the simpler approach is insufficient.

---

## 23. Consequences for #107

Initial PR should preferably remain data-service scoped.

Use existing patterns:

```text
DataSettings
+ asyncio.Semaphore or equivalent bounded gate
+ bounded wait/timeout if justified
+ stable error semantics
+ structlog fields
+ deterministic fake-connector tests
```

Do **not**:

- reduce freshness guarantees to lower load,
- add a new overload status without checking every caller that matters,
- stress public providers,
- modify `_shared` just for convenience,
- introduce Prometheus/OpenTelemetry in PR 1 unless the maintainer asks,
- tune concurrency by intuition.

Before coding, answer:

1. Can current `main` reproduce #107?
2. Which workload creates saturation?
3. Is the bottleneck application concurrency, event-loop starvation, provider latency, DB pool, connection churn, or another resource?
4. Is duplicate same-key backfill significant?
5. Does one provider monopolize capacity?
6. Does live-runner traffic materially change the result?

Only then choose the fix.

---

## Working rule

> Do not optimize away a business invariant.

For #107, stability only counts as a real fix if freshness, explicit failure semantics, service boundaries, security/owner boundaries, and auditability remain correct.
