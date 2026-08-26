# Task 2 Report: Wire Notifier into Job Finalize

## Status

Implemented on branch `feat/web-ai-drive`.

## Requirements

- `_finalize_job` calls `notify_job_finished` for `DONE` and `ERROR`.
- Notification call happens before `save_history`.
- Notification failures are logged through `log_error("jobs.finalize_notify", e)` and do not block history persistence.
- `CANCELLED` and `AWAITING_MANUAL` do not trigger notifications.
- No new thread created in `_finalize_job`; notifier retains threading ownership.
- Added DONE notification and CANCELLED no-notification tests.

## TDD Evidence

1. Added tests before production change.
2. Ran `pytest backend/tests/test_jobs.py::test_finalize_job_notifies_on_done -v`.
3. Test failed as expected: `mock_notify.assert_called_once()` reported 0 calls.
4. Added minimal notifier integration.
5. Ran focused tests: 2 passed.

## Verification

Command:

```text
pytest backend/tests/test_jobs.py -v
```

Result: 13 passed in 1.77s.

## Self-Review

- Changed only `backend/jobs.py` and `backend/tests/test_jobs.py` before this report.
- Import remains local, matching existing lazy imports in `_finalize_job`.
- Existing terminal-state history behavior unchanged.
- Existing cancellation override still prevents notification when cancellation forces status to `CANCELLED`.
- Notifier call receives finalized job and metadata, including cloud-rewritten paths.
- No unrelated refactor or dependency change.

## Concerns

- No blocking concerns found.
- Full repository test suite not run; Task 2 coverage uses full `backend/tests/test_jobs.py` plus focused red/green tests.
