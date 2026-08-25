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
    monkeypatch.setenv("AUTO_CLIPPER_WEB_TOKEN", "test-token")
    monkeypatch.setattr("backend.main._GDRIVE_BASE", str(root))
    from backend.main import app
    return TestClient(app)


def test_gdrive_search_finds_video_case_insensitive(monkeypatch, tmp_path):
    _make_tree(tmp_path)
    monkeypatch.setenv("AUTO_CLIPPER_WEB_TOKEN", "test-token")
    c = _client_cloud(monkeypatch, tmp_path)
    r = c.get("/gdrive-search", params={"q": "podcast"}, headers={"Authorization": "Bearer test-token"})
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
    r = c.get("/gdrive-search", params={"q": "zzznothing"}, headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_gdrive_search_not_cloud_mode(monkeypatch):
    monkeypatch.delenv("AUTO_CLIPPER_CLOUD_MODE", raising=False)
    monkeypatch.setenv("AUTO_CLIPPER_WEB_TOKEN", "test-token")
    from backend.main import app
    c = TestClient(app)
    r = c.get("/gdrive-search", params={"q": "x"}, headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    assert r.json().get("status") == "error"


def test_gdrive_search_caps_max_results_at_100(monkeypatch, tmp_path):
    _make_tree(tmp_path)
    c = _client_cloud(monkeypatch, tmp_path)
    r = c.get("/gdrive-search", params={"q": "podcast", "max_results": 101}, headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 422


def test_gdrive_browser_rejects_prefix_sibling(monkeypatch, tmp_path):
    base = tmp_path / "drive"
    base.mkdir()
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_WEB_TOKEN", "test-token")
    monkeypatch.setattr("backend.main._GDRIVE_BASE", str(base))
    from backend.main import app
    c = TestClient(app)
    sibling = str(tmp_path / "drive-escape")
    r = c.get("/gdrive-browser", params={"dir_path": sibling}, headers={"Authorization": "Bearer test-token"})
    assert r.json()["current_dir"] == os.path.abspath(str(base))
