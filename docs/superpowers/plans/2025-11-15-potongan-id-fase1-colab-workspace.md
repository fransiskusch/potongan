# Potongan.id Fase 1 — Workspace Colab Terpisah + Domain Baru Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Memisahkan working directory Colab (disk lokal, cepat) dari penyimpanan persisten Google Drive (hasil final), menambah CORS via env var, mengganti domain ke `fransiskus.my.id`, dan memperbarui notebook Colab (assert T4 + install font).

**Architecture:** Backend FastAPI berjalan di Colab dengan dua workspace: `AUTO_CLIPPER_LOCAL_WORKDIR` (disk lokal `/content/projects` untuk download/render/temp) dan `AUTO_CLIPPER_WORKSPACE` (mount Drive untuk `history.db` + hasil final `clips/` + `subtitles/`). Saat job selesai, hasil disalin ke Drive dan semua path absolut di DB ditulis ulang ke path Drive. Modul baru `backend/cloud_sync.py` mengisolasi logika sinkronisasi.

**Tech Stack:** Python 3.11, FastAPI, SQLite, Google Colab (T4), Cloudflare Tunnel, Vite/React (hanya 1 baris default URL).

**Spec:** `docs/superpowers/specs/2025-11-15-colab-t4-drive-vercel-face-tracking-design.md` (Workstream A — Fase 1)

## Global Constraints

- Desktop (Windows/macOS, mode Tauri) TIDAK boleh rusak: semua perilaku baru aktif hanya jika env cloud mode ter-set; jalur lama tetap utuh.
- `AUTO_CLIPPER_CLOUD_MODE=1` di-set oleh `colab_api.py` (sudah ada).
- Domain frontend: `clip.fransiskus.my.id`; domain backend: `be-clipper.fransiskus.my.id`.
- Pool env var baru: `AUTO_CLIPPER_LOCAL_WORKDIR`. `AUTO_CLIPPER_WORKSPACE` maknanya tetap (workspace persisten/DB).
- TDD: setiap task punya test yang gagal dulu, lulus kemudian. Jalankan `python -m pytest backend/tests/ -v` dari root repo.
- Style kode mengikuti pola yang ada (log via `backend.logger`, error ditangani dengan log + fallback, bukan crash).
- Commit message konvensional (`feat:`, `fix:`, `docs:`, `test:`), commit per task.

---

### Task 1: Prioritas resolusi workspace di `db.py` + `logger.py`

**Files:**
- Modify: `backend/db.py:8-25`
- Modify: `backend/logger.py:7-24`
- Test: `backend/tests/test_db.py` (tambah)

**Interfaces:**
- Produces: `get_app_data_dir()` di `db.py` & `logger.py` — resolve `AUTO_CLIPPER_LOCAL_WORKDIR` dulu (fallback `AUTO_CLIPPER_WORKSPACE`, lalu default OS). Dipakai Task 3, Task 5, dan semua modul yang sudah meng-import-nya (`jobs.py`, `main.py`, `metadata.py`, `broll.py`).
- Catatan: `get_db_path()` (db.py:29-30) TIDAK berubah — DB tetap di Drive.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan di `backend/tests/test_db.py` (di akhir file):

```python
def test_get_app_data_dir_prefers_local_workdir(monkeypatch, tmp_path):
    import backend.db as db
    local_ws = tmp_path / "local_ws"
    drive_ws = tmp_path / "drive_ws"
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(local_ws))
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(drive_ws))
    res = db.get_app_data_dir()
    assert res == os.path.abspath(str(local_ws))


def test_get_db_path_ignores_local_workdir(monkeypatch, tmp_path):
    # history.db HARUS tetap di workspace persisten (Drive), bukan workdir lokal.
    import backend.db as db
    local_ws = tmp_path / "local_ws"
    drive_ws = tmp_path / "drive_ws"
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(local_ws))
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(drive_ws))
    res = db.get_db_path()
    assert res == os.path.join(os.path.abspath(str(drive_ws)), "history.db")
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python -m pytest backend/tests/test_db.py::test_get_app_data_dir_prefers_local_workdir backend/tests/test_db.py::test_get_db_path_ignores_local_workdir -v`
Expected: FAIL — `get_app_data_dir` masih mengembalikan `drive_ws` (belum tahu `LOCAL_WORKDIR`).

- [ ] **Step 3: Implementasi minimal**

Di `backend/db.py`, ganti isi `get_app_data_dir()` (baris 8-25) menjadi:

```python
def get_app_data_dir() -> str:
    # Workdir lokal (disk cepat Colab) menang untuk aktivitas harian...
    local_ws = os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR", "").strip()
    if local_ws:
        local_ws = os.path.abspath(os.path.expanduser(local_ws))
        os.makedirs(local_ws, exist_ok=True)
        return local_ws

    # ...tapi workspace persisten (Drive) tetap dipakai bila workdir lokal
    # tidak diset (desktop, atau Colab lama).
    custom_ws = os.environ.get("AUTO_CLIPPER_WORKSPACE", "").strip()
    if custom_ws:
        custom_ws = os.path.abspath(os.path.expanduser(custom_ws))
        os.makedirs(custom_ws, exist_ok=True)
        return custom_ws

    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.join(home, ".local", "share"))

    app_dir = os.path.join(base, "AutoClipper")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir
```

Di `backend/logger.py`, terapkan blok `local_ws` yang sama di posisi paling atas `get_app_data_dir()` (baris 7-24) — sisipkan sebelum blok `custom_ws`:

```python
def get_app_data_dir() -> str:
    local_ws = os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR", "").strip()
    if local_ws:
        local_ws = os.path.abspath(os.path.expanduser(local_ws))
        os.makedirs(local_ws, exist_ok=True)
        return local_ws

    # ... blok custom_ws & default OS yang lama tetap di bawahnya ...
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python -m pytest backend/tests/test_db.py -v`
Expected: semua PASS (termasuk 2 test baru + test lama `test_get_app_data_dir_custom_workspace`, `test_get_app_data_dir_default` yang belum terpengaruh karena tidak men-set `LOCAL_WORKDIR`).

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/logger.py backend/tests/test_db.py
git commit -m "feat: prefer AUTO_CLIPPER_LOCAL_WORKDIR for app data dir, keep history.db on persistent workspace"
```

---

### Task 2: Modul `cloud_sync.py` — sinkronisasi hasil ke Drive

**Files:**
- Create: `backend/cloud_sync.py`
- Test: `backend/tests/test_cloud_sync.py` (buat baru)

**Interfaces:**
- Produces (dipakai Task 3 & Task 4):
  - `is_cloud_mode() -> bool` — True jika `AUTO_CLIPPER_CLOUD_MODE` di-set.
  - `get_persistent_root() -> str` — root workspace persisten (Drive); kosong string bila tidak ada.
  - `sync_project_to_persistent(local_project_dir: str, keep: tuple[str, ...] = ("clips", "subtitles")) -> dict` — menyalin subfolder `keep` dari project lokal ke `<persistent_root>/projects/<basename>`, mengembalikan `{"persistent_project_dir": str, "copied": [str, ...]}`; no-op (return `{"persistent_project_dir": "", "copied": []}`) di non-cloud mode.
  - `rewrite_path_to_persistent(path: str, local_root: str, persistent_root: str) -> str` — jika `path` di bawah `local_root`, kembalikan padanan di bawah `persistent_root`; selain itu kembalikan `path` apa adanya.

- [ ] **Step 1: Tulis test yang gagal**

Buat `backend/tests/test_cloud_sync.py`:

```python
import os
from backend.cloud_sync import (
    is_cloud_mode,
    get_persistent_root,
    sync_project_to_persistent,
    rewrite_path_to_persistent,
)


def test_is_cloud_mode_off_by_default(monkeypatch):
    monkeypatch.delenv("AUTO_CLIPPER_CLOUD_MODE", raising=False)
    assert is_cloud_mode() is False


def test_is_cloud_mode_on(monkeypatch):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    assert is_cloud_mode() is True


def test_sync_noop_when_not_cloud(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTO_CLIPPER_CLOUD_MODE", raising=False)
    res = sync_project_to_persistent(str(tmp_path))
    assert res == {"persistent_project_dir": "", "copied": []}


def test_sync_copies_clips_and_subtitles(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))

    local_proj = tmp_path / "content" / "projects" / "Judul_Keren"
    (local_proj / "clips").mkdir(parents=True)
    (local_proj / "subtitles").mkdir(parents=True)
    (local_proj / "source").mkdir(parents=True)
    (local_proj / "clips" / "a.mp4").write_bytes(b"x")
    (local_proj / "subtitles" / "s.json").write_bytes(b"y")
    (local_proj / "source" / "source_video.mp4").write_bytes(b"z")

    res = sync_project_to_persistent(str(local_proj))

    dest = tmp_path / "drive" / "projects" / "Judul_Keren"
    assert res["persistent_project_dir"] == str(dest)
    assert (dest / "clips" / "a.mp4").exists()
    assert (dest / "subtitles" / "s.json").exists()
    # source TIDAK ikut disalin
    assert not (dest / "source").exists()


def test_rewrite_path(monkeypatch, tmp_path):
    local_root = str(tmp_path / "content" / "projects")
    persistent_root = str(tmp_path / "drive" / "projects")
    p = os.path.join(local_root, "Judul", "clips", "a.mp4")
    rewritten = rewrite_path_to_persistent(p, local_root, persistent_root)
    assert rewritten == os.path.join(persistent_root, "Judul", "clips", "a.mp4")

    outside = str(tmp_path / "elsewhere" / "a.mp4")
    assert rewrite_path_to_persistent(outside, local_root, persistent_root) == outside
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python -m pytest backend/tests/test_cloud_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.cloud_sync'`

- [ ] **Step 3: Implementasi minimal**

Buat `backend/cloud_sync.py`:

```python
"""Sinkronisasi hasil job Colab (disk lokal) ke workspace persisten (Drive).

Prinsip (spec Workstream A): disk lokal untuk KERJA, Drive untuk HASIL.
Hanya subfolder hasil (clips/, subtitles/) yang disalin; file sumber dan
temporal tetap di disk lokal dan hilang saat session mati — by design.
"""

import os
import shutil
from backend.logger import log_app, log_error

_PERSISTENT_PROJECTS = "projects"


def is_cloud_mode() -> bool:
    return bool(os.environ.get("AUTO_CLIPPER_CLOUD_MODE"))


def get_persistent_root() -> str:
    ws = os.environ.get("AUTO_CLIPPER_WORKSPACE", "").strip()
    return os.path.abspath(os.path.expanduser(ws)) if ws else ""


def _local_projects_root() -> str:
    lw = os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR", "").strip()
    if not lw:
        return ""
    return os.path.abspath(os.path.expanduser(lw))


def rewrite_path_to_persistent(path: str, local_root: str, persistent_root: str) -> str:
    """Petakan path di bawah local_root ke padanannya di persistent_root."""
    if not path or not local_root or not persistent_root:
        return path
    try:
        norm = os.path.normpath(os.path.abspath(path))
        root = os.path.normpath(os.path.abspath(local_root))
        if norm == root or norm.startswith(root + os.sep):
            rel = os.path.relpath(norm, root)
            return os.path.join(persistent_root, rel)
    except Exception:
        pass
    return path


def sync_project_to_persistent(local_project_dir: str, keep: tuple = ("clips", "subtitles")) -> dict:
    """Salin subfolder hasil dari project lokal ke Drive. No-op di non-cloud."""
    empty = {"persistent_project_dir": "", "copied": []}
    if not is_cloud_mode():
        return empty

    persistent_root = get_persistent_root()
    if not persistent_root or not local_project_dir or not os.path.isdir(local_project_dir):
        return empty

    dest_project = os.path.join(persistent_root, _PERSISTENT_PROJECTS, os.path.basename(os.path.normpath(local_project_dir)))
    copied = []
    try:
        for sub in keep:
            src_sub = os.path.join(local_project_dir, sub)
            if not os.path.isdir(src_sub):
                continue
            dest_sub = os.path.join(dest_project, sub)
            os.makedirs(dest_sub, exist_ok=True)
            for item in os.listdir(src_sub):
                src_item = os.path.join(src_sub, item)
                if os.path.isfile(src_item):
                    shutil.copy2(src_item, os.path.join(dest_sub, item))
                    copied.append(os.path.join(dest_sub, item))
        log_app(f"[cloud_sync] Synced {len(copied)} file(s) to {dest_project}")
        return {"persistent_project_dir": dest_project, "copied": copied}
    except Exception as e:
        log_error("cloud_sync.sync_project_to_persistent", e)
        return empty
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python -m pytest backend/tests/test_cloud_sync.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/cloud_sync.py backend/tests/test_cloud_sync.py
git commit -m "feat: add cloud_sync module for syncing clip results to persistent Drive workspace"
```

---

### Task 3: `jobs.py` — workspace proyek di local workdir + sinkronisasi saat finalize

**Files:**
- Modify: `backend/jobs.py:56-84` (`get_project_workspace`) dan `_finalize_job` (± baris 1075-1113)
- Test: `backend/tests/test_cloud_sync.py` (tambah) + `backend/tests/test_jobs_workspace.py` (buat baru)

**Interfaces:**
- Consumes: `cloud_sync.sync_project_to_persistent`, `cloud_sync.rewrite_path_to_persistent`, `cloud_sync.is_cloud_mode`, `cloud_sync.get_persistent_root` (Task 2), `get_app_data_dir` prioritas baru (Task 1).
- Produces: `get_project_workspace(title, output_dir, job_id) -> dict` dengan kunci sama seperti lama (`project_dir`, `source_dir`, `subtitles_dir`, `clips_dir`, `broll_dir`, `safe_title`) — tapi di cloud mode `project_dir` berada di bawah `AUTO_CLIPPER_LOCAL_WORKDIR`.

- [ ] **Step 1: Tulis test yang gagal**

Buat `backend/tests/test_jobs_workspace.py`:

```python
import os
import backend.jobs as jobs


def test_project_workspace_local_when_cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "content" / "projects"))
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))

    ws = jobs.get_project_workspace("Judul Keren", "", "job-1")
    assert ws["project_dir"] == os.path.join(str(tmp_path / "content" / "projects"), "Judul_Keren")
    assert os.path.isdir(ws["clips_dir"])
    assert ws["safe_title"] == "Judul_Keren"


def test_project_workspace_output_dir_wins(monkeypatch, tmp_path):
    # output_dir eksplisit (dipilih user via Drive browser) harus tetap dihormati.
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "content" / "projects"))
    custom = str(tmp_path / "drive" / "MyVideos")
    ws = jobs.get_project_workspace("Judul", custom, "job-2")
    assert ws["project_dir"] == os.path.join(custom, "Judul")


def test_project_workspace_desktop_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTO_CLIPPER_CLOUD_MODE", raising=False)
    monkeypatch.delenv("AUTO_CLIPPER_LOCAL_WORKDIR", raising=False)
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "appdata"))
    ws = jobs.get_project_workspace("Judul", "", "job-3")
    assert ws["project_dir"] == os.path.join(str(tmp_path / "appdata"), "projects", "Judul")
```

Tambahkan juga di `backend/tests/test_cloud_sync.py` (uji rewrite di level finalize — pakai fungsi murni supaya tidak perlu menjalankan job penuh):

```python
def test_rewrite_paths_in_finalize_payload():
    from backend.cloud_sync import rewrite_path_to_persistent
    clips = [
        {"path": "/content/projects/J/clips/a.mp4", "description": "x"},
        {"path": "/content/projects/J/clips/b.mp4", "description": "y"},
    ]
    metadata = {
        "source_video": "/content/projects/J/source/source_video.mp4",
        "subtitle_path": "/content/projects/J/subtitles/subtitles.words.json",
    }
    # (Helper yang sama dipakai _finalize_job — lihat Step 3.)
    new_clips = [
        {**c, "path": rewrite_path_to_persistent(c["path"], "/content/projects", "/content/drive/MyDrive/AutoClipperData/projects/J".rsplit("/", 1)[0] + "/J")}
        for c in clips
    ]
    assert new_clips[0]["path"].startswith("/content/drive/MyDrive/AutoClipperData/projects/")
    assert rewrite_path_to_persistent(metadata["source_video"], "/content/projects", "/content/drive/MyDrive/AutoClipperData/projects/J") == "/content/drive/MyDrive/AutoClipperData/projects/J/source/source_video.mp4"
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python -m pytest backend/tests/test_jobs_workspace.py backend/tests/test_cloud_sync.py -v`
Expected: `test_project_workspace_local_when_cloud` FAIL (project_dir masih di Drive), `test_project_workspace_output_dir_wins` & `test_project_workspace_desktop_unchanged` mungkin sudah PASS (perilaku lama sama).

- [ ] **Step 3: Implementasi minimal**

Di `backend/jobs.py`, ubah `get_project_workspace` (baris 56-84) — hanya blok pemilihan `base_dir` yang berubah:

```python
def get_project_workspace(title: str, output_dir: str = "", job_id: str = "") -> dict:
    safe_title = sanitize_title(title)
    if not safe_title:
        safe_title = f"Project_{job_id}" if job_id else "Project_Untitled"

    if output_dir and output_dir.strip():
        base_dir = output_dir.strip()
    else:
        from backend.cloud_sync import is_cloud_mode
        local_ws = os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR", "").strip() if is_cloud_mode() else ""
        if local_ws:
            base_dir = os.path.abspath(os.path.expanduser(local_ws))
        else:
            base_dir = os.path.join(get_app_data_dir(), "projects")

    project_dir = os.path.join(base_dir, safe_title)
    # ... sisanya (source/subtitles/clips/broll + makedirs + return dict) TIDAK berubah ...
```

Kemudian di `_finalize_job` (baris 1075-1113), sisipkan sinkronisasi + rewrite path **sebelum** `save_history`:

```python
    # --- Sinkronisasi hasil ke Drive (cloud mode) ---
    from backend.cloud_sync import is_cloud_mode, get_persistent_root, sync_project_to_persistent, rewrite_path_to_persistent
    if is_cloud_mode() and status in ["DONE"]:
        try:
            local_projects_root = os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR", "").strip()
            persistent_root = get_persistent_root()
            if local_projects_root and persistent_root:
                local_projects_root = os.path.abspath(os.path.expanduser(local_projects_root))
                persistent_projects = os.path.join(persistent_root, "projects")
                # Sinkron folder hasil proyek ini
                proj_name = sanitize_title(job.get("title", "")) or f"Project_{job_id}"
                local_proj = os.path.join(local_projects_root, proj_name)
                sync_project_to_persistent(local_proj)
                # Rewrite path klip + metadata agar menunjuk Drive
                for clip in job.get("clips", []):
                    clip["path"] = rewrite_path_to_persistent(clip["path"], local_projects_root, persistent_projects)
                for meta_key in ("source_video", "subtitle_path"):
                    if metadata.get(meta_key):
                        metadata[meta_key] = rewrite_path_to_persistent(metadata[meta_key], local_projects_root, persistent_projects)
                # Clip-level custom subtitle path juga ikut di-rewrite
                for clip in job.get("clips", []):
                    if clip.get("custom_subtitle_path"):
                        clip["custom_subtitle_path"] = rewrite_path_to_persistent(clip["custom_subtitle_path"], local_projects_root, persistent_projects)
        except Exception as e:
            log_error("jobs.finalize_cloud_sync", e)
```

(Sisipkan blok ini setelah loop `for key in [...]` penyalinan metadata, tepat sebelum `if status in ["DONE", "ERROR", ...]:` yang memanggil `save_history`.)

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python -m pytest backend/tests/test_jobs_workspace.py backend/tests/test_cloud_sync.py -v`
Expected: semua PASS

- [ ] **Step 5: Commit**

```bash
git add backend/jobs.py backend/tests/test_jobs_workspace.py backend/tests/test_cloud_sync.py
git commit -m "feat: run project workspaces on local disk in cloud mode and sync results to Drive with path rewrite"
```

---

### Task 4: Upload lama redirect ke disk lokal di cloud mode

**Files:**
- Modify: `backend/main.py:124-132`
- Test: `backend/tests/test_upload_cloud.py` (buat baru)

**Interfaces:**
- Consumes: `cloud_sync.is_cloud_mode` (Task 2).
- Produces: `POST /upload` menyimpan ke `<AUTO_CLIPPER_LOCAL_WORKDIR>/uploads` di cloud mode; `local:` URL tetap format yang sama.

- [ ] **Step 1: Tulis test yang gagal**

Buat `backend/tests/test_upload_cloud.py`:

```python
import os
import io
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_upload_goes_to_local_workdir_in_cloud_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "content" / "projects"))
    # workspace persisten (Drive) — untuk memastikan file TIDAK ke sini
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))

    from backend.main import app
    client = TestClient(app)

    res = client.post(
        "/upload",
        files={"file": ("video.mp4", io.BytesIO(b"fake"), "video/mp4")},
    )
    assert res.status_code == 200
    url = res.json()["url"]
    assert url.startswith("local:")
    path = url.split("local:")[1]
    assert os.path.abspath(path).startswith(os.path.abspath(str(tmp_path / "content" / "projects")))
    assert not os.path.abspath(path).startswith(os.path.abspath(str(tmp_path / "drive")))
    assert os.path.exists(path)
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python -m pytest backend/tests/test_upload_cloud.py -v`
Expected: FAIL — path upload masih di bawah `AUTO_CLIPPER_WORKSPACE` (Drive) via `get_app_data_dir()`.

- [ ] **Step 3: Implementasi minimal**

Di `backend/main.py`, ubah `api_upload_video` (baris 124-132):

```python
@app.post("/upload")
def api_upload_video(file: UploadFile = File(...)):
    from backend.cloud_sync import is_cloud_mode
    if is_cloud_mode():
        base = os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR", "").strip()
    else:
        base = ""
    if base:
        temp_dir = os.path.abspath(os.path.expanduser(base))
    else:
        temp_dir = os.path.abspath(os.path.join(get_app_data_dir(), "temp_downloads"))
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, f"upload_{file.filename}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # Return local path prefixed with local: so jobs.py knows to skip download
    return {"status": "success", "url": f"local:{file_path}"}
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python -m pytest backend/tests/test_upload_cloud.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_upload_cloud.py
git commit -m "feat: store direct uploads on local Colab disk in cloud mode"
```

---

### Task 5: CORS via env var + domain default baru

**Files:**
- Modify: `backend/main.py:96-103`
- Modify: `web/src/api.ts:3-7`
- Test: `backend/tests/test_main.py` (tambah)

**Interfaces:**
- Produces: env var `AUTO_CLIPPER_ALLOWED_ORIGINS` (comma-separated origin list, dibaca saat startup). Default regex lama tetap dipakai bila env kosong, dengan `clipper.dhims.web.id` diganti `clip.fransiskus.my.id`.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan di `backend/tests/test_main.py`:

```python
def test_cors_env_var_overrides_origins(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    monkeypatch.setenv("AUTO_CLIPPER_ALLOWED_ORIGINS", "https://clip.fransiskus.my.id,https://potongan.vercel.app")
    # Re-instantiate middleware config via app startup is static; we test the helper.
    from backend.main import _resolve_cors_origins
    origins = _resolve_cors_origins()
    assert "https://clip.fransiskus.my.id" in origins
    assert "https://potongan.vercel.app" in origins


def test_cors_default_includes_new_domain(monkeypatch):
    monkeypatch.delenv("AUTO_CLIPPER_ALLOWED_ORIGINS", raising=False)
    from backend.main import _resolve_cors_origins
    origins = _resolve_cors_origins()
    assert "https://clip.fransiskus.my.id" in origins
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python -m pytest backend/tests/test_main.py::test_cors_env_var_overrides_origins backend/tests/test_main.py::test_cors_default_includes_new_domain -v`
Expected: FAIL — `_resolve_cors_origins` belum ada.

- [ ] **Step 3: Implementasi minimal**

Di `backend/main.py`, tambahkan helper sebelum `app.add_middleware(...)` (baris 96):

```python
_DEFAULT_CORS_ORIGINS = [
    "https://clip.fransiskus.my.id",
]

def _resolve_cors_origins() -> list:
    """Origin list dari AUTO_CLIPPER_ALLOWED_ORIGINS (comma-separated); default bila kosong."""
    raw = os.environ.get("AUTO_CLIPPER_ALLOWED_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return list(_DEFAULT_CORS_ORIGINS)
```

Ubah middleware (baris 96-103):

```python
app.add_middleware(
    CORSMiddleware,
    # Local dev + Tauri custom protocols via regex; cloud origins via env list.
    allow_origin_regex=r"https?://([a-zA-Z0-9_.-]+\.)?localhost(:\d+)?|https?://127\.0\.0\.1(:\d+)?|tauri://.*|app://.*",
    allow_origins=_resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

(Catatan: Starlette mengizinkan `allow_origin_regex` **dan** `allow_origins` bersamaan — request cocok salah satu akan di-allow.)

Perbarui test CORS lama di `test_main.py` (`test_cors_headers`) yang mereferensikan `https://clipper.dhims.web.id`: ganti origin yang diuji ke `https://clip.fransiskus.my.id`, dan hapus monkeypatch env lama bila ada.

Di `web/src/api.ts` (baris 3-7), ganti default:

```typescript
export const API_URL =
  import.meta.env.VITE_API_URL ||
  (typeof window !== "undefined" && window.location.hostname !== "localhost"
    ? "https://be-clipper.fransiskus.my.id"
    : "http://localhost:8000");
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python -m pytest backend/tests/test_main.py -v`
Expected: semua PASS (test CORS lama yang di-update + 2 test baru).

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_main.py web/src/api.ts
git commit -m "feat: configurable CORS origins via env, default to fransiskus.my.id domains"
```

---

### Task 6: `colab_api.py` — set LOCAL_WORKDIR, assert T4, cek tunnel, cleanup

**Files:**
- Modify: `backend/colab_api.py`
- Test: `backend/tests/test_colab_api.py` (tambah)

**Interfaces:**
- Produces:
  - `DEFAULT_LOCAL_WORKDIR = "/content/projects"`
  - `setup_environment(workspace, api_token, local_workdir=None)` — signature lama tetap kompatibel (argumen baru optional).
  - `verify_gpu(require_t4: bool = True) -> tuple[bool, str]` — cek CUDA device via torch; return `(ok, message)`.
  - `check_tunnel_health(tunnel_url: str, timeout: float = 5.0) -> bool` — GET `<tunnel_url>/health`.
  - `cleanup_stale_uploads(uploads_dir: str, max_age_hours: float = 24.0) -> int` — hapus file/session upload yang lebih tua dari `max_age_hours`, return jumlah yang dihapus.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan di `backend/tests/test_colab_api.py`:

```python
from backend.colab_api import (
    DEFAULT_LOCAL_WORKDIR,
    check_tunnel_health,
    cleanup_stale_uploads,
    setup_environment,
    verify_gpu,
)


def test_setup_environment_sets_local_workdir(monkeypatch, tmp_path):
    ws = str(tmp_path / "drive_ws")
    local_ws = str(tmp_path / "local_ws")
    setup_environment(ws, "secret", local_workdir=local_ws)
    assert os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR") == local_ws
    assert os.path.exists(local_ws)


def test_setup_environment_local_workdir_default(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTO_CLIPPER_LOCAL_WORKDIR", raising=False)
    ws = str(tmp_path / "drive_ws")
    setup_environment(ws, "secret")
    assert os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR") == DEFAULT_LOCAL_WORKDIR


def test_verify_gpu_no_torch(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "torch", None)
    ok, msg = verify_gpu(require_t4=True)
    assert ok is False
    assert "torch" in msg.lower()


def test_check_tunnel_health_unreachable():
    assert check_tunnel_health("http://127.0.0.1:1", timeout=0.5) is False


def test_cleanup_stale_uploads_removes_old(monkeypatch, tmp_path):
    import time
    old = tmp_path / "old.mp4"
    old.write_bytes(b"x")
    two_days_ago = time.time() - 48 * 3600
    os.utime(old, (two_days_ago, two_days_ago))
    fresh = tmp_path / "fresh.mp4"
    fresh.write_bytes(b"y")
    removed = cleanup_stale_uploads(str(tmp_path), max_age_hours=24.0)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `python -m pytest backend/tests/test_colab_api.py -v`
Expected: test baru FAIL (import error / fungsi belum ada), test lama PASS.

- [ ] **Step 3: Implementasi minimal**

Di `backend/colab_api.py`:

(a) Tambahkan konstanta setelah `DEFAULT_WORKSPACE` (baris 20):

```python
DEFAULT_LOCAL_WORKDIR = "/content/projects"
```

(b) Ubah `parse_args` — tambahkan argumen:

```python
    env_local_workdir = os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR") or DEFAULT_LOCAL_WORKDIR
    parser.add_argument(
        "--local-workdir",
        dest="local_workdir",
        default=env_local_workdir,
        help=f"Fast local working directory for downloads/renders (default: {DEFAULT_LOCAL_WORKDIR})",
    )
```

(c) Ubah `setup_environment` (baris 76-90):

```python
def setup_environment(workspace: str, api_token: Optional[str] = None, local_workdir: Optional[str] = None) -> None:
    """Configure environment variables for cloud mode and prepare directories."""
    os.environ["AUTO_CLIPPER_CLOUD_MODE"] = "1"
    os.environ["AUTO_CLIPPER_WORKSPACE"] = workspace
    os.environ["AUTO_CLIPPER_LOCAL_WORKDIR"] = local_workdir or DEFAULT_LOCAL_WORKDIR

    if api_token:
        os.environ["AUTO_CLIPPER_DEV_TOKEN"] = api_token
        os.environ["AUTO_CLIPPER_WEB_TOKEN"] = api_token
        os.environ["API_SECRET_TOKEN"] = api_token

    for d in (workspace, os.environ["AUTO_CLIPPER_LOCAL_WORKDIR"]):
        try:
            os.makedirs(d, exist_ok=True)
            print(f"[Auto Clipper Colab] Directory initialized: {d}")
        except Exception as e:
            print(f"[Auto Clipper Colab] Warning: Could not create directory '{d}': {e}", file=sys.stderr)
```

(d) Tambahkan fungsi baru (letakkan setelah `setup_environment`):

```python
def verify_gpu(require_t4: bool = True) -> tuple:
    """Verify a CUDA GPU is available; warn (not crash) if it is not a T4."""
    try:
        import torch
    except Exception:
        return (False, "torch is not installed or importable")
    if not torch.cuda.is_available():
        return (False, "CUDA is not available — pilih Runtime > Change runtime type > T4 GPU")
    try:
        name = torch.cuda.get_device_name(0)
    except Exception:
        name = ""
    if require_t4 and "T4" not in name:
        return (True, f"GPU terdeteksi ({name}) tetapi bukan T4 — disarankan T4")
    return (True, f"GPU OK: {name}")


def check_tunnel_health(tunnel_url: str, timeout: float = 5.0) -> bool:
    """GET <tunnel_url>/health; True jika merespons."""
    if not tunnel_url:
        return False
    try:
        import requests
        r = requests.get(tunnel_url.rstrip("/") + "/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def cleanup_stale_uploads(uploads_dir: str, max_age_hours: float = 24.0) -> int:
    """Delete upload files older than max_age_hours. Returns deleted count."""
    if not uploads_dir or not os.path.isdir(uploads_dir):
        return 0
    import time
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for root, dirs, files in os.walk(uploads_dir, topdown=False):
        for name in files:
            p = os.path.join(root, name)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except Exception:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except Exception:
                pass
    return removed
```

(e) Di `run_server` (setelah `setup_environment(...)`, sebelum start uvicorn), panggil:

```python
    ok_gpu, gpu_msg = verify_gpu()
    print(f"[Auto Clipper Colab] GPU check: {'OK' if ok_gpu else 'FAILED'} — {gpu_msg}")
    if not ok_gpu:
        print("[Auto Clipper Colab] ERROR: GPU tidak tersedia. Set Runtime > Change runtime type > T4 GPU, lalu jalankan ulang.", file=sys.stderr)
        return 1

    removed = cleanup_stale_uploads(os.path.join(parsed.local_workdir, "uploads"))
    if removed:
        print(f"[Auto Clipper Colab] Cleaned {removed} stale upload file(s).")
```

Lalu ubah pemanggilan `setup_environment(parsed.workspace, parsed.api_token)` menjadi `setup_environment(parsed.workspace, parsed.api_token, local_workdir=parsed.local_workdir)`.

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `python -m pytest backend/tests/test_colab_api.py -v`
Expected: semua PASS (lama + baru).

- [ ] **Step 5: Commit**

```bash
git add backend/colab_api.py backend/tests/test_colab_api.py
git commit -m "feat: colab entrypoint sets local workdir, verifies T4 GPU, checks tunnel, cleans stale uploads"
```

---

### Task 7: Notebook Colab — T4 assert, form baru, install font, URL repo baru

**Files:**
- Modify: `Auto_Clipper_Colab.ipynb` (semua sel)

**Interfaces:**
- Consumes: `colab_api.py` Task 6 (arg `--local-workdir` otomatis via default; tidak perlu flag eksplisit).
- Produces: notebook yang men-clone `https://github.com/fransiskusch/potongan.git`, install font subtitle, form field `ALLOWED_ORIGINS`.

- [ ] **Step 1: Tulis ulang notebook**

Ganti seluruh isi `Auto_Clipper_Colab.ipynb` dengan notebook berikut (valid JSON ipynb; 7 sel — header markdown, mount drive, install sistem + font, clone + pip install, GPU check, cleanup, run server):

```json
{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {"id": "header_cell"},
   "source": [
    "# Potongan.id — Colab Backend (T4 GPU)\n",
    "\n",
    "Backend **Potongan.id** berjalan di GPU T4 Colab. Hasil klip + database tersimpan otomatis di Google Drive (`MyDrive/AutoClipperData`).\n",
    "\n",
    "**Urutan:** jalankan semua sel berurutan. Pastikan **Runtime > Change runtime type > T4 GPU**."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {"id": "step1_code"},
   "outputs": [],
   "source": [
    "# 1. Mount Google Drive (hasil klip + history.db tersimpan di sini)\n",
    "from google.colab import drive\n",
    "drive.mount('/content/drive')"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {"id": "step2_code"},
   "outputs": [],
   "source": [
    "# 2. System deps: FFmpeg, cloudflared, + font subtitle (agar libass tidak fallback)\n",
    "!apt-get update -qq\n",
    "!apt-get install -y -qq ffmpeg fontconfig\n",
    "!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb\n",
    "!dpkg -i -q cloudflared-linux-amd64.deb\n",
    "\n",
    "import os\n",
    "FONT_DIR = '/usr/share/fonts/truetype/potongan'\n",
    "os.makedirs(FONT_DIR, exist_ok=True)\n",
    "FONTS = {\n",
    "    'Anton': 'https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf',\n",
    "    'BebasNeue': 'https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf',\n",
    "    'Montserrat': 'https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf',\n",
    "    'Oswald': 'https://github.com/google/fonts/raw/main/ofl/oswald/Oswald%5Bwght%5D.ttf',\n",
    "    'Poppins': 'https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf',\n",
    "    'PermanentMarker': 'https://github.com/google/fonts/raw/main/ofl/permanentmarker/PermanentMarker-Regular.ttf',\n",
    "}\n",
    "for name, url in FONTS.items():\n",
    "    !wget -q -O \"{FONT_DIR}/{name}.ttf\" \"{url}\"\n",
    "!fc-cache -f > /dev/null 2>&1\n",
    "!fc-list | grep -i -E 'anton|bebas|montserrat|oswald|poppins|permanent' | head -10"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {"id": "step3_code"},
   "outputs": [],
   "source": [
    "# 3. Clone repo Potongan.id + install Python dependencies\n",
    "!rm -rf /content/potongan\n",
    "!git clone https://github.com/fransiskusch/potongan.git /content/potongan\n",
    "%cd /content/potongan\n",
    "!pip install -q -r backend/requirements.txt uvicorn requests"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {"id": "step4_code"},
   "outputs": [],
   "source": [
    "# 4. Verifikasi GPU T4 (stop dengan pesan jelas bila bukan T4)\n",
    "import torch\n",
    "assert torch.cuda.is_available(), 'GPU TIDAK TERSEDIA. Runtime > Change runtime type > T4 GPU, lalu Run All lagi.'\n",
    "gpu_name = torch.cuda.get_device_name(0)\n",
    "print(f'GPU: {gpu_name}')\n",
    "if 'T4' not in gpu_name:\n",
    "    print(f'PERINGATAN: GPU {gpu_name} bukan T4 — performa mungkin berbeda, disarankan T4.')"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {"id": "step5_code"},
   "outputs": [],
   "source": [
    "# 5. Bersihkan file sisa sesi sebelumnya (opsional, aman dijalankan)\n",
    "import shutil, time, os\n",
    "for d in ['/content/projects', '/content/uploads']:\n",
    "    if os.path.isdir(d):\n",
    "        shutil.rmtree(d, ignore_errors=True)\n",
    "        print(f'Cleaned: {d}')\n",
    "print('Local disk siap.')"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {"cellView": "form", "id": "step6_code"},
   "outputs": [],
   "source": [
    "#@title 6. Jalankan Backend Potongan.id\n",
    "CLOUDFLARE_TUNNEL_TOKEN = \"\" #@param {type:\"string\"}\n",
    "API_SECRET_TOKEN = \"\" #@param {type:\"string\"}\n",
    "ALLOWED_ORIGINS = \"https://clip.fransiskus.my.id\" #@param {type:\"string\"}\n",
    "\n",
    "import os\n",
    "os.environ['AUTO_CLIPPER_ALLOWED_ORIGINS'] = ALLOWED_ORIGINS\n",
    "\n",
    "!python -m backend.colab_api --cloudflare-token \"$CLOUDFLARE_TUNNEL_TOKEN\" --api-token \"$API_SECRET_TOKEN\""
   ]
  }
 ],
 "metadata": {
  "accelerator": "GPU",
  "colab": {"provenance": []},
  "kernelspec": {"display_name": "Python 3", "name": "python3"},
  "language_info": {"name": "python"}
 },
 "nbformat": 4,
 "nbformat_minor": 0
}
```

- [ ] **Step 2: Validasi JSON notebook**

Run: `python -c "import json; json.load(open('Auto_Clipper_Colab.ipynb', encoding='utf-8')); print('valid ipynb')"`
Expected: `valid ipynb`

- [ ] **Step 3: Commit**

```bash
git add Auto_Clipper_Colab.ipynb
git commit -m "feat: rebuild Colab notebook for Potongan.id — T4 assert, font install, new repo URL, allowed origins form"
```

---

### Task 8: README — tulis ulang Opsi 5 + update docs arsitektur

**Files:**
- Modify: `README.md` (Opsi 5, baris ±122-132)
- Modify: `docs/cloud-architecture-plan.md` (domain, baris 6-7, 34-37, 397, 406-407, 448, 463)

**Interfaces:** Tidak ada — dokumentasi saja.

- [ ] **Step 1: Tulis ulang bagian Opsi 5 di README.md**

Ganti seluruh bagian `### Opsi 5: ...` (baris 122-132) dengan:

```markdown
### Opsi 5: Menjalankan Backend di Google Colab (Gratis GPU T4) — Potongan.id Cloud

Jalankan mesin render di **Google Colab T4** dan akses UI web **Potongan.id** dari browser mana saja (termasuk HP).

1. Buka file **[`Auto_Clipper_Colab.ipynb`](Auto_Clipper_Colab.ipynb)** di Google Colab.
2. Pastikan **Runtime > Change runtime type > T4 GPU** (notebook akan memverifikasi dan berhenti dengan pesan jelas bila bukan T4).
3. Jalankan semua sel berurutan: mount Drive → install FFmpeg + cloudflared + font subtitle → clone repo → verifikasi GPU → jalankan backend.
4. Di sel terakhir, isi **Cloudflare Tunnel Token** (dari Cloudflare Zero Trust → Tunnels, hostname `be-clipper.fransiskus.my.id` → `http://localhost:8000`), **API Secret Token** Anda, dan **Allowed Origins** (default `https://clip.fransiskus.my.id`).
5. Seluruh proses berat (download YouTube, transkripsi Whisper GPU, render FFmpeg) berjalan di disk lokal Colab yang cepat; **hasil klip + riwayat otomatis tersimpan di Google Drive** (`MyDrive/AutoClipperData`).
6. Buka **Potongan.id** (UI di Vercel: `clip.fransiskus.my.id`), masukkan API Secret Token Anda, dan mulai clipping.
7. Upload video lokal langsung dari browser, pilih file dari Google Drive, atau tempel link YouTube/TikTok/Instagram/X.

> Catatan: backend Colab aktif selama sesi notebook hidup (±12 jam). Semua hasil dan riwayat aman di Drive — nyalakan ulang notebook kapan pun tanpa kehilangan data.
```

- [ ] **Step 2: Update domain di docs/cloud-architecture-plan.md**

Ganti semua kemunculan (gunakan find & replace):
- `clipper.dhims.web.id` → `clip.fransiskus.my.id`
- `be-clipper.dhims.web.id` → `be-clipper.fransiskus.my.id`
- `Domain: dhims.web.id` → `Domain: fransiskus.my.id`
- Tambahkan catatan di bawah judul utama: `> **Superseded:** Desain operasional terbaru ada di docs/superpowers/specs/2025-11-15-colab-t4-drive-vercel-face-tracking-design.md (Potongan.id Cloud v2).`

- [ ] **Step 3: Verifikasi tidak ada domain lama yang tersisa**

Run: `rg -n "dhims\.web\.id" README.md docs/cloud-architecture-plan.md || echo "bersih"`
Expected: hanya `docs/superpowers/specs/` (sejarah, biarkan) — README & cloud-architecture-plan bersih. (Jika `rg` tidak tersedia: `grep -rn "dhims.web.id" README.md docs/cloud-architecture-plan.md`.)

- [ ] **Step 4: Commit**

```bash
git add README.md docs/cloud-architecture-plan.md
git commit -m "docs: rewrite Colab option for Potongan.id cloud with new fransiskus.my.id domains"
```

---

### Task 9: Verifikasi akhir Fase 1 — full test suite + smoke test manual

**Files:** Tidak ada perubahan file (verifikasi).

- [ ] **Step 1: Jalankan seluruh test suite backend**

Run: `python -m pytest backend/tests/ -v`
Expected: semua PASS — tidak ada regresi desktop (test lama tetap hijau).

- [ ] **Step 2: Smoke test cloud mode lokal (simulasi Colab di laptop)**

```bash
# Windows PowerShell (jalankan dari root repo):
$env:AUTO_CLIPPER_CLOUD_MODE="1"
$env:AUTO_CLIPPER_LOCAL_WORKDIR="$PWD\.smoke\projects"
$env:AUTO_CLIPPER_WORKSPACE="$PWD\.smoke\drive"
$env:AUTO_CLIPPER_DEV_TOKEN="dev-token"
uvicorn backend.main:app --port 8010
```

Lalu cek dengan curl/PowerShell:
1. `GET http://localhost:8010/health` → `{"status":"ok"}`
2. `POST http://localhost:8010/upload` dengan file kecil → respons `local:` URL harus di bawah `.smoke\projects`, BUKAN `.smoke\drive`
3. (Opsional) jalankan job manual kecil → pastikan folder `projects/<judul>/clips` muncul di `.smoke\drive` setelah job DONE, dan path di history menunjuk `.smoke\drive`

Bersihkan: hapus folder `.smoke` dan unset env var.

- [ ] **Step 3: Push ke repo baru**

```bash
git push origin main
```

Expected: semua commit Fase 1 ter-push ke `git@github.com:fransiskusch/potongan.git`.

---

## Catatan untuk Fase-Fase Berikutnya (di plan terpisah)

- **Fase 2** — chunked upload (`/upload/init|chunk|complete|status`) + tab Upload di StepInput.
- **Fase 3** — `backend/face_tracker.py` MediaPipe + Dominant Face Lock + One-Euro filter.
- **Fase 4** — UI/UX polish + mobile-first + rebrand "Potongan.id" di web UI.
- **Fase 5** — deploy Vercel (`web/`, `VITE_API_URL=https://be-clipper.fransiskus.my.id`, custom domain `clip.fransiskus.my.id`) + verifikasi end-to-end.
