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

Therefore current evidence rules out generic Docker/Ollama connectivity, generic SSE framing failure, missing `[DONE]`, premature socket close, and raw streamed tool-call termination as the reproducer.

## AI SDK boundary confirmed

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

This confirms that the installed `@ai-sdk/openai-compatible@2.0.48` object is a LanguageModel V3 implementation exposing `doStream` directly. The next isolation step is therefore a minimal direct `doStream()` test inside the Mastra container, bypassing Mastra/AG-UI/CopilotKit while retaining the AI SDK parser/adapter.

## Relevant upstream AI SDK bug found

Vercel AI SDK issue `vercel/ai#15789` documents a confirmed bug in `@ai-sdk/openai-compatible@2.0.48`: the adapter reused the synthetic text-part ID `txt-0` across separate text segments in a multi-step `text -> tool -> text` stream. The reporter observed the problem through Mastra's React adapter, and the issue was later classified/reproduced as a bug.

Important limitation: **this is not yet proof that #15789 causes our `INCOMPLETE_STREAM`.** That upstream bug is primarily about text-part identity/order across multi-step tool flows, while our current failure also occurs on a trivial first chat request. It is nevertheless a highly relevant compatibility seam because:

- Inalpha currently uses the exact originally reported `@ai-sdk/openai-compatible@2.0.48` version;
- the failing path is a streamed, tool-capable OpenAI-compatible model path through Mastra/UI adapters;
- upstream reproduction notes show the same `txt-0` behavior also existed in later 2.0.x and even a later 3.0.x snapshot at the time of reproduction, so a blind dependency bump is **not** an evidence-based fix.

Conclusion: record #15789 as a related upstream bug and diagnostic clue, not as the current root cause.

## Current fault boundary

```text
Ollama raw OpenAI-compatible SSE          PASS
  - plain text                            PASS
  - tools advertised                     PASS
  - actual streamed tool call             PASS

@ai-sdk/openai-compatible 2.0.48          NEXT
Mastra stream adaptation                  OPEN
AG-UI / CopilotKit adaptation             OPEN
Dashboard                                 FAILS with INCOMPLETE_STREAM
```

## Next decision ladder

1. Direct `model.doStream()` through `@ai-sdk/openai-compatible@2.0.48`, text-only.
2. Direct `model.doStream()` with a tool advertised but not invoked.
3. Direct `model.doStream()` with a real tool call.
4. If AI SDK output is healthy, test minimal Mastra streaming without AG-UI/CopilotKit.
5. If Mastra is healthy, isolate the AG-UI/CopilotKit bridge and completion event handling.

Do not modify production code or bump dependencies until the first failing layer is identified.

## Production relevance

- **Confirmed:** the tested local/private self-host path using Ollama through `Custom` is currently unusable end-to-end.
- **Possible broader relevance:** any deployment using an OpenAI-compatible custom provider plus the same AI-SDK/Mastra/UI stack could encounter an adapter-level problem.
- **Not established:** managed-provider production paths are affected.

## Maintainer presentation rule

If surfaced later, present this as a layered compatibility finding with positive controls, not as "Ollama is broken" or "Inalpha streaming is broken". The useful evidence is precisely that the raw provider stream is valid and the failure appears only after higher-level adaptation.