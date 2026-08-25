# Potongan.id Cloud Experience — AI Selection, Drive Search, Source Sync, Telegram Notif & Face Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Potongan.id web (Vercel) app to full cloud parity with desktop — AI provider/model selection (incl. custom 9router gateway), Google Drive search, save source video to Drive, Telegram job notifications, and modern MediaPipe face tracking.

**Architecture:** Backend (`backend/`, shared desktop+Colab) gains three isolated modules (`notifier.py`, `face_tracker.py`, extended `cloud_sync.py`) and two endpoints (`/gdrive-search`, extended `/api/providers/models`). The web frontend (`web/`, Vercel-only) gains a Settings modal + context for AI config, an adaptive wizard (3-step AI / 4-step manual), and a Drive search bar. All new backend units are drop-in (unchanged interfaces for existing callers).

**Tech Stack:** Python/FastAPI + faster-whisper + openai/genai SDKs + OpenCV + MediaPipe (face tracking) · React + Vite + TypeScript + Tailwind · pytest (backend) · Telegram Bot API via `requests`.

## Global Constraints

- **Backend code is shared** between desktop (`src/`, Tauri/Electron) and Colab. Do NOT break the desktop path: desktop must keep working with the existing Haar Cascade tracker (no `mediapipe` import at module load).
- `mediapipe` is installed ONLY in the Colab notebook (`!pip install mediapipe`), NOT added to `backend/requirements.txt` (that file is shared with desktop).
- `opencv-python-headless>=4.9,<5.0.0` is already pinned in requirements.txt — do not change it.
- Telegram / public base URL config come from **env vars** set by the Colab notebook (not from the web UI).
- API key for AI providers is stored in **browser localStorage**, sent per-request in the job payload — mirror of desktop (`ac_provider`, `ac_model`, `ac_api_keys`).
- Cloud Mode is detected via `AUTO_CLIPPER_CLOUD_MODE` env (existing `cloud_sync.is_cloud_mode()`).
- Persistent workspace root: `AUTO_CLIPPER_WORKSPACE` (default `/content/drive/MyDrive/AutoClipperData`); local workdir `AUTO_CLIPPER_LOCAL_WORKDIR` (default `/content/projects`).
- Backend tests use `pytest`; run from repo root with `pytest backend/tests/<file>`.
- Frontend has NO test framework — verification is `npm run build` (tsc + vite) in `web/` plus manual smoke testing.
- Existing backend test suite must stay green; any new test must follow the existing mock patterns in `backend/tests/`.

---

### Task 1: Telegram Notifier Module

**Files:**
- Create: `backend/notifier.py`
- Test: `backend/tests/test_notifier.py`

**Interfaces:**
- Consumes: `backend.logger.log_error`, `backend.logger.log_app` (existing).
- Produces: `notify_job_finished(job_id: str, status: str, job: dict, metadata: dict) -> None` and `send_telegram_message(text: str, bot_token: str, chat_id: str) -> bool`. Later tasks (Task 2) call `notify_job_finished` from `_finalize_job`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_notifier.py`:

```python
import os
from unittest.mock import patch
from backend.notifier import send_telegram_message, notify_job_finished


def _env(monkeypatch, bot="bot123", chat="42"):
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_BOT_TOKEN", bot)
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_CHAT_ID", chat)


def test_send_telegram_message_success(monkeypatch):
    with patch("backend.notifier.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        ok = send_telegram_message("hello", "bot123", "42")
        assert ok is True
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.telegram.org/botbot123/sendMessage"
        assert kwargs["json"] == {"chat_id": "42", "text": "hello"}
        assert kwargs["timeout"] == 10


def test_send_telegram_message_network_error_returns_false(monkeypatch):
    with patch("backend.notifier.requests.post", side_effect=Exception("boom")):
        ok = send_telegram_message("hello", "bot123", "42")
        assert ok is False


def test_send_telegram_message_empty_token_no_call(monkeypatch):
    with patch("backend.notifier.requests.post") as mock_post:
        ok = send_telegram_message("hello", "", "42")
        assert ok is False
        mock_post.assert_not_called()


def test_notify_job_finished_skips_when_no_env(monkeypatch):
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_CHAT_ID", "")
    with patch("backend.notifier.send_telegram_message") as mock_send:
        notify_job_finished("job-1", "DONE", {"title": "Judul"}, {"title": "Judul"})
        mock_send.assert_not_called()


def test_notify_job_finished_done_sends_message(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("AUTO_CLIPPER_PUBLIC_BASE_URL", "https://be.example.com")
    job = {"title": "Judul Proyek", "clips": [{"path": "/tmp/a_clip_1.mp4", "description": "d1"}], "failed": 0}
    metadata = {"title": "Judul Proyek", "duration_seconds": 720}
    with patch("backend.notifier.send_telegram_message") as mock_send:
        notify_job_finished("job-1", "DONE", job, metadata)
        assert mock_send.called
        text = mock_send.call_args.args[0]
        assert "Judul Proyek" in text
        assert "DONE" in text
        assert "1 berhasil" in text


def test_notify_job_finished_error_sends_message(monkeypatch):
    _env(monkeypatch)
    job = {"title": "X", "clips": [], "failed": 0, "error": "gagal"}
    with patch("backend.notifier.send_telegram_message") as mock_send:
        notify_job_finished("job-2", "ERROR", job, {"title": "X"})
        assert mock_send.called
        assert "ERROR" in mock_send.call_args.args[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_notifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.notifier'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/notifier.py`:

```python
"""Best-effort Telegram notifications for finished jobs.

Reads config from env vars (set by the Colab notebook):
  AUTO_CLIPPER_TELEGRAM_BOT_TOKEN  (empty = notifications disabled)
  AUTO_CLIPPER_TELEGRAM_CHAT_ID
  AUTO_CLIPPER_PUBLIC_BASE_URL     (default https://be-clipper.fransiskus.my.id)
"""
import os

from backend.logger import log_error, log_app

TELEGRAM_API = "https://api.telegram.org"

MAX_MESSAGE_LEN = 4096


def _bot_token() -> str:
    return os.environ.get("AUTO_CLIPPER_TELEGRAM_BOT_TOKEN", "").strip()


def _chat_id() -> str:
    return os.environ.get("AUTO_CLIPPER_TELEGRAM_CHAT_ID", "").strip()


def _public_base_url() -> str:
    return os.environ.get("AUTO_CLIPPER_PUBLIC_BASE_URL", "https://be-clipper.fransiskus.my.id").strip()


def send_telegram_message(text: str, bot_token: str, chat_id: str) -> bool:
    if not bot_token or not chat_id or not text:
        return False
    try:
        import requests

        url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        log_error("notifier.send_telegram_message", e)
        return False


def notify_job_finished(job_id: str, status: str, job: dict, metadata: dict) -> None:
    bot_token = _bot_token()
    chat_id = _chat_id()
    if not bot_token or not chat_id:
        return

    title = (metadata.get("title") or job.get("title") or "").strip() or "Untitled"
    base_url = _public_base_url().rstrip("/")

    if status == "ERROR":
        emoji = "\u274c"
        err = str(job.get("error") or "")[:200]
        status_line = f"ERROR: {err}" if err else "ERROR"
    else:
        emoji = "\U0001F3AC"
        status_line = "DONE"

    clips = job.get("clips", []) or []
    ok = len(clips)
    failed = job.get("failed", 0)
    dur = metadata.get("duration_seconds", 0)
    dur_min = f"{int(dur // 60)} menit" if dur >= 60 else f"{int(dur)} detik"

    lines = [f"{emoji} Potongan.id \u2014 Job Selesai",
             f"\U0001F4CC Judul: {title}",
             f"{'\u2705' if status == 'DONE' else emoji} Status: {status_line}",
             f"\U0001F39E Klip: {ok} berhasil, {failed} gagal",
             f"\u23F1 Durasi proses: {dur_min}",
             ""]

    if clips:
        lines.append("\U0001F4E5 Unduh klip:")
        for i, clip in enumerate(clips, start=1):
            name = os.path.basename(clip.get("path", "")) or f"clip_{i}"
            url = f"{base_url}/video?path={clip.get('path', '')}"
            lines.append(f"{i}. {name} \u2014 {url}")

    lines.append("")
    lines.append("\u23F3 Link aktif selama backend Colab menyala.")

    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_LEN:
        keep = len(clips) - (len(text) - MAX_MESSAGE_LEN) // 60
        keep = max(0, keep)
        lines = lines[:6]
        lines.append(f"\U0001F4E5 Unduh klip ({keep} pertama):")
        for i, clip in enumerate(clips[:keep], start=1):
            name = os.path.basename(clip.get("path", "")) or f"clip_{i}"
            lines.append(f"{i}. {name} \u2014 {base_url}/video?path={clip.get('path', '')}")
        lines.append(f"\u2026dan {len(clips) - keep} klip lainnya, buka web untuk melihat semua.")
        lines.append("\u23F3 Link aktif selama backend Colab menyala.")
        text = "\n".join(lines)

    # Fire in a thread so a slow/failing network never blocks job finalization.
    import threading

    def _send():
        try:
            ok = send_telegram_message(text, bot_token, chat_id)
            log_app(f"[notifier] job {job_id} status={status} sent={ok}")
        except Exception as e:
            log_error("notifier.notify_job_finished", e)

    threading.Thread(target=_send, daemon=True).start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_notifier.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/notifier.py backend/tests/test_notifier.py
git commit -m "feat: add best-effort Telegram notifier module"
```

---

### Task 2: Wire Notifier into Job Finalize

**Files:**
- Modify: `backend/jobs.py` (in `_finalize_job`, near the `save_history` block ~line 1141)

**Interfaces:**
- Consumes: `notify_job_finished` (Task 1).
- Produces: side-effect — Telegram message on DONE/ERROR. No new signatures.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_jobs.py` (append; adapt existing imports at top of file — the file already imports `backend.jobs`):

```python
from unittest.mock import patch


def test_finalize_job_notifies_on_done(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_BOT_TOKEN", "b")
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_CHAT_ID", "c")
    monkeypatch.delenv("AUTO_CLIPPER_CLOUD_MODE", raising=False)
    from backend import jobs
    job_id = "notif-done-1"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "https://youtube.com/x", "title": "T",
        "status": "DONE", "clips": [], "failed": 0, "error": None,
        "mode": "manual", "source_path": str(tmp_path / "src.mp4"),
    }
    with patch("backend.notifier.notify_job_finished") as mock_notify:
        jobs._finalize_job(job_id, "DONE", {"title": "T"})
        mock_notify.assert_called_once()


def test_finalize_job_no_notify_on_cancelled(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_BOT_TOKEN", "b")
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_CHAT_ID", "c")
    monkeypatch.delenv("AUTO_CLIPPER_CLOUD_MODE", raising=False)
    from backend import jobs
    job_id = "notif-cancel-1"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "x", "title": "T", "status": "CANCELLED",
        "clips": [], "failed": 0, "error": None, "mode": "manual",
    }
    with patch("backend.notifier.notify_job_finished") as mock_notify:
        jobs._finalize_job(job_id, "CANCELLED", {"title": "T"})
        mock_notify.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_jobs.py::test_finalize_job_notifies_on_done -v`
Expected: FAIL (assert `mock_notify.assert_called_once()` fails because it was never called).

- [ ] **Step 3: Write minimal implementation**

In `backend/jobs.py`, inside `_finalize_job`, in the `if status in ["DONE", "ERROR", "CANCELLED", "AWAITING_MANUAL"]:` block, add a notifier call BEFORE `save_history`:

```python
    if status in ["DONE", "ERROR", "CANCELLED", "AWAITING_MANUAL"]:
        # Notify on terminal states the user cares about (not cancel / awaiting).
        if status in ("DONE", "ERROR"):
            try:
                from backend.notifier import notify_job_finished
                notify_job_finished(job_id, status, job, metadata)
            except Exception as e:
                log_error("jobs.finalize_notify", e)

        try:
            from backend.db import save_history
            save_history(job_id, job["url"], status, job["clips"], metadata)
        except Exception as e:
            log_error("jobs.save_history", e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_jobs.py::test_finalize_job_notifies_on_done backend/tests/test_jobs.py::test_finalize_job_no_notify_on_cancelled -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/jobs.py backend/tests/test_jobs.py
git commit -m "feat: send Telegram notification on job DONE/ERROR"
```

---

### Task 3: Save Source Video to Drive

**Files:**
- Modify: `backend/cloud_sync.py` (add `sync_source_to_persistent`)
- Modify: `backend/jobs.py` (`create_job` signature + job dict + `_finalize_job` source sync)
- Modify: `backend/main.py` (`CreateJobRequest` add `save_source_to_drive`)
- Test: `backend/tests/test_cloud_sync.py`

**Interfaces:**
- Consumes: `is_cloud_mode`, `get_persistent_root` (existing in cloud_sync.py).
- Produces: `sync_source_to_persistent(local_project_dir: str) -> str` returns destination path or `""`. `CreateJobRequest.save_source_to_drive: bool = True`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_cloud_sync.py`:

```python
def test_sync_source_to_persistent_copies_source(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    from backend.cloud_sync import sync_source_to_persistent
    local = tmp_path / "local_projects" / "Judul"
    (local / "source").mkdir(parents=True)
    src_file = local / "source" / "source_video.mp4"
    src_file.write_bytes(b"videodata")
    dest = sync_source_to_persistent(str(local))
    assert dest.endswith("source" + os.sep + "source_video.mp4")
    assert os.path.exists(dest)
    assert open(dest, "rb").read() == b"videodata"


def test_sync_source_to_persistent_noop_non_cloud(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTO_CLIPPER_CLOUD_MODE", raising=False)
    from backend.cloud_sync import sync_source_to_persistent
    local = tmp_path / "x"
    assert sync_source_to_persistent(str(local)) == ""
```

(Ensure `import os` is present at the top of `test_cloud_sync.py`; add if missing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_cloud_sync.py::test_sync_source_to_persistent_copies_source -v`
Expected: FAIL (`ImportError: cannot import name 'sync_source_to_persistent'`).

- [ ] **Step 3: Write minimal implementation**

In `backend/cloud_sync.py`, add after `sync_project_to_persistent`:

```python
def sync_source_to_persistent(local_project_dir: str) -> str:
    """Salin source/source_video.mp4 ke Drive. No-op di non-cloud. Return dest path ('' jika gagal)."""
    if not is_cloud_mode():
        return ""
    persistent_root = get_persistent_root()
    if not persistent_root or not local_project_dir or not os.path.isdir(local_project_dir):
        return ""

    src_file = os.path.join(local_project_dir, "source", "source_video.mp4")
    if not os.path.isfile(src_file):
        return ""

    dest_project = os.path.join(persistent_root, _PERSISTENT_PROJECTS, os.path.basename(os.path.normpath(local_project_dir)))
    dest_file = os.path.join(dest_project, "source", "source_video.mp4")
    try:
        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
        shutil.copy2(src_file, dest_file)
        log_app(f"[cloud_sync] Synced source video to {dest_file}")
        return dest_file
    except Exception as e:
        log_error("cloud_sync.sync_source_to_persistent", e)
        return ""
```

Then in `backend/jobs.py`:
- Change `create_job` signature: add `save_source_to_drive: bool = True` at the end (after `subtitle_config`).
- In the `active_jobs[job_id]` dict in `create_job`, add `"save_source_to_drive": save_source_to_drive,`.

In `backend/main.py`, add to `CreateJobRequest` (after `subtitle_config`):

```python
    save_source_to_drive: bool = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_cloud_sync.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/cloud_sync.py backend/jobs.py backend/main.py backend/tests/test_cloud_sync.py
git commit -m "feat: add sync_source_to_persistent + save_source_to_drive flag"
```

---

### Task 4: Sync Source in _finalize_job (respecting flag)

**Files:**
- Modify: `backend/jobs.py` (`_finalize_job` cloud-sync block ~line 1117)
- Modify: `backend/main.py` (`api_create_job` to pass `req.save_source_to_drive`)

**Interfaces:**
- Consumes: `sync_source_to_persistent` (Task 3), `job["save_source_to_drive"]`.
- Produces: source video copied to Drive after DONE when flag is true.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_jobs_workspace.py`:

```python
def test_finalize_syncs_source_when_flag_on(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
    from backend import jobs
    local_proj = tmp_path / "local" / "Judul"
    (local_proj / "source").mkdir(parents=True)
    (local_proj / "source" / "source_video.mp4").write_bytes(b"x")
    job_id = "src-sync-1"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "https://youtube.com/x", "title": "Judul",
        "status": "DONE", "clips": [], "failed": 0, "error": None,
        "mode": "manual", "save_source_to_drive": True,
        "source_path": str(local_proj / "source" / "source_video.mp4"),
    }
    with patch("backend.db.save_history"):
        jobs._finalize_job(job_id, "DONE", {"title": "Judul"})
    assert (tmp_path / "drive" / "projects" / "Judul" / "source" / "source_video.mp4").exists()


def test_finalize_skips_source_when_flag_off(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
    from backend import jobs
    job_id = "src-sync-2"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "x", "title": "Judul", "status": "DONE",
        "clips": [], "failed": 0, "error": None, "mode": "manual",
        "save_source_to_drive": False,
        "source_path": str(tmp_path / "local" / "Judul" / "source" / "source_video.mp4"),
    }
    with patch("backend.db.save_history"):
        jobs._finalize_job(job_id, "DONE", {"title": "Judul"})
    assert not (tmp_path / "drive" / "projects" / "Judul" / "source" / "source_video.mp4").exists()
```

(Ensure `from unittest.mock import patch` is imported at top of `test_jobs_workspace.py`; add if missing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_jobs_workspace.py::test_finalize_syncs_source_when_flag_on -v`
Expected: FAIL (file not created).

- [ ] **Step 3: Write minimal implementation**

In `backend/jobs.py`, inside the cloud-sync block of `_finalize_job` (after `sync_project_to_persistent(local_proj)`), add:

```python
                # Salin source video ke Drive bila diminta (default ON).
                if job.get("save_source_to_drive", True) and not str(job.get("url", "")).startswith("local:"):
                    from backend.cloud_sync import sync_source_to_persistent
                    sync_source_to_persistent(local_proj)
```

In `backend/main.py`, update `api_create_job`'s `create_job(...)` call to pass `save_source_to_drive=req.save_source_to_drive` (add as last keyword arg after `subtitle_config=req.subtitle_config`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_jobs_workspace.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/jobs.py backend/main.py backend/tests/test_jobs_workspace.py
git commit -m "feat: sync source video to Drive in finalize when save_source_to_drive"
```

---

### Task 5: Google Drive Search Endpoint

**Files:**
- Modify: `backend/main.py` (add `/gdrive-search`)
- Test: `backend/tests/test_gdrive_search.py`

**Interfaces:**
- Consumes: Cloud Mode guard pattern from existing `/gdrive-browser`.
- Produces: `GET /gdrive-search?q=<query>` returning `{status, results: [{name, path}], truncated: bool}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gdrive_search.py`:

```python
import os
from fastapi.testclient import TestClient


def _make_tree(root):
    (root / "videos").mkdir(parents=True)
    (root / "videos" / "my_podcast_01.mp4").write_bytes(b"x")
    (root / "videos" / "travel_vlog.mp4").write_bytes(b"x")
    (root / "videos" / "notes.txt").write_bytes(b"x")
    (root / "videos" / "nested").mkdir()
    (root / "videos" / "nested" / "PODCAST_clip.mov").write_bytes(b"x")


def _client_cloud(monkeypatch, root):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    # Patch the base drive path used by the endpoint to our tmp root.
    monkeypatch.setattr("backend.main.os.path.abspath", lambda p: p)
    monkeypatch.setattr("backend.main._GDRIVE_BASE", str(root))
    from backend.main import app
    return TestClient(app)


def test_gdrive_search_finds_video_case_insensitive(monkeypatch, tmp_path):
    _make_tree(tmp_path)
    c = _client_cloud(monkeypatch, tmp_path)
    r = c.get("/gdrive-search", params={"q": "podcast"})
    assert r.status_code == 200
    data = r.json()
    names = [i["name"] for i in data["results"]]
    assert "my_podcast_01.mp4" in names
    assert "PODCAST_clip.mov" in names
    assert "travel_vlog.mp4" not in names
    assert data["truncated"] is False


def test_gdrive_search_no_results(monkeypatch, tmp_path):
    _make_tree(tmp_path)
    c = _client_cloud(monkeypatch, tmp_path)
    r = c.get("/gdrive-search", params={"q": "zzznothing"})
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_gdrive_search_not_cloud_mode(monkeypatch):
    monkeypatch.delenv("AUTO_CLIPPER_CLOUD_MODE", raising=False)
    from backend.main import app
    c = TestClient(app)
    r = c.get("/gdrive-search", params={"q": "x"})
    assert r.status_code == 200
    assert r.json().get("status") == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_gdrive_search.py -v`
Expected: FAIL (404 Not Found, or assertion on missing `_GDRIVE_BASE`).

- [ ] **Step 3: Write minimal implementation**

In `backend/main.py`, refactor the base-drive constant so tests can patch it. Replace the hardcoded base in `/gdrive-browser` (`base_drive = os.path.abspath("/content/drive/MyDrive")`) with a module constant, and add the search endpoint right after `/gdrive-browser`:

```python
_GDRIVE_BASE = "/content/drive/MyDrive"

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm")


@app.get("/gdrive-browser")
def api_get_gdrive_browser(dir_path: str = Query("/content/drive/MyDrive")):
    if not os.environ.get("AUTO_CLIPPER_CLOUD_MODE"):
        return {"status": "error", "message": "Only available in Cloud Mode"}
    base_drive = os.path.abspath(_GDRIVE_BASE)
    # ... (unchanged body)
```

Then add:

```python
@app.get("/gdrive-search")
def api_gdrive_search(q: str = Query(""), max_results: int = 100):
    if not os.environ.get("AUTO_CLIPPER_CLOUD_MODE"):
        return {"status": "error", "message": "Only available in Cloud Mode"}
    if not q or not q.strip():
        return {"status": "success", "results": [], "truncated": False}

    needle = q.strip().lower()
    base_drive = os.path.abspath(_GDRIVE_BASE)
    results = []
    truncated = False
    start = time.time()

    try:
        for root, dirs, files in os.walk(base_drive):
            if time.time() - start > 10:
                truncated = True
                break
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.lower().endswith(VIDEO_EXTS) and needle in name.lower():
                    results.append({"name": name, "path": os.path.join(root, name)})
                    if len(results) >= max_results:
                        truncated = True
                        return {"status": "success", "results": results, "truncated": truncated}
    except Exception as e:
        log_error("api_gdrive_search", e)

    return {"status": "success", "results": results, "truncated": truncated}
```

(Ensure `import time` is present at top of `main.py`; add if missing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_gdrive_search.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_gdrive_search.py
git commit -m "feat: add /gdrive-search endpoint for recursive video search"
```

---

### Task 6: Face Tracker Module (MediaPipe + Dominant Face Lock)

**Files:**
- Create: `backend/face_tracker.py`
- Test: `backend/tests/test_face_tracker.py`

**Interfaces:**
- Consumes: `backend.crop_utils.to_seconds`, `backend.logger.log_error`.
- Produces (drop-in for crop_utils functions):
  - `sample_face_trajectory(video_path: str, start_time: float, end_time: float, interval: float = 0.25, should_cancel=None) -> list[tuple[float, float]]`
  - `detect_video_layout(video_path: str, start_time=None, end_time=None, samples: int = 12, should_cancel=None) -> dict`
  - Internal: `_OneEuroFilter`, `_DominantFaceLock`, `_detector()` (returns MediaPipe detector or None).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_face_tracker.py`:

```python
from unittest.mock import patch


def test_sample_face_trajectory_returns_identity_format(monkeypatch):
    # Force Haar fallback by making MediaPipe unavailable.
    monkeypatch.setattr("backend.face_tracker._mediapipe_available", lambda: False)
    monkeypatch.setattr("backend.face_tracker.sample_face_trajectory_haar",
                        lambda *a, **k: [(0.0, 0.5), (0.25, 0.5)])
    from backend.face_tracker import sample_face_trajectory
    traj = sample_face_trajectory("dummy.mp4", 0.0, 0.5, interval=0.25)
    assert traj == [(0.0, 0.5), (0.25, 0.5)]


def test_one_euro_filter_static_is_flat():
    from backend.face_tracker import _OneEuroFilter
    f = _OneEuroFilter(min_cutoff=1.0, beta=0.0)
    out = [f(t, 0.5) for t in [0.0, 0.1, 0.2, 0.3]]
    assert all(abs(x - 0.5) < 1e-9 for x in out)


def test_one_euro_filter_responds_to_jump():
    from backend.face_tracker import _OneEuroFilter
    f = _OneEuroFilter(min_cutoff=1.0, beta=0.0)
    f(0.0, 0.5)
    f(0.1, 0.5)
    out = f(0.2, 0.9)
    assert out > 0.5  # moved toward the new value


def test_dominant_face_lock_holds_when_missing():
    from backend.face_tracker import _DominantFaceLock
    lock = _DominantFaceLock()
    lock.update(0.0, [(0.5, 0.5, 0.1, 0.1)])   # one face at t=0
    x = lock.update(1.0, [])                     # missing -> hold
    assert x == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_face_tracker.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write minimal implementation**

Create `backend/face_tracker.py`:

```python
"""Modern face tracking: MediaPipe Face Detection + Dominant Face Lock.

Drop-in replacement for the Haar-based functions in backend.crop_utils. When
MediaPipe is not installed, delegates to the legacy Haar implementation so the
desktop build keeps working unchanged.
"""
import math

from backend.logger import log_error
from backend.crop_utils import to_seconds


def _mediapipe_available() -> bool:
    try:
        import mediapipe  # noqa: F401
        return True
    except Exception:
        return False


class _OneEuroFilter:
    """1€ filter: low latency at high speed, zero jitter when still."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    def _alpha(self, dt):
        tau = 1.0 / (2 * math.pi * self.min_cutoff)
        return 1.0 / (1.0 + tau / max(dt, 1e-6))

    def __call__(self, t, x):
        if self.x_prev is None:
            self.x_prev = x
            self.t_prev = t
            return x
        dt = t - self.t_prev
        if dt <= 0:
            return self.x_prev
        dx = (x - self.x_prev) / dt
        alpha_d = self._alpha(dt)
        self.dx_prev = self.dx_prev + alpha_d * (dx - self.dx_prev)
        cutoff = self.min_cutoff + self.beta * abs(self.dx_prev)
        tau = 1.0 / (2 * math.pi * cutoff)
        alpha = 1.0 / (1.0 + tau / dt)
        self.x_prev = self.x_prev + alpha * (x - self.x_prev)
        self.t_prev = t
        return self.x_prev


class _DominantFaceLock:
    """Pick one dominant face and lock onto it across frames."""

    HOLD_SECONDS = 5.0
    RESCAN_SECONDS = 15.0

    def __init__(self):
        self.target = None          # (cx, cy)
        self.last_seen = None       # timestamp
        self.anchor = None
        self.missing_since = None

    def update(self, t, faces):
        """faces: list of (cx, cy, w, h) normalized. Returns x-center or None."""
        if not faces:
            if self.target is not None and self.missing_since is None:
                self.missing_since = t
            if self.missing_since is not None and (t - self.missing_since) > self.RESCAN_SECONDS:
                self.target = None
                self.missing_since = None
                self.anchor = None
            if self.target is not None:
                return self.target[0]
            return None

        if self.target is None:
            # Pick the largest face as initial target.
            faces_sorted = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
            cx, cy, _, _ = faces_sorted[0]
            self.target = (cx, cy)
            self.anchor = (cx, cy)
            self.missing_since = None
            self.last_seen = t
            return cx

        # Track: nearest centroid to last target.
        nearest = min(faces, key=lambda f: abs(f[0] - self.target[0]) + abs(f[1] - self.target[1]))
        cx, cy, _, _ = nearest
        self.target = (cx, cy)
        self.last_seen = t
        self.missing_since = None
        return cx


def sample_face_trajectory_haar(video_path, start_time, end_time, interval=0.5, should_cancel=None):
    """Delegate to legacy Haar tracker (imported lazily to avoid circulars)."""
    from backend.crop_utils import sample_face_trajectory as _haar
    return _haar(video_path, start_time, end_time, interval=interval, should_cancel=should_cancel)


def sample_face_trajectory(video_path, start_time, end_time, interval=0.25, should_cancel=None):
    """Sample face x-centers across a window. MediaPipe if available, else Haar."""
    if not _mediapipe_available():
        return sample_face_trajectory_haar(video_path, start_time, end_time, interval=interval, should_cancel=should_cancel)

    try:
        import cv2
        import mediapipe as mp

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            return [(0.0, 0.5)]

        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        half_window = (frame_h * 9 / 16) / frame_w / 2 if (frame_w and frame_h) else 0.28
        lo, hi = half_window, 1.0 - half_window

        duration = max(0.1, end_time - start_time)
        num_samples = max(2, int(duration / interval) + 1)

        detector = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.4)
        lock = _DominantFaceLock()
        filt = _OneEuroFilter(min_cutoff=0.8, beta=0.4)

        traj = []
        for i in range(num_samples):
            if should_cancel and should_cancel():
                break
            rel_t = min(duration, i * interval)
            abs_t = start_time + rel_t
            cap.set(cv2.CAP_PROP_POS_MSEC, abs_t * 1000.0)
            ret, frame = cap.read()
            if not ret:
                traj.append((rel_t, 0.5))
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detections = detector.process(rgb).detections or []
            faces = []
            for d in detections:
                box = d.location_data.relative_bounding_box
                cx = box.xmin + box.width / 2
                cy = box.ymin + box.height / 2
                faces.append((cx, cy, box.width, box.height))

            x = lock.update(rel_t, faces)
            if x is None:
                x = 0.5
            x = filt(rel_t, x)
            x = max(lo, min(hi, x)) if lo <= hi else x
            traj.append((rel_t, x))

        cap.release()
        detector.close()
        return traj
    except Exception as e:
        log_error("face_tracker.sample_face_trajectory", f"MediaPipe failed ({e}); fallback to Haar.")
        return sample_face_trajectory_haar(video_path, start_time, end_time, interval=interval, should_cancel=should_cancel)


def detect_video_layout(video_path, start_time=None, end_time=None, samples=12, should_cancel=None):
    """Layout detection. MediaPipe if available, else Haar (legacy)."""
    if not _mediapipe_available():
        from backend.crop_utils import detect_video_layout as _haar_layout
        return _haar_layout(video_path, start_time=start_time, end_time=end_time, samples=samples, should_cancel=should_cancel)

    try:
        import cv2
        import mediapipe as mp
        import statistics

        result = {"mode": "standard", "face_box": None, "face_area_ratio": 0.0, "face_center": (0.5, 0.5)}
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            return result

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        dur = total_frames / fps if fps else 0.0
        if start_time is not None:
            s = to_seconds(start_time)
            e = to_seconds(end_time) if end_time is not None else s + 30.0
        else:
            s, e = 0.0, (dur if dur else 1.0)
        if e <= s:
            e = s + 1.0

        detector = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.4)
        corner_faces = []
        for i in range(samples):
            if should_cancel and should_cancel():
                break
            t = s + (e - s) * (i / (samples - 1) if samples > 1 else 0.5)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ret, frame = cap.read()
            if not ret:
                continue
            fh_, fw_ = frame.shape[0], frame.shape[1]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detections = detector.process(rgb).detections or []
            for d in detections:
                box = d.location_data.relative_bounding_box
                area = box.width * box.height
                cx = box.xmin + box.width / 2
                cy = box.ymin + box.height / 2
                if area < 0.25 and (abs(cx - 0.5) > 0.1 or abs(cy - 0.5) > 0.1):
                    corner_faces.append((cx, cy, area, box.xmin, box.ymin, box.width, box.height))

        cap.release()
        detector.close()

        if not corner_faces:
            return result

        # Simple clustering (mirrors legacy). Reuse the legacy clustering via Haar
        # is not trivial, so do a light equivalent: dominant corner cluster.
        clusters = []
        for f in corner_faces:
            cx, cy = f[0], f[1]
            for c in clusters:
                if abs(c['cx'] - cx) < 0.1 and abs(c['cy'] - cy) < 0.1:
                    c['faces'].append(f)
                    c['cx'] = sum(x[0] for x in c['faces']) / len(c['faces'])
                    c['cy'] = sum(x[1] for x in c['faces']) / len(c['faces'])
                    break
            else:
                clusters.append({'cx': cx, 'cy': cy, 'faces': [f]})

        best = max(clusters, key=lambda c: len(c['faces']))
        min_det = max(2, int(samples * 0.2))
        if len(best['faces']) >= min_det:
            med = lambda idx: statistics.median([b[idx] for b in best['faces']])
            cx, cy, area = med(0), med(1), med(2)
            x, y, w, h = med(3), med(4), med(5), med(6)
            result = {"mode": "gaming", "face_box": (x, y, w, h),
                      "face_area_ratio": area, "face_center": (cx, cy)}
        return result
    except Exception as e:
        log_error("face_tracker.detect_video_layout", f"MediaPipe failed ({e}); fallback to Haar.")
        from backend.crop_utils import detect_video_layout as _haar_layout
        return _haar_layout(video_path, start_time=start_time, end_time=end_time, samples=samples, should_cancel=should_cancel)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_face_tracker.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/face_tracker.py backend/tests/test_face_tracker.py
git commit -m "feat: add MediaPipe face tracker with Dominant Face Lock + Haar fallback"
```

---

### Task 7: Delegate crop_utils to face_tracker

**Files:**
- Modify: `backend/crop_utils.py` (top of `sample_face_trajectory` and `detect_video_layout`)

**Interfaces:**
- Consumes: `backend.face_tracker` (Task 6).
- Produces: cloud mode uses MediaPipe path via delegation; desktop (no mediapipe) unchanged.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_face_tracker_integration.py`:

```python
from unittest.mock import patch


def test_crop_utils_delegates_when_mediapipe(monkeypatch):
    monkeypatch.setattr("backend.face_tracker._mediapipe_available", lambda: True)
    with patch("backend.face_tracker.sample_face_trajectory", return_value=[(0.0, 0.5)]) as mock_ft:
        from backend.crop_utils import sample_face_trajectory
        traj = sample_face_trajectory("dummy.mp4", 0.0, 0.5)
        assert traj == [(0.0, 0.5)]
        mock_ft.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_face_tracker_integration.py -v`
Expected: FAIL (crop_utils doesn't delegate yet; its own Haar code runs).

- [ ] **Step 3: Write minimal implementation**

In `backend/crop_utils.py`, add a guard at the top of both `sample_face_trajectory` (line 121) and `detect_video_layout` (line 250) to delegate to `face_tracker` when MediaPipe is available. For `sample_face_trajectory`, insert immediately after the docstring:

```python
    try:
        from backend.face_tracker import _mediapipe_available
        if _mediapipe_available():
            from backend.face_tracker import sample_face_trajectory as _mp_traj
            return _mp_traj(video_path, start_time, end_time, interval=interval, should_cancel=should_cancel)
    except Exception:
        pass
```

For `detect_video_layout`, insert immediately after its docstring:

```python
    try:
        from backend.face_tracker import _mediapipe_available
        if _mediapipe_available():
            from backend.face_tracker import detect_video_layout as _mp_layout
            return _mp_layout(video_path, start_time=start_time, end_time=end_time, samples=samples, should_cancel=should_cancel)
    except Exception:
        pass
```

(Delegation only happens in cloud mode effectively, because MediaPipe is only installed in Colab; the desktop environment will never satisfy `_mediapipe_available()`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_face_tracker_integration.py -v backend/tests/test_crop_utils.py -v`
Expected: all PASS (existing crop_utils tests still green — they mock cv2 and don't trigger the mediapipe path because mediapipe isn't installed locally).

- [ ] **Step 5: Commit**

```bash
git add backend/crop_utils.py backend/tests/test_face_tracker_integration.py
git commit -m "feat: delegate face tracking to face_tracker (MediaPipe) in cloud"
```

---

### Task 8: Extend fetch_provider_models for Custom Base URL

**Files:**
- Modify: `backend/ai_utils.py` (`fetch_provider_models`)
- Modify: `backend/main.py` (`FetchModelsRequest` + `api_fetch_models`)
- Test: `backend/tests/test_ai_utils.py`

**Interfaces:**
- Consumes: `OPENAI_COMPAT_PROVIDERS`, OpenAI client (existing).
- Produces: `fetch_provider_models(provider, api_key, custom_base_url="", custom_model_name="") -> list`; `FetchModelsRequest.custom_base_url: str = ""`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ai_utils.py`:

```python
def test_fetch_provider_models_custom_base_url(monkeypatch):
    from backend import ai_utils

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs.get("base_url") == "https://my9router.example/v1"

        def models(self):
            class M:
                def __init__(self, i):
                    self.id = i
                def __iter__(self):
                    return iter([])
            return type("Resp", (), {"data": [M("model-a"), M("model-b")]})()

    monkeypatch.setattr(ai_utils, "OpenAI", FakeClient)
    models = ai_utils.fetch_provider_models("custom", "key", custom_base_url="https://my9router.example/v1")
    assert [m["id"] for m in models] == ["model-a", "model-b"]
```

(If `ai_utils` is not already imported at the top of the test file, add `from backend import ai_utils` inside the test as shown.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_ai_utils.py::test_fetch_provider_models_custom_base_url -v`
Expected: FAIL (TypeError: unexpected keyword `custom_base_url`).

- [ ] **Step 3: Write minimal implementation**

In `backend/ai_utils.py`, change the signature:

```python
def fetch_provider_models(provider: str, api_key: str, custom_base_url: str = "", custom_model_name: str = "") -> list:
```

And in the `elif provider in OPENAI_COMPAT_PROVIDERS or provider == "openai":` branch, when `provider == "custom"`, use `custom_base_url`:

```python
        elif provider in OPENAI_COMPAT_PROVIDERS or provider == "openai" or provider == "custom":
            cfg = OPENAI_COMPAT_PROVIDERS.get(provider)
            if provider == "custom":
                if not custom_base_url:
                    return []
                base_url = custom_base_url
            else:
                base_url = cfg["base_url"] if cfg else None
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=15.0,
                default_headers=BROWSER_HEADERS
            ) if base_url else OpenAI(
                api_key=api_key,
                timeout=15.0,
                default_headers=BROWSER_HEADERS
            )
```

In `backend/main.py`, update:

```python
class FetchModelsRequest(BaseModel):
    provider: str
    api_key: str
    custom_base_url: str = ""
    custom_model_name: str = ""

@app.post("/api/providers/models")
def api_fetch_models(req: FetchModelsRequest):
    try:
        from backend.ai_utils import fetch_provider_models
        models = fetch_provider_models(req.provider, req.api_key.strip(), custom_base_url=req.custom_base_url.strip(), custom_model_name=req.custom_model_name.strip())
        return {"status": "success", "models": models}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_ai_utils.py::test_fetch_provider_models_custom_base_url -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/ai_utils.py backend/main.py backend/tests/test_ai_utils.py
git commit -m "feat: support custom base URL in fetch_provider_models (9router)"
```

---

### Task 9: Notebook — mediapipe install + Telegram form fields

**Files:**
- Modify: `Auto_Clipper_Colab.ipynb`

**Interfaces:**
- Consumes: existing notebook cells 2 and 6.
- Produces: `mediapipe` installed; env `AUTO_CLIPPER_TELEGRAM_BOT_TOKEN`, `AUTO_CLIPPER_TELEGRAM_CHAT_ID`, `AUTO_CLIPPER_PUBLIC_BASE_URL` set for `colab_api`.

- [ ] **Step 1: Edit cell 2 (system deps) — add mediapipe install**

In cell 2, after the cloudflared block and before the font block, add a pip install line. The notebook is JSON; the cell 2 `source` array gains:

```json
    "!pip install -q mediapipe\n",
```

(Place it right after the `import os, shutil, subprocess` block's font install section, e.g. just before `FONT_DIR = ...`.)

- [ ] **Step 2: Edit cell 6 (run backend) — add Telegram + public base URL form fields**

In cell 6, add three form fields after `ALLOWED_ORIGINS` and set env vars. The updated cell 6 `source` becomes:

```python
#@title 6. Jalankan Backend Potongan.id
CLOUDFLARE_TUNNEL_TOKEN = "" #@param {type:"string"}
API_SECRET_TOKEN = "" #@param {type:"string"}
ALLOWED_ORIGINS = "https://clip.fransiskus.my.id,https://auto-clipper-liart.vercel.app" #@param {type:"string"}
TELEGRAM_BOT_TOKEN = "" #@param {type:"string"}
TELEGRAM_CHAT_ID = "" #@param {type:"string"}
PUBLIC_BASE_URL = "https://be-clipper.fransiskus.my.id" #@param {type:"string"}

import os
os.environ['AUTO_CLIPPER_ALLOWED_ORIGINS'] = ALLOWED_ORIGINS
os.environ['AUTO_CLIPPER_TELEGRAM_BOT_TOKEN'] = TELEGRAM_BOT_TOKEN
os.environ['AUTO_CLIPPER_TELEGRAM_CHAT_ID'] = TELEGRAM_CHAT_ID
os.environ['AUTO_CLIPPER_PUBLIC_BASE_URL'] = PUBLIC_BASE_URL

%cd /content/potongan
!python -m backend.colab_api --cloudflare-token "$CLOUDFLARE_TUNNEL_TOKEN" --api-token "$API_SECRET_TOKEN"
```

- [ ] **Step 3: Validate notebook JSON**

Run: `python -c "import json; json.load(open('Auto_Clipper_Colab.ipynb')); print('valid')"`
Expected: `valid`.

- [ ] **Step 4: Commit**

```bash
git add Auto_Clipper_Colab.ipynb
git commit -m "feat: install mediapipe + add Telegram/public-base-url form fields to Colab notebook"
```

---

### Task 10: Port Provider Registry to Web

**Files:**
- Create: `web/src/lib/providers.ts`

**Interfaces:**
- Consumes: none.
- Produces: `ProviderId`, `ProviderConfig`, `PROVIDERS`, `DEFAULT_PROVIDER`, `getProviderConfig(id)`. Consumed by Task 11/12.

- [ ] **Step 1: Write the file (port from `src/lib/providers.ts`)**

Create `web/src/lib/providers.ts` with identical content to `src/lib/providers.ts` (verified in the desktop app):

```typescript
export type ProviderId =
  | "openai"
  | "gemini"
  | "deepseek"
  | "groq"
  | "openrouter"
  | "xai"
  | "mistral"
  | "custom"
  | "manual_ai";

export interface ProviderConfig {
  id: ProviderId;
  label: string;
  defaultModel: string;
  fallbackModels: string[];
  supportsModelFetch: boolean;
}

export const PROVIDERS: ProviderConfig[] = [
  { id: "openai", label: "OpenAI", defaultModel: "gpt-4o-mini", fallbackModels: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1-nano"], supportsModelFetch: true },
  { id: "gemini", label: "Google Gemini", defaultModel: "gemini-3.6-flash", fallbackModels: ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro"], supportsModelFetch: true },
  { id: "deepseek", label: "DeepSeek", defaultModel: "deepseek-chat", fallbackModels: ["deepseek-chat"], supportsModelFetch: true },
  { id: "groq", label: "Groq", defaultModel: "llama-3.3-70b-versatile", fallbackModels: ["llama-3.3-70b-versatile"], supportsModelFetch: true },
  { id: "openrouter", label: "OpenRouter", defaultModel: "openai/gpt-4o-mini", fallbackModels: ["openai/gpt-4o-mini"], supportsModelFetch: true },
  { id: "xai", label: "xAI Grok", defaultModel: "grok-2-latest", fallbackModels: ["grok-2-latest"], supportsModelFetch: true },
  { id: "mistral", label: "Mistral", defaultModel: "mistral-large-latest", fallbackModels: ["mistral-large-latest"], supportsModelFetch: true },
  { id: "custom", label: "Custom (OpenAI Compatible)", defaultModel: "", fallbackModels: [], supportsModelFetch: false },
  { id: "manual_ai", label: "Manual (Copy-Paste Prompt)", defaultModel: "", fallbackModels: [], supportsModelFetch: false },
];

export const DEFAULT_PROVIDER: ProviderId = "manual_ai";

export function getProviderConfig(id: ProviderId): ProviderConfig | undefined {
  return PROVIDERS.find((p) => p.id === id);
}
```

(Note: web default is `manual_ai` to preserve current behavior until the user selects a provider. The desktop registry's `DEFAULT_PROVIDER` is `openai`, but for web we keep the current manual default.)

- [ ] **Step 2: Verify build compiles**

Run: `cd web && npm run build`
Expected: build succeeds (the file is standalone; no consumers yet, so no errors).

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/providers.ts
git commit -m "feat: port AI provider registry to web"
```

---

### Task 11: Web API Client — test-ai, fetch models, drive search

**Files:**
- Modify: `web/src/api.ts`

**Interfaces:**
- Consumes: `apiFetch`, `API_URL` (existing).
- Produces:
  - `apiTestAi(payload): Promise<{status: string; message?: string}>`
  - `apiFetchModels(payload): Promise<{status: string; models: {id: string; label: string}[]}>`
  - `apiSearchGDrive(q: string): Promise<{status: string; results: {name: string; path: string}[]; truncated: boolean}>`

- [ ] **Step 1: Write the functions**

Append to `web/src/api.ts` (before the final `apiBrowseGDrive` or at the end):

```typescript
export interface ProviderModel {
  id: string;
  label: string;
}

export async function apiTestAi(payload: {
  provider: string;
  api_key: string;
  custom_base_url?: string;
  custom_model_name?: string;
  model?: string;
}): Promise<{ status: string; message?: string }> {
  return await apiFetch<{ status: string; message?: string }>("/api/settings/test-ai", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function apiFetchModels(payload: {
  provider: string;
  api_key: string;
  custom_base_url?: string;
  custom_model_name?: string;
}): Promise<{ status: string; models: ProviderModel[] }> {
  return await apiFetch<{ status: string; models: ProviderModel[] }>("/api/providers/models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface GDriveSearchResult {
  name: string;
  path: string;
}

export async function apiSearchGDrive(q: string): Promise<{
  status: string;
  results: GDriveSearchResult[];
  truncated: boolean;
}> {
  return await apiFetch<{ status: string; results: GDriveSearchResult[]; truncated: boolean }>(
    `/gdrive-search?q=${encodeURIComponent(q)}`
  );
}
```

- [ ] **Step 2: Verify build compiles**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add web/src/api.ts
git commit -m "feat: add web API clients for test-ai, fetch models, drive search"
```

---

### Task 12: AI Settings Context + Modal

**Files:**
- Create: `web/src/lib/aiSettings.ts` (context + hook)
- Create: `web/src/components/AISettingsModal.tsx`
- Modify: `web/src/App.tsx` (mount provider + gear button)

**Interfaces:**
- Consumes: `providers.ts` (Task 10), `apiTestAi`, `apiFetchModels` (Task 11).
- Produces:
  - `AISettingsProvider` (context provider), `useAISettings()` hook returning `{ provider, setProvider, model, setModel, apiKeys, setApiKey, customBaseUrl, setCustomBaseUrl, customModelName, setCustomModelName }`.
  - `<AISettingsModal open onClose />`.

- [ ] **Step 1: Write context**

Create `web/src/lib/aiSettings.ts`:

```typescript
import { createContext, useContext, useEffect, useState } from "react";
import type { ProviderId } from "./providers";
import { DEFAULT_PROVIDER, getProviderConfig } from "./providers";

const STORAGE_PROVIDER = "ac_provider";
const STORAGE_MODEL = "ac_model";
const STORAGE_KEYS = "ac_api_keys";

interface AISettingsValue {
  provider: ProviderId;
  setProvider: (p: ProviderId) => void;
  model: string;
  setModel: (m: string) => void;
  apiKeys: Record<string, string>;
  setApiKey: (provider: string, key: string) => void;
  customBaseUrl: string;
  setCustomBaseUrl: (u: string) => void;
  customModelName: string;
  setCustomModelName: (m: string) => void;
}

const AISettingsContext = createContext<AISettingsValue | null>(null);

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function AISettingsProvider({ children }: { children: React.ReactNode }) {
  const [provider, setProviderState] = useState<ProviderId>(() => {
    const saved = localStorage.getItem(STORAGE_PROVIDER) as ProviderId | null;
    return saved || DEFAULT_PROVIDER;
  });
  const [model, setModelState] = useState<string>(() => localStorage.getItem(STORAGE_MODEL) || "");
  const [apiKeys, setApiKeys] = useState<Record<string, string>>(() => readJson(STORAGE_KEYS, {}));
  const [customBaseUrl, setCustomBaseUrlState] = useState<string>(() => apiKeys["custom_base_url"] || "");
  const [customModelName, setCustomModelNameState] = useState<string>(() => apiKeys["custom_model_name"] || "");

  useEffect(() => {
    localStorage.setItem(STORAGE_PROVIDER, provider);
  }, [provider]);

  useEffect(() => {
    localStorage.setItem(STORAGE_MODEL, model);
  }, [model]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEYS, JSON.stringify(apiKeys));
  }, [apiKeys]);

  const setProvider = (p: ProviderId) => {
    setProviderState(p);
    const cfg = getProviderConfig(p);
    if (cfg && cfg.defaultModel) setModelState(cfg.defaultModel);
  };

  const setApiKey = (p: string, key: string) => {
    setApiKeys((prev) => {
      const next = { ...prev, [p]: key };
      if (p === "custom") {
        setCustomBaseUrlState(next["custom_base_url"] || "");
        setCustomModelNameState(next["custom_model_name"] || "");
      }
      return next;
    });
  };

  const setCustomBaseUrl = (u: string) => {
    setCustomBaseUrlState(u);
    setApiKeys((prev) => ({ ...prev, custom_base_url: u }));
  };
  const setCustomModelName = (m: string) => {
    setCustomModelNameState(m);
    setApiKeys((prev) => ({ ...prev, custom_model_name: m }));
  };

  return (
    <AISettingsContext.Provider
      value={{
        provider,
        setProvider,
        model,
        setModel: setModelState,
        apiKeys,
        setApiKey,
        customBaseUrl,
        setCustomBaseUrl,
        customModelName,
        setCustomModelName,
      }}
    >
      {children}
    </AISettingsContext.Provider>
  );
}

export function useAISettings(): AISettingsValue {
  const ctx = useContext(AISettingsContext);
  if (!ctx) throw new Error("useAISettings must be used within AISettingsProvider");
  return ctx;
}
```

- [ ] **Step 2: Write modal**

Create `web/src/components/AISettingsModal.tsx`:

```tsx
import type React from "react";
import { useEffect, useState } from "react";
import { X, KeyRound, Cpu, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react";
import { PROVIDERS, getProviderConfig } from "../lib/providers";
import { useAISettings } from "../lib/aiSettings";
import { apiTestAi, apiFetchModels, type ProviderModel } from "../api";

export const AISettingsModal: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { provider, setProvider, model, setModel, apiKeys, setApiKey, customBaseUrl, setCustomBaseUrl, customModelName, setCustomModelName } = useAISettings();
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [showKey, setShowKey] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setFeedback(null);
    setModels([]);
  }, [provider]);

  if (!open) return null;

  const cfg = getProviderConfig(provider);
  const keyVal = apiKeys[provider] || "";
  const isCustom = provider === "custom";

  const handleTest = async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const res = await apiTestAi({ provider, api_key: keyVal, custom_base_url: customBaseUrl, custom_model_name: customModelName, model });
      setFeedback({ ok: true, msg: res.message || "API Key is valid!" });
    } catch (e: any) {
      setFeedback({ ok: false, msg: e.message || "Test failed" });
    } finally {
      setLoading(false);
    }
  };

  const handleFetch = async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const res = await apiFetchModels({ provider, api_key: keyVal, custom_base_url: customBaseUrl, custom_model_name: customModelName });
      setModels(res.models || []);
      setFeedback({ ok: true, msg: `Loaded ${res.models?.length ?? 0} models` });
    } catch (e: any) {
      setFeedback({ ok: false, msg: e.message || "Failed to fetch models" });
    } finally {
      setLoading(false);
    }
  };

  const modelOptions = cfg?.fallbackModels || [];
  const allModels = Array.from(new Set([...modelOptions, ...models.map((m) => m.id)]));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between p-4 border-b border-neutral-800">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-amber-400" />
            <h3 className="font-semibold text-neutral-100">AI Engine Settings</h3>
          </div>
          <button onClick={onClose} className="p-1 text-neutral-400 hover:text-neutral-100 rounded-lg hover:bg-neutral-800">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-neutral-300">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as any)}
              className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm"
            >
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </div>

          {provider !== "manual_ai" && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-neutral-300 flex items-center gap-1.5">
                <KeyRound className="w-4 h-4 text-neutral-400" /> API Key
              </label>
              <div className="relative">
                <input
                  type={showKey ? "text" : "password"}
                  value={keyVal}
                  onChange={(e) => setApiKey(provider, e.target.value)}
                  className="w-full px-3 py-2 pr-16 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm"
                  placeholder={`${cfg?.label} API key`}
                />
                <button
                  type="button"
                  onClick={() => setShowKey((s) => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-neutral-400 hover:text-neutral-200"
                >
                  {showKey ? "Hide" : "Show"}
                </button>
              </div>
            </div>
          )}

          {isCustom && (
            <>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-neutral-300">Base URL (9router)</label>
                <input
                  value={customBaseUrl}
                  onChange={(e) => setCustomBaseUrl(e.target.value)}
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm font-mono"
                  placeholder="https://your-gateway.example/v1"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-neutral-300">Model Name</label>
                <input
                  value={customModelName}
                  onChange={(e) => setCustomModelName(e.target.value)}
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm font-mono"
                  placeholder="e.g. gpt-4o-mini"
                />
              </div>
            </>
          )}

          {provider !== "manual_ai" && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-neutral-300">Model</label>
              {allModels.length > 0 ? (
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm"
                >
                  {allModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <input
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm font-mono"
                  placeholder="model id"
                />
              )}
            </div>
          )}

          {feedback && (
            <div className={`p-3 rounded-xl flex items-start gap-2 text-xs ${feedback.ok ? "bg-emerald-950/40 border border-emerald-800/60 text-emerald-300" : "bg-red-950/40 border border-red-800/60 text-red-300"}`}>
              {feedback.ok ? <CheckCircle2 className="w-4 h-4 mt-0.5" /> : <AlertCircle className="w-4 h-4 mt-0.5" />}
              <span>{feedback.msg}</span>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-neutral-800 flex items-center justify-end gap-2">
          {provider !== "manual_ai" && (
            <button
              type="button"
              onClick={handleFetch}
              disabled={loading || (isCustom && !customBaseUrl)}
              className="px-3.5 py-2 bg-neutral-800 hover:bg-neutral-700 disabled:opacity-40 text-neutral-200 text-xs font-medium rounded-xl flex items-center gap-1.5"
            >
              <RefreshCw className="w-4 h-4" /> Fetch Models
            </button>
          )}
          <button
            type="button"
            onClick={handleTest}
            disabled={loading || provider === "manual_ai"}
            className="px-3.5 py-2 bg-amber-400 hover:bg-amber-300 disabled:opacity-40 text-neutral-950 text-xs font-bold rounded-xl"
          >
            {loading ? "Working…" : "Test Key"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 text-xs font-medium rounded-xl"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export default AISettingsModal;
```

- [ ] **Step 3: Wire into App.tsx**

In `web/src/App.tsx`:
- Add imports: `import { AISettingsProvider, useAISettings } from "./lib/aiSettings"; import { AISettingsModal } from "./components/AISettingsModal"; import { Settings } from "lucide-react";`
- Wrap `MainWizard` usage: change `export default function App()` to:

```tsx
export default function App() {
  return (
    <AISettingsProvider>
      <AuthGate>
        <MainWizard />
      </AuthGate>
    </AISettingsProvider>
  );
}
```

- Inside `MainWizard`, add state `const [settingsOpen, setSettingsOpen] = useState(false);` and a gear button in the header action group (near LogOut):

```tsx
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              className="p-2 rounded-xl text-neutral-400 hover:text-neutral-200 bg-neutral-900/60 hover:bg-neutral-800 border border-neutral-800 transition-colors"
              title="AI Engine Settings"
            >
              <Settings className="w-4 h-4" />
            </button>
```

- Render the modal once, near the end of `MainWizard` (before closing `</div>`):

```tsx
        <AISettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
```

- [ ] **Step 4: Verify build compiles**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/aiSettings.ts web/src/components/AISettingsModal.tsx web/src/App.tsx
git commit -m "feat: add AI settings context + modal to web"
```

---

### Task 13: StepInput — AI mode toggle, settings chip, source-to-Drive checkbox, full payload

**Files:**
- Modify: `web/src/components/Steps/StepInput.tsx`
- Modify: `web/src/types/job.ts`

**Interfaces:**
- Consumes: `useAISettings` (Task 12), `CreateJobPayload` (existing).
- Produces: payload now carries `provider`, `api_key`, `model`, `custom_base_url`, `custom_model_name`, `save_source_to_drive`.

- [ ] **Step 1: Extend the payload type**

In `web/src/types/job.ts`, add to `CreateJobPayload`:

```typescript
  save_source_to_drive?: boolean;
```

- [ ] **Step 2: Update StepInput**

In `web/src/components/Steps/StepInput.tsx`:
- Add import: `import { useAISettings } from "../../lib/aiSettings"; import { getProviderConfig } from "../../lib/providers";`
- Add a gear-open state callback via prop (or reuse a local "open settings" event). Add a new optional prop `onOpenSettings?: () => void;` to `StepInputProps`, and call `onOpenSettings()` from a chip button.
- Inside the component, get settings: `const ai = useAISettings();`
- Add state: `const [saveSource, setSaveSource] = useState<boolean>(true);`
- In `handleSubmit`, replace the hardcoded `provider: "manual"` with the settings-derived fields:

```typescript
    const payload: CreateJobPayload = {
      url: url.trim(),
      provider: ai.provider,
      api_key: ai.provider === "manual_ai" ? "" : ai.apiKeys[ai.provider] || "",
      title: title.trim() || `Auto Clip - ${new Date().toLocaleTimeString()}`,
      aspect_ratio: aspectRatio,
      caption_style: subtitlePreset === "podcast" ? "karaoke" : subtitlePreset === "viral_pop" ? "single_word" : "standard",
      burn_subs: true,
      quality: "best",
      whisper_model: whisperModel,
      language: language === "auto" ? "" : language,
      max_clips: maxClips,
      model: ai.provider === "manual_ai" ? "" : ai.model,
      custom_base_url: ai.provider === "custom" ? ai.customBaseUrl : "",
      custom_model_name: ai.provider === "custom" ? ai.customModelName : "",
      save_source_to_drive: saveSource,
      canvas_config: canvasConfig,
      subtitle_config: subtitleConfig,
    };
```

- Add the AI Engine chip + "Simpan video sumber ke Drive" checkbox UI. Insert a new section near the top of the form (after the title/source input), e.g.:

```tsx
      {/* AI Engine summary chip */}
      <div className="flex items-center justify-between p-3 bg-neutral-900/60 border border-neutral-800 rounded-xl">
        <div className="text-xs text-neutral-400 flex items-center gap-2">
          <Bot className="w-4 h-4 text-amber-400" />
          <span>AI Engine:</span>
          <span className="text-neutral-200 font-medium">
            {getProviderConfig(ai.provider)?.label}{ai.provider !== "manual_ai" && ai.model ? ` · ${ai.model}` : ""}
          </span>
        </div>
        <button
          type="button"
          onClick={onOpenSettings}
          className="text-xs font-semibold text-amber-400 hover:underline"
        >
          Ubah
        </button>
      </div>

      {/* Save source to Drive checkbox */}
      <label className="flex items-center gap-2 text-xs text-neutral-300">
        <input
          type="checkbox"
          checked={saveSource}
          onChange={(e) => setSaveSource(e.target.checked)}
          className="accent-amber-400"
        />
        Simpan video sumber ke Drive
      </label>
```

(Add `Bot` to the lucide-react import list if not already present; check the current import at the top of StepInput.tsx.)

- [ ] **Step 3: Wire onOpenSettings in App.tsx**

In `web/src/App.tsx`, pass `onOpenSettings={() => setSettingsOpen(true)}` to `<StepInput>`.

- [ ] **Step 4: Verify build compiles**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/Steps/StepInput.tsx web/src/types/job.ts web/src/App.tsx
git commit -m "feat: wire AI settings + save-source toggle into StepInput payload"
```

---

### Task 14: Adaptive Wizard (3-step AI / 4-step manual)

**Files:**
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `useAISettings` (Task 12).
- Produces: `getSteps(mode)` returning step config; step-sync logic maps status→step for both modes.

- [ ] **Step 1: Implement getSteps + mode-aware rendering**

In `web/src/App.tsx`, inside `MainWizard`:

```tsx
  const { provider } = useAISettings();
  const isManualMode = provider === "manual_ai";

  const STEPS_CONFIG = isManualMode
    ? [
        { num: 1 as WizardStep, label: "Input", desc: "URL & Style" },
        { num: 2 as WizardStep, label: "AI Prompt", desc: "Transcribe" },
        { num: 3 as WizardStep, label: "Highlights", desc: "Paste JSON" },
        { num: 4 as WizardStep, label: "Export", desc: "Render & Download" },
      ]
    : [
        { num: 1 as WizardStep, label: "Input", desc: "URL & Style" },
        { num: 2 as WizardStep, label: "AI Processing", desc: "Transcribe & Pick" },
        { num: 3 as WizardStep, label: "Export", desc: "Render & Download" },
      ];
```

- [ ] **Step 2: Map status → step for AI mode**

The existing step-sync `useEffect` (lines 84-96) maps: `AWAITING_MANUAL`→2/3, `CROPPING/PROCESSING/DONE/ERROR`→4, `DOWNLOADING/TRANSCRIBING`→2. For AI mode (3 steps), step 4 no longer exists — "Export" is step 3. Update the effect to be mode-aware:

```tsx
  useEffect(() => {
    if (jobId) {
      if (isManualMode) {
        if (status === "AWAITING_MANUAL" && prompt) {
          if (currentStep !== 2 && currentStep !== 3) setCurrentStep(2);
        } else if (status === "CROPPING" || status === "PROCESSING" || status === "DONE" || status === "ERROR") {
          if (currentStep !== 4) setCurrentStep(4);
        } else if (status === "DOWNLOADING" || status === "TRANSCRIBING") {
          if (currentStep !== 2 && currentStep !== 3) setCurrentStep(2);
        }
      } else {
        if (status === "CROPPING" || status === "PROCESSING" || status === "DONE" || status === "ERROR") {
          if (currentStep !== 3) setCurrentStep(3);
        } else if (status === "DOWNLOADING" || status === "TRANSCRIBING") {
          if (currentStep !== 2) setCurrentStep(2);
        }
      }
    }
  }, [status, jobId, prompt, currentStep, isManualMode]);
```

- [ ] **Step 3: Render AI Processing progress view for step 2 in AI mode**

Update the `{currentStep === 2 && ...}` block so that in AI mode (3-step), step 2 renders a progress-only view (reuse `StepPrompt` which already shows a loading state when there's no prompt, and won't show the "copy prompt" actions because `prompt` is empty). The existing `<StepPrompt>` already handles the empty-prompt (transcribing) state; keep it as-is but pass no `onNext` prompt action relevance. No structural change needed — `StepPrompt` displays the loading state automatically. Leave the render as:

```tsx
              {currentStep === 2 && (
                <StepPrompt
                  prompt={prompt}
                  jobId={jobId || "new_job"}
                  status={status}
                  progress={progress}
                  onNext={handleStep2Next}
                  onBack={() => setCurrentStep(1)}
                />
              )}
```

- [ ] **Step 4: Render Export at step 3 in AI mode**

Update the step-3 / step-4 render blocks to render `StepResult` at whichever step is the final one. Replace:

```tsx
              {currentStep === 3 && (
                <StepPaste ... />
              )}
              {currentStep === 4 && (
                <StepResult ... />
              )}
```

with:

```tsx
              {currentStep === 3 && isManualMode && (
                <StepPaste
                  jobId={jobId || "new_job"}
                  isSubmitting={isLoading}
                  onSubmit={handleStep3Submit}
                  onBack={() => setCurrentStep(2)}
                />
              )}
              {((currentStep === 4 && isManualMode) || (currentStep === 3 && !isManualMode)) && (
                <StepResult
                  jobId={jobId || "job"}
                  status={status}
                  progress={progress}
                  clips={clips}
                  failedCount={failedCount}
                  error={error}
                  activeJob={activeJob}
                  onReset={handleResetToNewJob}
                  onCancel={cancelCurrentJob}
                  onRetry={handleRetryJob}
                />
              )}
```

- [ ] **Step 5: Verify build compiles**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web/src/App.tsx
git commit -m "feat: adaptive wizard (3-step AI / 4-step manual)"
```

---

### Task 15: Drive Search Bar in Browser Modal

**Files:**
- Modify: `web/src/components/Steps/StepInput.tsx` (in `GDriveBrowserModal`)

**Interfaces:**
- Consumes: `apiSearchGDrive` (Task 11).

- [ ] **Step 1: Add search state + UI**

In `GDriveBrowserModal` (inside StepInput.tsx), add:

```tsx
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [searchResults, setSearchResults] = useState<{ name: string; path: string }[] | null>(null);
  const [searching, setSearching] = useState<boolean>(false);

  const handleSearch = async () => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const res = await apiSearchGDrive(q);
      setSearchResults(res.results || []);
    } catch (err: any) {
      setError(err.message || "Search failed");
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };
```

Add the search input UI right below the header (before the breadcrumb bar):

```tsx
        <div className="p-3 bg-neutral-950 flex items-center gap-2 border-b border-neutral-800">
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
            placeholder="Search videos in Drive..."
            className="flex-1 px-3 py-2 bg-neutral-900 border border-neutral-800 rounded-lg text-neutral-200 text-sm focus:outline-none focus:border-amber-400/80"
          />
          <button
            type="button"
            onClick={handleSearch}
            className="px-3 py-2 bg-amber-400 hover:bg-amber-300 text-neutral-950 text-xs font-bold rounded-lg"
          >
            {searching ? "..." : "Cari"}
          </button>
          {searchResults !== null && (
            <button
              type="button"
              onClick={() => { setSearchResults(null); setSearchQuery(""); }}
              className="px-2 py-2 text-neutral-400 hover:text-neutral-200 text-xs"
              title="Clear search"
            >
              <XCircle className="w-4 h-4" />
            </button>
          )}
        </div>
```

Update the list body to render search results when `searchResults !== null`:

```tsx
          {searchResults !== null ? (
            searchResults.length === 0 ? (
              <div className="text-center py-12 text-neutral-500 text-sm">Tidak ada video yang cocok dengan '{searchQuery}'</div>
            ) : (
              <div className="space-y-1">
                {searchResults.map((item, i) => (
                  <button
                    key={i}
                    onClick={() => onSelectFile(item.path)}
                    className="w-full flex items-center gap-3 p-3 text-left hover:bg-neutral-800 rounded-xl transition-colors group"
                  >
                    <FileVideo className="w-5 h-5 text-amber-400 group-hover:text-amber-300 flex-shrink-0" />
                    <span className="text-sm text-neutral-200 truncate">{item.name}</span>
                  </button>
                ))}
              </div>
            )
          ) : (
            /* existing browse list */
            <div className="space-y-1">
              {items.map((item, i) => ( ... ))}
            </div>
          )}
```

(Keep the existing browse `items.map(...)` block intact inside the `else` branch. Import `apiSearchGDrive` at the top of StepInput.tsx from `../../api`.)

- [ ] **Step 2: Verify build compiles**

Run: `cd web && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/Steps/StepInput.tsx
git commit -m "feat: add Drive search bar to browser modal"
```

---

## Self-Review Checklist

**Spec coverage:**
- AI Engine Selection (Settings modal) → Task 10, 12 ✓
- Adaptive wizard 3/4 step → Task 14 ✓
- Drive search → Task 5 (backend), 15 (frontend) ✓
- Save source to Drive → Task 3, 4 ✓
- Telegram notif → Task 1, 2, 9 ✓
- Face tracking MediaPipe → Task 6, 7, 9 ✓
- Custom provider (9router) model fetch → Task 8 ✓

**Placeholder scan:** none — every code step has full code.

**Type consistency:** `sync_source_to_persistent` defined Task 3, consumed Task 4. `notify_job_finished` defined Task 1, consumed Task 2. `sample_face_trajectory`/`detect_video_layout` re-exported by face_tracker Task 6, consumed by crop_utils Task 7. `useAISettings`/`AISettingsProvider` defined Task 12, consumed Task 13/14. `apiSearchGDrive` defined Task 11, consumed Task 15. `getProviderConfig` defined Task 10, consumed Task 12/13. `save_source_to_drive` in CreateJobRequest (Task 3) matches payload field (Task 13). All consistent.

**Gaps:** Task 9 (notebook) also sets `AUTO_CLIPPER_PUBLIC_BASE_URL` consumed by Task 1 (`_public_base_url`). ✓
