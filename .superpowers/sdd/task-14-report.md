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

- `feat: adaptive wizard (3-step AI / 4-step manual)`

Concerns:

- Persisted mode has no backend metadata source. Jobs created before Task 14 with no saved mode fall back to current provider on restore.
