# Self-host smoke closeout — return to issue #107

Status: contributor-only diagnostic closeout. This is **not** part of issue #107 and must not be merged into the upstream #107 PR unless the maintainer explicitly asks for it.

## Decision

Stop the local chat/LLM compatibility investigation here and return to the actual contribution target: issue #107 (`data-service` sustained-concurrency saturation).

The self-host investigation was useful as a pre-flight because it proved the stack can be built and exercised locally and because it surfaced several real self-host/debugging issues. It is not required to proceed with the #107 benchmark harness, which exercises the relevant factor/data/DB/provider paths directly and does not depend on the dashboard chat completing successfully.

## What was encountered during local smoke testing

### 1. Windows UTF-8 bootstrap failure

`scripts/selfhost.sh init` invokes embedded Python `Path.read_text()` / `write_text()` without forcing UTF-8. On the tested Windows/CP1252 host, the first init attempt raised `UnicodeDecodeError`.

Workaround used locally: run the script through Git Bash while overriding `python3` to an explicit Python invocation with `-X utf8`.

Classification: credible Windows self-host portability bug / documentation gap. Separate from #107.

### 2. Partial `.env.selfhost` after failed init

The failed init had already created a partial environment file before aborting. The partial file was deleted before a clean rerun.

Classification: self-host robustness/transactionality improvement opportunity. Separate from #107.

### 3. Windows `python3` command ambiguity

In PowerShell, `python3` resolved through the WindowsApps alias rather than the intended installed Python. Explicit interpreter paths or the Git-Bash override were required.

Classification: Windows bootstrap/documentation friction, not an application runtime bug.

### 4. Local Ollama must be configured through `Custom`

The per-user LLM settings UI exposes a `Custom` OpenAI-compatible provider rather than a dedicated Ollama option. Local Ollama also requires a non-empty API-key field even though the local server ignores the bearer token; `ollama` was used as a harmless placeholder.

Classification: UX/documentation improvement opportunity for self-host/local-model users. Not a #107 concern.

### 5. Dashboard chat ends in `INCOMPLETE_STREAM`

The full dashboard path still fails for the tested custom Ollama configuration even though progressively lower layers pass.

Positive controls established:

- Docker/dashboard/mastra connectivity to Ollama: PASS
- Ollama OpenAI-compatible non-streaming: PASS
- Ollama raw SSE text: PASS
- Ollama raw SSE with tools: PASS
- Ollama raw streamed tool call: PASS
- `@ai-sdk/openai-compatible@2.0.48` text stream: PASS
- same AI SDK with advertised tool: PASS
- same AI SDK with real streamed tool call: PASS
- Mastra `Agent.stream()` text-only: PASS
- Mastra tool advertised/not used: PASS
- Mastra real tool execution + continuation: PASS

The failure boundary was therefore narrowed above Mastra core, around the AG-UI/CopilotKit/dashboard integration.

### 6. AG-UI bridge compatibility mismatch is real, but terminal-chunk support exists

The installed/bundled bridge does not recognize Mastra v5 `text-start` / `text-end` chunks; Inalpha already suppresses the resulting `Unrecognized stream chunk type` warnings. `text-delta` remains handled.

However, bundle inspection also proved that `finish` and `step-finish` are explicitly recognized and that the bridge has an `onRunFinished` path which emits AG-UI `RUN_FINISHED` and completes the observable.

Therefore the earlier hypothesis that `INCOMPLETE_STREAM` was simply caused by `@ag-ui/mastra` not recognizing Mastra terminal chunks is ruled out.

### 7. CopilotKit finalizer confirms what `INCOMPLETE_STREAM` means

The bundled CopilotKit `1.59.5` finalizer checks for `RUN_FINISHED` / `RUN_ERROR`; if neither terminal event is present when the run ends, it synthesizes `RUN_ERROR` with code `INCOMPLETE_STREAM`.

The unresolved question is therefore very narrow: in the failing end-to-end request, either the bridge's normal `onRunFinished` path is not reached, the resulting `RUN_FINISHED` is dropped/transformed, or the upstream stream terminates abnormally before that callback completes.

We intentionally stop here because resolving this is not necessary for #107.

### 8. Token usage is empty/zero through Ollama compatibility path

The local OpenAI-compatible Ollama responses expose empty usage fields in the exercised path, and Mastra consequently reports zero token counts.

Classification: accounting/telemetry limitation for local/custom providers; not a stream-completion root cause and unrelated to #107.

### 9. Next.js standalone container introspection nuance

`require.resolve('@ag-ui/mastra')` from an ad-hoc `node -e` process failed inside the dashboard runner image even though the route uses the package successfully. The reason is the Next.js standalone build: runtime dependencies can be bundled into `.next/server` chunks rather than remain conventionally resolvable from `/app`.

Correct debugging technique: inspect `/app/.next/server/**` artifacts rather than assuming a normal top-level `node_modules` layout.

Classification: useful operations/debugging note, not a product bug.

## Production relevance assessment

Do not present all of the above as production bugs.

- Windows init/encoding and interpreter-alias findings are primarily self-host portability concerns.
- Next standalone resolution behavior is packaging/debugging behavior, not a defect.
- Empty token accounting may affect deployments that use similar custom OpenAI-compatible providers.
- The AG-UI/CopilotKit terminal-event failure could theoretically affect providers other than Ollama because the bridge is provider-independent, but no managed-provider production impact has been demonstrated.
- The dashboard chat issue remains an unresolved compatibility finding, not a diagnosed root cause.

## Why this does not block issue #107

The #107 evidence path is intentionally independent of the chat UI:

```text
factor / runner
      -> data-service
      -> DB pool + provider I/O
      -> latency / queueing / timeout / refusal measurements
```

The prepared benchmark tooling uses a dedicated `inalpha_issue107` database, fake/blocked provider routing, fail-closed target checks, bounded probes and result capture outside Git. It does not require the dashboard LLM conversation to work.

No production code change was made for any smoke-test finding.

## Handoff back to #107

Resume from the pre-runtime freeze:

1. verify branch/SHA/clean tree and benchmark safety targets,
2. run Stage A no-load checks,
3. establish the current-main baseline,
4. identify which resource saturates first,
5. only then select the smallest measured fix.

Candidate A (narrow DB lease around external provider I/O) remains **unapplied** until runtime evidence confirms H1.

## Related notes

- `60-local-selfhost-smoke-findings.md` — living smoke findings and classifications
- `61-llm-stream-isolation.md` — layered Ollama/AI-SDK/Mastra isolation evidence
- `62-dashboard-standalone-bridge-introspection.md` — bundled AG-UI/CopilotKit inspection

This file is the stop point for that detour unless a maintainer later asks for the local/self-host findings or a future contribution specifically targets them.