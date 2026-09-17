# Local LLM stream isolation — self-host smoke test

Status: contributor-only diagnostic note. This is **not** part of issue #107 and must not be merged into the upstream #107 PR unless the maintainer explicitly asks for it.

## Scope

This note isolates the `INCOMPLETE_STREAM` failure observed while smoke-testing current `main` with a local Ollama provider configured through the dashboard's `Custom` OpenAI-compatible path.

Tested environment:

- Inalpha current main at `ed01be9056776c107ab76a404c328a4fed19f529`
- Windows host + Docker Desktop self-host stack
- Ollama `0.34.1`
- model `qwen3:8b`
- `@ai-sdk/openai-compatible@2.0.48`
- custom base URL `http://host.docker.internal:11434/v1`

## Product-level symptom

The dashboard successfully saves and activates the user-owned custom provider configuration. The failing inference trace reaches Mastra with:

- model `qwen3:8b`
- provider `Ollama Local.chat`
- `streaming=true`
- the expected custom base URL
- the user LLM config present in the request

The dashboard then reports `INCOMPLETE_STREAM` and does not render a completed assistant response.

This is a real end-to-end failure for the tested self-host/custom-Ollama path, but the root cause is not yet assigned to Inalpha, Ollama, AI SDK, Mastra, AG-UI, or CopilotKit.

## Positive controls

The following layers already passed:

1. Dashboard container can call `GET /v1/models` on Ollama and sees `qwen3:8b`.
2. Direct non-streaming OpenAI-compatible chat completion succeeds.
3. Direct non-streaming tool calling succeeds with a valid function call and `finish_reason=tool_calls`.
4. Raw SSE, no tools: `HTTP 200`, `text/event-stream`, terminal `finish_reason=stop`, `[DONE]`, clean close.
5. Raw SSE, tools advertised but not invoked: same healthy termination.
6. Raw SSE, real forced tool call: Ollama emits `get_price({"symbol":"BTC"})`, then `finish_reason=tool_calls`, `[DONE]`, clean close.
7. Direct `@ai-sdk/openai-compatible@2.0.48` `model.doStream()` text-only succeeds and cleanly produces reasoning events, text events, then `finish` with unified/raw `stop`.
8. Direct AI-SDK `doStream()` with a tool advertised but not invoked completes normally and finishes with `stop`.
9. Direct AI-SDK `doStream()` with a real tool call completes normally and finishes with unified `tool-calls` / raw `tool_calls`.
10. Minimal Mastra `Agent.stream()` text-only completes normally through terminal `finish`; final promises resolve.
11. Minimal Mastra `Agent.stream()` with a tool advertised but explicitly not used completes normally: text is returned, `finishReason=stop`, and the synthetic tool executes zero times.
12. Minimal Mastra multi-step tool flow completes normally: the first step emits a streamed `get_price({"symbol":"BTC"})` call, the tool executes exactly once, Mastra marks the step `reason=tool-calls` and `isContinued=true`, starts a second model step with the tool result in history, emits `MASTRA TOOL OK`, then terminates with `finishReason=stop`.

Therefore current evidence rules out generic Docker/Ollama connectivity, generic SSE framing failure, missing `[DONE]`, premature socket close, raw streamed tool-call termination, Ollama reasoning deltas by themselves, the AI SDK 2.0.48 adapter for the direct cases exercised, and Mastra core `Agent.stream()` including a real two-step tool execution/continuation path.

## AI SDK boundary

Runtime introspection of the exact installed provider produced:

```text
provider= ollama-test.chat
modelId= qwen3:8b
specificationVersion= v3
own= [
  'specificationVersion',
  'modelId',
  'config',
  'chunkSchema',
  'failedResponseHandler',
  'supportsStructuredOutputs'
]
proto= [
  'constructor',
  'provider',
  'providerOptionsName',
  'supportedUrls',
  'transformRequestBody',
  'convertUsage',
  'getArgs',
  'doGenerate',
  'doStream'
]
```

This confirms that the installed `@ai-sdk/openai-compatible@2.0.48` object is a LanguageModel V3 implementation exposing `doStream` directly.

### AI SDK controls passed

Text-only:

```text
stream-start
response-metadata
reasoning-start ...
reasoning-end ...
text-start id=txt-0
text-delta ...
text-end id=txt-0
finish unified=stop raw=stop
```

Tool advertised but not invoked:

```text
stream-start
response-metadata
reasoning-start ...
reasoning-end ...
text-start id=txt-0
text-delta ...
text-end id=txt-0
finish unified=stop raw=stop
```

Real tool call:

```text
stream-start
response-metadata
reasoning-start ...
reasoning-end ...
tool-input-start id=<call-id> toolName=get_price
tool-input-delta id=<call-id> delta={"symbol":"BTC"}
tool-input-end id=<call-id>
tool-call toolName=get_price input={"symbol":"BTC"}
finish unified=tool-calls raw=tool_calls
```

These controls materially move the fault boundary above the direct AI-SDK provider adapter for the cases tested.

## Mastra boundary

### Text-only passed

Minimal `@mastra/core` `Agent.stream()` using the same model produced:

```text
start
step-start
reasoning-start / reasoning-delta / reasoning-end
text-start id=txt-0
text-delta ...
text-end id=txt-0
step-finish reason=stop
finish reason=stop
```

Final promises resolved as:

```text
text= MASTRA STREAM OK
finishReason= stop
usage= {"totalTokens":0,"raw":{"inputTokens":{},"outputTokens":{}}}
```

### Tool advertised but not used passed

The agent received the `get_price` tool but was told not to call it. It emitted normal text, `step-finish reason=stop`, terminal `finish`, and:

```text
text= MASTRA TOOLS OK.
finishReason= stop
toolExecutionsThisRun= 0
```

The extra period is a model instruction-following detail, not a streaming failure.

### Real tool execution + continuation passed

The agent was required to call `get_price` for BTC and then produce a fixed response. The stream showed the complete multi-step lifecycle:

```text
step-start
reasoning-start / reasoning-end
tool-call-input-streaming-start
tool-call-delta {"symbol":"BTC"}
tool-call-input-streaming-end
tool-call get_price({"symbol":"BTC"})
tool-result {"symbol":"BTC","price":123.45,"source":"synthetic-test"}
step-finish reason=tool-calls isContinued=true
step-start                         # second model call
reasoning-start / reasoning-end
text-start id=txt-0
text-delta ...
text-end id=txt-0
step-finish reason=stop isContinued=false
finish reason=stop
```

Final state:

```text
text= MASTRA TOOL OK
finishReason= stop
toolExecutionsThisRun= 1
ALL TOOL EXECUTIONS= [{"symbol":"BTC"}]
```

This is strong evidence that Mastra core itself correctly handles the exact class of multi-step stream that was previously still open: streamed tool input, tool execution, tool result injection, continuation, final text, and terminal completion.

### Adjacent usage-accounting observation

Ollama's OpenAI-compatible usage fields arrive empty in these controls, so Mastra reports zero token counts. This may affect accounting, telemetry, limits, or cost displays for local/custom providers, but it does not prevent stream completion and is not the `INCOMPLETE_STREAM` root cause.

## AG-UI / CopilotKit compatibility seam now becomes primary

The dashboard bridge itself already documents a known dependency mismatch:

- `@ag-ui/mastra@1.0.3`
- `@copilotkit/runtime@1.59.5`
- `@copilotkit/react-core@1.59.5`

The lockfile records that `@ag-ui/mastra@1.0.3` expects the prerelease peer `@copilotkit/runtime@0.0.0-mme-ag-ui-0-0-46-20260227141603`, while Inalpha intentionally runs stable CopilotKit `1.59.5` instead.

The Inalpha `/api/copilotkit` route also contains an explicit compatibility workaround: it globally filters `[MastraAgent] Unrecognized stream chunk type` warnings because `@ag-ui/mastra@1.0.3` does not recognize Mastra v5 `text-start` / `text-end` chunks. The route comment states that `text-delta` still renders and treats those warnings as benign.

This mismatch is **not yet proven to be the `INCOMPLETE_STREAM` cause**, but after the raw provider, AI SDK, and Mastra multi-step controls all passed, it is now the strongest concrete compatibility seam to inspect next. In particular, we need to verify whether the installed bridge recognizes the current Mastra terminal `finish` / `step-finish` shapes and emits the AG-UI run-completion event expected by CopilotKit 1.59.5.

Do not infer from the existing warning filter that all newer Mastra chunk differences are harmless; that claim must be verified against the actual installed bridge code and observed output.

## Relevant upstream AI SDK bug found

Vercel AI SDK issue `vercel/ai#15789` documents a confirmed bug in `@ai-sdk/openai-compatible@2.0.48`: the adapter reused the synthetic text-part ID `txt-0` across separate text segments in a multi-step `text -> tool -> text` stream.

Important limitation: **this is not proof that #15789 causes our `INCOMPLETE_STREAM`.** Our direct AI-SDK controls and Mastra multi-step control all pass. The upstream bug remains useful background for text-part identity across more complex adapters, but it is no longer the primary fault candidate for the current first-message product failure.

A blind dependency bump remains inappropriate until the first failing layer is identified.

## Current fault boundary

```text
Ollama raw OpenAI-compatible SSE          PASS
  - plain text                            PASS
  - tools advertised                     PASS
  - actual streamed tool call            PASS

@ai-sdk/openai-compatible 2.0.48          PASS for tested direct paths
  - text + reasoning doStream             PASS
  - tools advertised doStream             PASS
  - actual tool-call doStream             PASS

Mastra Agent.stream                       PASS for tested core paths
  - text-only                             PASS
  - tool advertised, not used             PASS
  - real tool execution + continuation    PASS

@ag-ui/mastra 1.0.3 bridge                NEXT / primary seam
CopilotKit runtime 1.59.5                 OPEN
Dashboard                                 FAILS with INCOMPLETE_STREAM
```

## Next decision ladder

1. Inspect the exact installed `@ag-ui/mastra@1.0.3` bridge code in the dashboard container and list which Mastra chunk types it recognizes, especially `text-start`, `text-end`, `step-finish`, and terminal `finish`.
2. Confirm exact runtime-resolved package versions in the dashboard container, not just manifest ranges.
3. Exercise the AG-UI bridge directly if practical, bypassing React rendering, and verify whether it emits AG-UI `RUN_STARTED`, text events, and terminal `RUN_FINISHED` for the same healthy Mastra stream.
4. Only after that decide whether the defect is in the AG-UI bridge, CopilotKit runtime consumption, or dashboard integration.

Do not modify production code or bump dependencies before this boundary test.

## Production relevance

- **Confirmed:** the tested local/private self-host path using Ollama through `Custom` is currently unusable end-to-end.
- **Possible broader relevance:** the bridge mismatch is not Ollama-specific. Any deployment exercising the same `@ag-ui/mastra@1.0.3` + CopilotKit `1.59.5` pairing against the current Mastra stream shape could theoretically be affected.
- **Not established:** managed-provider production paths are affected; provider choice may alter stream details, and current evidence comes from the Ollama/custom-provider path.
- **Narrowed finding:** raw provider streaming, direct AI-SDK streaming, and Mastra core multi-step streaming are healthy. The first unvalidated layer is now the AG-UI/CopilotKit bridge.
- **Adjacent telemetry note:** token usage is observed as zero/empty for this Ollama-compatible path; treat separately from stream completion.

## Maintainer presentation rule

If surfaced later, present this as a layered compatibility finding with positive controls, not as "Ollama is broken", "AI SDK streaming is broken", or "Mastra is broken". The useful evidence is that the exact provider/model/AI-SDK combination and Mastra core—including real tool continuation—complete cleanly while the full product path still ends as `INCOMPLETE_STREAM`.