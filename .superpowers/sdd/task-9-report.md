## Task 9 Report

- Status: implemented provider registry in `web/src/lib/providers.ts`.
- Scope: added OpenAI, Gemini, DeepSeek, Groq, OpenRouter, xAI, Mistral, custom OpenAI-compatible/9router, and manual providers.
- Default: preserved web default `manual_ai`.
- Verification: `git diff --check` passed.
- Build: `cd web && npm run build` blocked because dependencies are unavailable; `tsc` was not recognized.
- Concerns: build should run after installing web dependencies.
