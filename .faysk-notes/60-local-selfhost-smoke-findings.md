# Local self-host smoke-test findings

Status: living contributor note. This is **not** part of the #107 production change and must not be merged into the upstream PR unless the maintainer explicitly asks for it.

Purpose: record bugs, portability problems, compatibility gaps, misleading diagnostics, and useful improvement ideas encountered while trying to run and smoke-test current `main` locally. Some findings are local/self-host only; others may also matter in deployed environments. Each item is classified so we do not accidentally present a local setup quirk as a production defect.

## Classification

- **Confirmed bug** — behavior is directly reproducible and the relevant code path explains it.
- **Observed failure, root cause open** — failure is real, but ownership has not yet been isolated.
- **UX/docs improvement** — product can work, but setup or behavior is unnecessarily confusing.
- **Observability improvement** — runtime may be healthy, but logs/errors are noisy or misleading.
- **Known dependency constraint** — already acknowledged by the codebase; record only because it affected diagnosis.

For every item, keep a separate **production relevance** assessment.

---

## SH-01 — Windows selfhost init is encoding-sensitive

**Classification:** Confirmed portability bug.

**Observed:** `bash scripts/selfhost.sh init` failed when Git Bash invoked native Windows Python 3.13. The embedded Python uses `Path.read_text()` / `Path.write_text()` without an explicit encoding; native Windows Python therefore used the Windows locale codec and failed decoding UTF-8 content in `infra/.env.selfhost`.

Representative failure:

```text
UnicodeDecodeError: 'charmap' codec can't decode byte ...
```

**Local workaround used:** invoke Python with UTF-8 mode (`python.exe -X utf8`). Init then completed and all generated secrets/keys were present.

**Suggested correction:** use explicit UTF-8 in the embedded script, e.g. `read_text(encoding="utf-8")` and `write_text(..., encoding="utf-8")`. This is preferable to relying on shell locale or `PYTHONUTF8`.

**Production relevance:** low for an already-deployed Linux stack; meaningful for Windows contributors/operators following the official self-host path. This is an onboarding/self-host portability issue, not a data-service runtime issue.

---

## SH-02 — Failed selfhost init can leave a partial `.env.selfhost`

**Classification:** Confirmed bootstrap robustness bug.

**Observed:** after the encoding failure above, `infra/.env.selfhost` existed but still contained unresolved placeholders such as `__POSTGRES_PASSWORD__` / `__REDIS_PASSWORD__`. A subsequent clean retry required deleting the partial file first.

**Risk:** a failed init can leave a file that looks provisioned but is invalid; if init intentionally refuses to overwrite an existing file, recovery is less obvious and automation can become non-idempotent.

**Suggested correction:** generate into a temporary file, validate that no required placeholders remain, then atomically replace `infra/.env.selfhost` only after all secret/key generation and substitutions succeed. Clean up the temporary file on failure.

**Production relevance:** low after successful deployment, but meaningful to self-host reliability and disaster/rebuild workflows on any platform.

---

## SH-03 — Windows `python3` command expectation is fragile

**Classification:** UX/docs improvement.

**Observed:** the machine had Python 3.12/3.13 installed, but PowerShell `python3` resolved to the WindowsApps alias rather than a usable interpreter. Git Bash therefore needed an explicit mapping to native Windows Python for `selfhost.sh init`.

**Suggested improvement:** document the requirement more precisely for Windows/Git Bash, or make the helper resolve `python3`, then `python`, with a clear version/error message before creating any files.

**Production relevance:** local contributor/self-host setup only.

---

## LLM-01 — Per-user UI has no direct Ollama provider despite orchestration supporting Ollama

**Classification:** UX/docs/product consistency improvement.

**Observed:** orchestration has an `ollama` provider path, but the dashboard per-user LLM provider type intentionally excludes Ollama. Local Ollama therefore has to be configured as `Custom` using its OpenAI-compatible endpoint.

Working local configuration:

```text
provider             = Custom
custom endpoint      = http://host.docker.internal:11434/v1
custom provider name = Ollama Local
model                = qwen3:8b
api key              = non-empty placeholder
```

The dashboard form requires a non-empty API key even though a default local Ollama server normally does not require one.

**Suggested improvement options:**

1. document Ollama explicitly as a supported `Custom` self-host recipe; or
2. expose an `ollama` per-user provider and allow a keyless local configuration while still requiring credentials for generic custom providers.

The second option should remain provider-specific; generic `custom` should not silently weaken credential assumptions.

**Production relevance:** high for local/private self-host users; lower for hosted deployments that use managed providers. Could also help production deployments that intentionally use an internal Ollama/OpenAI-compatible endpoint.

---

## LLM-02 — Ollama custom-provider streaming ends as `INCOMPLETE_STREAM`

**Classification:** Observed failure, root cause open. **Do not yet call this an Inalpha bug.**

**Observed end-to-end behavior with `qwen3:8b`:**

- Ollama local API responds on `127.0.0.1:11434`.
- Mastra container reaches Ollama through `host.docker.internal:11434`.
- Dashboard container reaches `GET /v1/models` and sees `qwen3:8b`.
- Direct non-streaming `POST /v1/chat/completions` succeeds.
- Direct OpenAI-compatible tool-calling succeeds and returns a valid `tool_calls` payload with `finish_reason=tool_calls`.
- Inalpha receives the active user config and starts model inference with `model=qwen3:8b`, provider `Ollama Local.chat`, `streaming=true`, and the expected custom endpoint.
- The dashboard then reports `Agent reply failed ... (INCOMPLETE_STREAM)` and no assistant message completes.

This isolates the failure above basic connectivity, model loading, credential validation, and non-streaming tool calling.

### Isolation update — raw SSE control passed

A raw `stream:true` request was executed from inside the same Mastra container directly against Ollama's OpenAI-compatible `/v1/chat/completions` endpoint, without Mastra/AI-SDK/AG-UI adaptation. The response was `HTTP 200`, `Content-Type: text/event-stream`, emitted reasoning chunks followed by normal content chunks, then produced a terminal chunk with `finish_reason="stop"`, followed by `data: [DONE]`, and the response body closed cleanly.

That means the **basic no-tools Ollama OpenAI-compatible SSE framing and termination path is healthy in this environment**. The original `INCOMPLETE_STREAM` therefore should no longer be described as a generic inability of Ollama to stream. The remaining failure boundary is narrower: tool-capable streaming and/or one of the adapters above the raw HTTP stream.

The installed orchestration dependency was also confirmed at runtime as:

```text
@ai-sdk/openai-compatible@2.0.48
```

**What this rules out:**

- Docker-to-Ollama connectivity;
- plain OpenAI-compatible streaming transport failure;
- missing terminal `finish_reason` in a simple no-tools stream;
- missing `[DONE]` in a simple no-tools stream;
- premature socket/body closure in that control case.

**What it does not yet rule out:**

- Ollama streaming behavior when `tools` are present;
- streamed tool-call delta shape/assembly;
- handling of Ollama's separate `reasoning` deltas by `@ai-sdk/openai-compatible`;
- AI SDK stream completion semantics;
- Mastra stream adaptation;
- AG-UI/CopilotKit completion-event handling.

**Current suspects, not conclusions:**

- tool-capable Ollama OpenAI-compatible streaming shape;
- `@ai-sdk/openai-compatible` 2.0.48 streaming/tool-call/reasoning handling;
- Mastra stream adaptation;
- AG-UI/CopilotKit stream adaptation/termination.

The request advertises many tools even for a trivial chat prompt, so the tool-capable streaming path is in play even when the model does not need to call a tool.

**Next isolation ladder:**

1. raw `stream:true` OpenAI-compatible request with tools present but a prompt that should not invoke a tool;
2. raw streamed request that deliberately invokes one tool and inspect tool-call deltas plus termination;
3. minimal `@ai-sdk/openai-compatible` streaming call without Mastra;
4. minimal Mastra stream without AG-UI/CopilotKit;
5. full dashboard path.

Only after the failing layer is identified should we propose a dependency bump, adapter workaround, or Ollama-specific change.

**Production relevance:** definite for self-host/custom Ollama users. Potentially broader if another OpenAI-compatible custom provider produces the same stream shape. Not evidence of a production issue for official managed providers yet.

---

## OBS-01 — Repeated `config: null` LLM errors are misleading beside a valid configured request

**Classification:** Observability improvement; semantic status still under investigation.

**Observed:** logs repeatedly emit:

```text
[llm] resolveModel called, config: null AUTH_ENABLED: true
[llm] AUTH_ENABLED=true but no user config in ALS
```

At the same time, the actual failing inference trace clearly contains the active `X-LLM-Config`, model `qwen3:8b`, and custom provider. Therefore at least some of the `config:null` lines come from separate requests/code paths and must not be interpreted as proof that the configured chat request lost its LLM config.

**Suggested improvement:** include route/request/trace context in these messages, reduce repeated error-level noise for requests that do not actually require an LLM, and/or deduplicate identical warnings. This would make incident diagnosis much safer.

**Production relevance:** potentially medium. Misleading logs are an operations issue even if runtime behavior is correct.

---

## OBS-02 — Initial memory lookup logs `Thread not found` as an error

**Classification:** Observed behavior; likely observability/initialization issue unless shown user-visible.

**Observed:** before a successful conversation existed, Mastra logged an error for:

```text
GET /memory/threads/:threadId
Error: Thread not found
```

**Open question:** is this an expected first-load lookup before thread creation, a frontend ordering race, or a genuine broken thread lifecycle?

**Suggested investigation:** reproduce from a clean session and correlate the request with dashboard behavior. If expected, return/handle a normal not-found state without a stack-trace-level error. If it blocks conversation creation, treat as a product bug instead.

**Production relevance:** potentially broad because the path is not Ollama-specific.

---

## OBS-03 — Storage provider reports unsupported batch logs/metrics

**Classification:** Observability/dependency capability gap; impact unknown.

**Observed warnings:** 

```text
This storage provider does not support batch creating logs
This storage provider does not support batch creating metrics
```

**Open question:** are only optional telemetry batches dropped, or is useful operational data lost?

**Suggested investigation:** identify the configured storage implementation and whether Mastra can feature-detect/disable unsupported batching. If expected in self-host, suppress or downgrade the warning after the first occurrence; if telemetry is expected, use a compatible storage path.

**Production relevance:** depends on deployment storage backend. Could be self-host-only or could affect any deployment using the same provider.

---

## DEP-01 — Existing AG-UI/CopilotKit peer-version mismatch remains relevant to stream diagnosis

**Classification:** Known dependency constraint, not a newly discovered bug.

The dashboard source already documents that `@ag-ui/mastra` 1.0.3 expects a prerelease CopilotKit runtime while the project deliberately uses stable CopilotKit 1.59.x. The code states the used APIs were tested for normal message/history/stop flows.

**Why record it here:** the current failure is specifically a stream-completion failure, so this known compatibility seam belongs in the isolation matrix. It must not be blamed without a minimal reproducer.

**Production relevance:** potentially broad because the same dashboard packages are used outside the local Ollama scenario.

---

## Positive controls already established

These are useful because they prevent future investigation from re-opening layers that already passed:

- self-host stack builds and all services become healthy;
- only dashboard is host-published (`127.0.0.1:3001`) in the tested self-host stack;
- login/user creation works;
- working tree remains clean after ordinary self-host use;
- Ollama `qwen3:8b` runs on GPU and exposes the OpenAI-compatible API;
- Mastra container can reach Ollama;
- dashboard container can validate `/v1/models` and see the model;
- direct non-streaming completion works;
- direct tool-calling works with a valid function call;
- direct raw no-tools SSE streaming completes with `finish_reason=stop`, `[DONE]`, and a clean body close;
- per-user encrypted LLM config is saved, activated, decrypted, and forwarded into the failing inference request.

---

## Presentation rule for future maintainer discussion

Do not dump this list as a bag of complaints. For each item we eventually surface, present:

1. exact environment/path where it occurred;
2. shortest reproducible evidence;
3. whether it affects local self-host, contributor setup, or potentially production;
4. whether root cause is confirmed or still open;
5. smallest sensible correction or documentation improvement;
6. why it is intentionally separate from the #107 production patch.

The goal is to give the maintainer useful, low-noise feedback from a real first-time local bring-up without conflating self-host friction with the data-service saturation contribution.