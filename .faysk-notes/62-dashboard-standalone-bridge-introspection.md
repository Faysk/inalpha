# Dashboard standalone bridge introspection

Status: contributor-only diagnostic note. This is **not** part of issue #107 and should not be mixed into the upstream #107 PR unless the maintainer explicitly asks for it.

## Why this note exists

After isolating the local `INCOMPLETE_STREAM` symptom above Ollama, the direct OpenAI-compatible protocol, `@ai-sdk/openai-compatible`, and Mastra core `Agent.stream()`, the next diagnostic target became the dashboard's `@ag-ui/mastra` ↔ CopilotKit bridge.

## Standalone packaging nuance

The first runtime-introspection attempt tried to call `require.resolve('@ag-ui/mastra')` from an ad-hoc `node --input-type=module -e` process inside `inalpha-selfhost-dashboard`. That failed with:

```text
Error: Cannot find module '@ag-ui/mastra'
Require stack:
- /app/[eval1]
```

This is **not evidence that the dashboard is missing `@ag-ui/mastra` at runtime** and is not classified as an Inalpha product bug.

The dashboard image is built as a Next.js 16 standalone production image. `infra/docker/Dockerfile.dashboard` installs dependencies in the builder stage, runs `pnpm build`, then copies only `.next/standalone`, `.next/static`, `public`, and messages into the runner image. Because `/api/copilotkit` imports `@ag-ui/mastra` at build time, Next may bundle it into server chunks rather than preserve a normal top-level package resolvable from an unrelated `/app/[eval]` module.

Operational consequence: inspect `/app/.next/server/**` (and client static chunks when relevant), not only `node_modules`, when debugging this production image.

## Bundled runtime inspection

A scan of the running dashboard's actual standalone artifacts inspected **422 JavaScript files** under `/app/.next/server` plus `/app/server.js` and located the bundled AG-UI/Mastra adapter and `/api/copilotkit` route in:

```text
/app/.next/server/chunks/[root-of-the-server]__0eltybc._.js
```

### What the installed bridge actually recognizes

The bundled `createChunkProcessor` switch contains the following relevant behavior:

```text
reasoning-start      -> handled
reasoning-delta      -> handled
reasoning-end        -> handled
start                -> ignored intentionally
step-start           -> ignored intentionally
text-delta           -> handled
 tool-call           -> handled
 tool-result         -> handled
error                -> handled / terminal error path
tool-call-suspended  -> handled
finish               -> handled
step-finish          -> handled
other chunk types    -> "Unrecognized stream chunk type" warning
```

Crucially, both Mastra `finish` and `step-finish` are explicitly recognized:

```text
case "finish":
case "step-finish":
  flush();
  onFinishMessagePart?.();
  break;
```

Therefore the earlier hypothesis that the installed `@ag-ui/mastra` bridge simply fails to recognize Mastra's terminal `finish` / `step-finish` chunks is **ruled out**.

### `text-start` / `text-end` mismatch remains real but appears non-terminal

The same switch does not contain `text-start` or `text-end`, so those chunk types fall into the default warning path. This matches the explicit Inalpha workaround that suppresses:

```text
[MastraAgent] Unrecognized stream chunk type: ...
```

The bridge consumes `text-delta`, so text rendering can still proceed. Current evidence therefore supports the existing characterization of `text-start` / `text-end` as a compatibility mismatch/noise source, but **not yet** as the cause of the missing terminal AG-UI event.

### Remote-agent completion path

The bundled remote path is also important. After calling the remote Mastra agent and processing its data stream, the bridge does approximately:

```text
await response.processDataStream({ onChunk: handleChunk })
if no terminal error:
  flush()
  await onRunFinished?.()
```

The boolean used to skip normal completion is set when the chunk processor returns its terminal-error path; healthy `finish` / `step-finish` chunks do not set it. So, on a normally resolved remote stream, the adapter is designed to invoke its higher-level `onRunFinished` callback after `processDataStream` completes.

This materially narrows the fault boundary again: the bridge *contains* a healthy completion path. We still need to prove whether that path is reached in the failing dashboard request and whether its callback actually emits an AG-UI `RUN_FINISHED` event that survives the CopilotKit runtime.

## Why `INCOMPLETE_STREAM` matters

Current CopilotKit sources define `INCOMPLETE_STREAM` specifically for a stream that reaches EOF without a terminal `RUN_FINISHED` or `RUN_ERROR` event. This matches the product symptom: some higher layer believes the stream ended without an AG-UI terminal event.

That does **not** by itself tell us whether the event was never produced, was dropped/transformed incorrectly, or whether the remote `processDataStream` path completed abnormally before the bridge's `onRunFinished` callback.

## Current fault boundary

```text
Ollama raw SSE                         PASS
AI SDK OpenAI-compatible               PASS
Mastra Agent.stream text               PASS
Mastra Agent.stream tools/multi-step   PASS
Mastra terminal finish chunks          recognized by bundled AG-UI bridge
AG-UI onRunFinished callback path       present in bundled bridge
AG-UI RUN_FINISHED emitted at runtime   NOT YET OBSERVED
CopilotKit receives terminal event      NOT YET OBSERVED
Dashboard                              FAILS: INCOMPLETE_STREAM
```

## Classification / production relevance

- Next standalone `require.resolve` failure: diagnostic packaging nuance, **not a product bug**.
- `text-start` / `text-end` unsupported by the installed bridge: **confirmed compatibility mismatch**, currently appears non-terminal because text deltas still flow and terminal Mastra chunks are recognized.
- Missing AG-UI terminal event in the failing end-to-end run: **observed symptom**, producer/drop point still open.
- Production relevance: potentially broader than Ollama because the AG-UI/CopilotKit bridge is provider-independent, but managed-provider impact is not established.

## Next step

Inspect the bundled producer side around `onRunFinished` / `RUN_FINISHED`, then capture the actual AG-UI event sequence for one failing `/api/copilotkit` request. The decisive question is no longer whether Mastra finishes; it is whether the dashboard bridge emits and CopilotKit receives the terminal AG-UI event.

Do not bump dependencies or patch product code until that exact boundary is observed.