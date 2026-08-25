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
