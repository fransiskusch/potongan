# Fix Final Review Report — HIGH 1 & HIGH 2

**Date:** 2026-08-25
**Branch:** fix-final-review (final whole-branch review)
**Findings Addressed:** HIGH 1 (upload dir mismatch), HIGH 2 (unsanitized filename)

## HIGH 1 — backend/main.py:781-784 upload dir mismatch

**Problem:** `temp_dir = abspath(expanduser(base))` placed `upload_<name>` directly in `LOCAL_WORKDIR` (=/content/projects) alongside project dirs, while `colab_api.py:508` cleans `os.path.join(local_workdir,"uploads")` which never contained the file. Stale uploads never GC'd, projects polluted. Spec expects `/content/uploads` (isolated uploads dir).

**Fix:** `backend/main.py:143-144`
```python
# Before
temp_dir = os.path.abspath(os.path.expanduser(base))

# After
temp_dir = os.path.join(os.path.abspath(os.path.expanduser(base)), "uploads")
```
Now upload path = `<LOCAL_WORKDIR>/uploads/upload_<safe>` which aligns with `colab_api.py:256`:
```python
removed = cleanup_stale_uploads(os.path.join(parsed.local_workdir, "uploads"))
```
`os.makedirs(temp_dir, exist_ok=True)` ensures the `uploads` subdir is created.

**Test update:** `backend/tests/test_upload_cloud.py:26`
Added explicit assertion that path is inside `uploads` while keeping existing `startswith(projects)` check passing:
```python
assert os.path.abspath(path).startswith(os.path.abspath(os.path.join(str(tmp_path / "content" / "projects"), "uploads")))
```

## HIGH 2 — backend/main.py:786 unsanitized filename

**Problem:** `file.filename` used verbatim `f"upload_{file.filename}"` — allows `../` traversal and injection of special chars.

**Fix:** `backend/main.py:147-149`
```python
safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(file.filename or "upload"))
if not safe_filename:
    safe_filename = "upload"
file_path = os.path.join(temp_dir, f"upload_{safe_filename}")
```
- `os.path.basename` strips directory components (`../evil.mp4` → `evil.mp4`)
- `re.sub` replaces anything not `A-Z a-z 0-9 . _ -` with `_`
- Fallback for empty/None filename

`re` already imported at `backend/main.py:15`.

## Verification

### Covering tests (required)
Command:
```
python -m pytest backend/tests/test_upload_cloud.py backend/tests/test_colab_api.py -v
```
Output:
```
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0
collected 17 items

backend/tests/test_upload_cloud.py::test_upload_goes_to_local_workdir_in_cloud_mode PASSED [  5%]
backend/tests/test_colab_api.py::test_parse_args_defaults PASSED         [ 11%]
backend/tests/test_colab_api.py::test_parse_args_from_env PASSED         [ 17%]
backend/tests/test_colab_api.py::test_parse_args_cli_overrides_env PASSED [ 23%]
backend/tests/test_colab_api.py::test_setup_environment PASSED           [ 29%]
backend/tests/test_colab_api.py::test_setup_environment_handles_dir_error PASSED [ 35%]
backend/tests/test_colab_api.py::test_start_uvicorn PASSED               [ 41%]
backend/tests/test_colab_api.py::test_start_cloudflared_empty PASSED     [ 47%]
backend/tests/test_colab_api.py::test_start_cloudflared_with_token PASSED [ 52%]
backend/tests/test_colab_api.py::test_start_cloudflared_not_found PASSED [ 58%]
backend/tests/test_colab_api.py::test_terminate_processes PASSED         [ 64%]
backend/tests/test_colab_api.py::test_run_server_lifecycle PASSED        [ 70%]
backend/tests/test_colab_api.py::test_setup_environment_sets_local_workdir PASSED [ 76%]
backend/tests/test_colab_api.py::test_setup_environment_local_workdir_default PASSED [ 82%]
backend/tests/test_colab_api.py::test_verify_gpu_no_torch PASSED         [ 88%]
backend/tests/test_colab_api.py::test_check_tunnel_health_unreachable PASSED [ 94%]
backend/tests/test_colab_api.py::test_cleanup_stale_uploads_removes_old PASSED [100%]

============================= 17 passed in 1.01s ==============================
```

Full backend test suite (CORS check):
```
python -m pytest backend/tests/test_main.py -v
============================= 26 passed in 1.54s ==============================
```

### Manual sanitization & GC alignment check
```
POST /upload filename="../evil.mp4" → path .../projects/uploads/upload_evil.mp4 (no "..", basename sanitized)
POST /upload filename="my video @#$.mp4" → .../uploads/upload_my_video____.mp4 (special chars → _)
cleanup_stale_uploads(<workdir>/uploads) correctly removes 48h-old file (1 removed)
```
All checks pass — upload dir and cleanup path now aligned, filename traversal blocked.

## Files Changed
- `backend/main.py:136-152` — Task 4 upload dir + sanitization
- `backend/tests/test_upload_cloud.py:24-28` — uploads subdir assertion

## Commit
Fix committed as `fix: HIGH1 upload dir mismatch & HIGH2 filename sanitization` (pending re-run of final review verification).
