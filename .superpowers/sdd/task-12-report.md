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

### Task 12 Remaining Issues

- Validate persisted `ac_provider` through `getProviderConfig`; invalid values fall back to `DEFAULT_PROVIDER`.
- Add `aria-label` to AI settings gear button.
- Trap modal Tab and Shift+Tab focus while preserving Escape, backdrop close, and focus restoration.
- Backend custom model fetch remains present in `backend/main.py` and `ai_utils.py`; no backend changes made.
- StepInput payload remains unchanged.
