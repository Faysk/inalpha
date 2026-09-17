# Dashboard standalone bridge introspection

Status: contributor-only diagnostic note. This is **not** part of issue #107 and should not be mixed into the upstream #107 PR unless the maintainer explicitly asks for it.

## Why this note exists

After isolating the local `INCOMPLETE_STREAM` symptom above Ollama, the direct OpenAI-compatible protocol, `@ai-sdk/openai-compatible`, and Mastra core `Agent.stream()`, the next diagnostic target became the dashboard's `@ag-ui/mastra` ↔ CopilotKit bridge.

The first runtime-introspection attempt tried to call `require.resolve('@ag-ui/mastra')` from an ad-hoc `node --input-type=module -e` process inside `inalpha-selfhost-dashboard`. That failed with:

```text
Error: Cannot find module '@ag-ui/mastra'
Require stack:
- /app/[eval1]
```

## Classification

This is **not evidence that the dashboard is missing `@ag-ui/mastra` at runtime** and is not currently classified as an Inalpha product bug.

The dashboard image is built as a Next.js 16 **standalone** production image. `infra/docker/Dockerfile.dashboard` installs dependencies in the builder stage, runs `pnpm build`, then copies only `.next/standalone`, `.next/static`, `public`, and messages into the runner image. The Dockerfile explicitly describes the runner payload as `standalone` with only traced runtime files.

Because the `/api/copilotkit` route imports `@ag-ui/mastra` at build time, Next can bundle that dependency into server chunks rather than preserve a normal top-level package that is resolvable from an unrelated `/app/[eval]` module. Therefore `require.resolve()` from an ad-hoc eval process is not a reliable way to prove package presence/absence in this image layout.

## Diagnostic consequence

Runtime bridge inspection must search the built Next server artifacts (`/app/.next/server/**`) for the bundled adapter code and recognizable strings, rather than assuming a conventional `/app/node_modules/@ag-ui/mastra` package root.

This is useful operational knowledge for future self-host debugging: an import that works from the built Next route may still be non-resolvable from `docker exec node -e` because the production image is a bundled/standalone artifact.

## Relevance

- Local/self-host diagnostic relevance: **confirmed**.
- Product/runtime defect: **not established**.
- Production relevance: the same standalone packaging is also used by the production dashboard Dockerfile, so this affects how production containers should be introspected, but does not by itself indicate an application failure.

## Next step

Search the actual `.next/server` JavaScript artifacts in the running dashboard container for the bridge's chunk handling (`text-start`, `text-end`, `step-finish`, terminal `finish`, `RUN_FINISHED`, and the known `Unrecognized stream chunk type` warning). Then exercise the AG-UI bridge directly if the bundled code confirms the expected conversion path.