import os
from unittest.mock import patch

import backend.jobs as jobs


def test_project_workspace_local_when_cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "content" / "projects"))
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))

    ws = jobs.get_project_workspace("Judul Keren", "", "job-1")
    # sanitize_title keeps spaces: "Judul Keren" -> "Judul Keren"
    assert ws["project_dir"] == os.path.join(str(tmp_path / "content" / "projects"), "Judul Keren")
    assert os.path.isdir(ws["clips_dir"])
    assert ws["safe_title"] == "Judul Keren"


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


def test_finalize_syncs_source_when_flag_on(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
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
    from backend.db import get_history, init_db
    init_db()
    jobs._finalize_job(job_id, "DONE", {"title": "Judul"})
    assert (tmp_path / "drive" / "projects" / "Judul" / "source" / "source_video.mp4").exists()
    history = get_history(job_id)
    assert history["metadata"]["source_video"] == str(tmp_path / "drive" / "projects" / "Judul" / "source" / "source_video.mp4")
    jobs.active_jobs.pop(job_id, None)


def test_finalize_skips_source_when_flag_off(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
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
    jobs.active_jobs.pop(job_id, None)


def test_finalize_skips_source_for_local_url(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
    local_proj = tmp_path / "local" / "Judul"
    (local_proj / "source").mkdir(parents=True)
    (local_proj / "source" / "source_video.mp4").write_bytes(b"x")
    job_id = "src-sync-local"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "local:/tmp/upload.mp4", "title": "Judul", "status": "DONE",
        "clips": [], "failed": 0, "error": None, "mode": "manual",
        "save_source_to_drive": True,
        "source_path": str(local_proj / "source" / "source_video.mp4"),
    }
    with patch("backend.db.save_history"):
        jobs._finalize_job(job_id, "DONE", {"title": "Judul"})
    assert not (tmp_path / "drive" / "projects" / "Judul" / "source" / "source_video.mp4").exists()
    jobs.active_jobs.pop(job_id, None)


def test_finalize_keeps_source_path_when_source_sync_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
    local_proj = tmp_path / "local" / "Judul"
    source = local_proj / "source" / "source_video.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    job_id = "src-sync-fail"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "https://youtube.com/x", "title": "Judul", "status": "DONE",
        "clips": [], "failed": 0, "error": None, "mode": "manual",
        "save_source_to_drive": True, "source_path": str(source),
    }
    metadata = {"title": "Judul", "source_video": str(source)}
    with patch("backend.db.save_history"), patch("backend.cloud_sync.sync_source_to_persistent", return_value=""):
        jobs._finalize_job(job_id, "DONE", metadata)
    assert metadata["source_video"] == str(source)
    jobs.active_jobs.pop(job_id, None)


def test_finalize_persists_local_source_path_for_history_reload(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
    local_proj = tmp_path / "local" / "Judul"
    source = local_proj / "source" / "source_video.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    job_id = "src-history-local"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "local:/tmp/upload.mp4", "title": "Judul", "status": "DONE",
        "clips": [], "failed": 0, "error": None, "mode": "manual",
        "save_source_to_drive": True, "source_path": str(source),
    }
    from backend.db import init_db
    init_db()
    with patch("backend.notifier.notify_job_finished"):
        jobs._finalize_job(job_id, "DONE", {"title": "Judul"})
    from backend.db import get_history
    history = get_history(job_id)
    assert history["metadata"]["source_video"] == str(source)
    assert not (tmp_path / "drive" / "projects" / "Judul" / "source" / "source_video.mp4").exists()
    jobs.active_jobs.pop(job_id, None)


def test_finalize_preserves_drive_picker_source_path(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
    drive_source = tmp_path / "drive" / "picked" / "source_video.mp4"
    drive_source.parent.mkdir(parents=True)
    drive_source.write_bytes(b"x")
    job_id = "src-history-picker"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "local:/tmp/upload.mp4", "title": "Judul", "status": "DONE",
        "clips": [], "failed": 0, "error": None, "mode": "manual",
        "save_source_to_drive": True, "source_path": str(drive_source),
    }
    from backend.db import get_history, init_db
    init_db()
    jobs._finalize_job(job_id, "DONE", {"title": "Judul", "source_video": str(drive_source)})
    assert get_history(job_id)["metadata"]["source_video"] == str(drive_source)
    jobs.active_jobs.pop(job_id, None)


def test_finalize_warns_notifier_when_requested_source_copy_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "local"))
    source = tmp_path / "local" / "Judul" / "source" / "source_video.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    job_id = "src-warning-1"
    jobs.active_jobs[job_id] = {
        "id": job_id, "url": "https://youtube.com/x", "title": "Judul", "status": "DONE",
        "clips": [], "failed": 0, "error": None, "mode": "manual",
        "save_source_to_drive": True, "source_path": str(source),
    }
    with patch("backend.cloud_sync.sync_source_to_persistent", return_value=""), \
         patch("backend.notifier.notify_job_finished") as notify:
        jobs._finalize_job(job_id, "DONE", {"title": "Judul"})
    assert jobs.active_jobs[job_id]["status"] == "DONE"
    assert notify.call_args.args[3]["warning"] == "source video tidak tersimpan ke Drive"
    jobs.active_jobs.pop(job_id, None)
