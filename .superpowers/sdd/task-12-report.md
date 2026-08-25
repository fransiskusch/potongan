### Task 12 Report

- Implemented `AISettingsProvider` and `useAISettings()` with guarded localStorage persistence for provider, model, API keys, custom base URL, and custom model name.
- Added `AISettingsModal` with provider selection, local-only API key fields, custom provider fields, manual mode, model selection, model fetching, and API key testing.
- Mounted provider, modal, and AI settings gear control in `web/src/App.tsx`.
- Verification: `cd web && npm run build` passes.
- Commit: `feat: add AI settings context + modal to web`.

### Task 12 Findings Fixes

- Use provider `supportsModelFetch` config for Fetch Models visibility instead of provider ID special case.
- Validate persisted `ac_api_keys` JSON as plain object with string values; invalid data falls back to empty object.
- Select first fetched model when persisted/current model is empty or absent from fetched models.
- Add modal Escape close, backdrop close, initial provider focus, and focus restoration on close.
- StepInput job payload and backend unchanged; Task 13 owns payload wiring.
- Verification: `cd web && npm run build` passes.
