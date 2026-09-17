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

This is a real end-to-end failure for the tested self-host/custom-Ollama path, but the root cause is not yet assigned to Inalpha, Ollama, AI SDK, Mastra, or AG-UI/CopilotKit.

## Positive controls

The following layers already passed:

1. Dashboard container can call `GET /v1/models` on Ollama and sees `qwen3:8b`.
2. Direct non-streaming OpenAI-compatible chat completion succeeds.
3. Direct non-streaming tool calling succeeds with a valid function call and `finish_reason=tool_calls`.
4. Raw SSE, no tools: `HTTP 200`, `text/event-stream`, terminal `finish_reason=stop`, `[DONE]`, clean close.
5. Raw SSE, tools advertised but not invoked: same healthy termination.
6. Raw SSE, real forced tool call: Ollama emits `get_price({"symbol":"BTC"})`, then `finish_reason=tool_calls`, `[DONE]`, clean close.
7. Direct `@ai-sdk/openai-compatible@2.0.48` `model.doStream()` text-only succeeds and cleanly produces `stream-start`, `response-metadata`, `reasoning-start`/`reasoning-delta`/`reasoning-end`, `text-start`/`text-delta`/`text-end`, then `finish` with unified/raw `stop`.
8. Direct AI-SDK `doStream()` with a tool advertised but not invoked also completes normally with reasoning events, one `txt-0` text part, and `finish` with unified/raw `stop`.
9. Direct AI-SDK `doStream()` with a real tool call also completes normally: `tool-input-start` → `tool-input-delta` containing `{"symbol":"BTC"}` → `tool-input-end` → `tool-call`, then `finish` with unified `tool-calls` / raw `tool_calls`.

Therefore current evidence rules out generic Docker/Ollama connectivity, generic SSE framing failure, missing `[DONE]`, premature socket close, raw streamed tool-call termination, Ollama reasoning deltas by themselves, and the AI SDK 2.0.48 parser/adapter for the single-step text and single-step tool-call cases we exercised.

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
reasoning-start id=reasoning-0
reasoning-delta ...
reasoning-end id=reasoning-0
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

## Relevant upstream AI SDK bug found

Vercel AI SDK issue `vercel/ai#15789` documents a confirmed bug in `@ai-sdk/openai-compatible@2.0.48`: the adapter reused the synthetic text-part ID `txt-0` across separate text segments in a multi-step `text -> tool -> text` stream. The reporter observed the problem through Mastra's React adapter, and the issue was later classified/reproduced as a bug.

Important limitation: **this is not proof that #15789 causes our `INCOMPLETE_STREAM`.** Our direct AI-SDK single-step controls all pass. The upstream bug concerns multi-step text/tool/text part identity and ordering, so it remains relevant only if a higher-level Mastra flow introduces multiple model steps or if later UI adaptation depends on these IDs.

Also, upstream reproduction notes show the duplicate-ID behavior existed in later 2.0.x and even a later 3.0.x snapshot at the time of reproduction. Therefore a blind dependency bump is still not an evidence-based correction.

Conclusion: retain #15789 as a related compatibility seam, not as the current root cause.

## Current fault boundary

```text
Ollama raw OpenAI-compatible SSE          PASS
  - plain text                            PASS
  - tools advertised                     PASS
  - actual streamed tool call            PASS

@ai-sdk/openai-compatible 2.0.48          PASS for tested single-step paths
  - text + reasoning doStream             PASS
  - tools advertised doStream             PASS
  - actual tool-call doStream             PASS

Mastra Agent.stream adaptation            NEXT
AG-UI / CopilotKit adaptation             OPEN
Dashboard                                 FAILS with INCOMPLETE_STREAM
```

## Next decision ladder

1. Minimal `@mastra/core` `Agent.stream()` using the same OpenAI-compatible model, no tools, inspect `fullStream` and final promises.
2. Minimal Mastra agent with one tool advertised but not used.
3. Minimal Mastra agent with one real tool execution and continuation if supported by the local test.
4. If Mastra is healthy, isolate the AG-UI/CopilotKit bridge and completion-event handling.

Do not modify production code or bump dependencies until the first failing layer is identified.

## Production relevance

- **Confirmed:** the tested local/private self-host path using Ollama through `Custom` is currently unusable end-to-end.
- **Possible broader relevance:** any deployment using an OpenAI-compatible custom provider plus the same Mastra/UI stack could encounter a higher-layer adapter problem.
- **Not established:** managed-provider production paths are affected.
- **Narrowed finding:** the raw provider and direct AI-SDK single-step streams are healthy, so current evidence points above those layers.

## Maintainer presentation rule

If surfaced later, present this as a layered compatibility finding with positive controls, not as "Ollama is broken" or "AI SDK streaming is broken". The useful evidence is that the exact provider/model/AI-SDK combination completes cleanly in direct controls while the full product path still ends as `INCOMPLETE_STREAM`.