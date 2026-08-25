# Task 14 Report

Status: complete

Changes:

- Added 3-step AI and 4-step manual wizard configurations with mode-aware navigation layout.
- Captured provider mode when creating jobs and persisted it as `ac_active_job_mode`.
- Restored active job mode from storage and used captured mode for status-to-step synchronization and result rendering, so settings changes do not remap active jobs.
- Preserved existing restore, reset, cancel, and retry behavior; reset and retry clear persisted mode.

Verification:

- `cd web && npm run build`: passed

Commit:

- `ba3cb96 feat: adaptive wizard (3-step AI / 4-step manual)`
- Follow-up: extracted `getSteps(mode)` helper required by Task 14 interface.

Concerns:

- Persisted mode has no backend metadata source. Jobs created before Task 14 with no saved mode fall back to current provider on restore.

Review follow-up:

- Clamped persisted/current step 4 to step 3 for AI mode and reset stale steps when no active job remains.
- Clamped persisted steps to step 1 when no active job ID exists, preventing invalid step 4 initialization.
- History resume fetches job metadata, derives mode from `mode`/`provider` with safe provider fallback, persists mode, then starts polling and routes to wizard.
- Added `provider` and `mode` fields to frontend job metadata typing.
- No frontend test runner exists in `web/package.json`; verification uses production build.
