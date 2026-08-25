import os
import io
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_upload_goes_to_local_workdir_in_cloud_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_CLIPPER_CLOUD_MODE", "1")
    monkeypatch.setenv("AUTO_CLIPPER_LOCAL_WORKDIR", str(tmp_path / "content" / "projects"))
    # workspace persisten (Drive) — untuk memastikan file TIDAK ke sini
    monkeypatch.setenv("AUTO_CLIPPER_WORKSPACE", str(tmp_path / "drive"))
    monkeypatch.setenv("AUTO_CLIPPER_WEB_TOKEN", "test-token-123")

    from backend.main import app
    client = TestClient(app)

    res = client.post(
        "/upload",
        files={"file": ("video.mp4", io.BytesIO(b"fake"), "video/mp4")},
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert res.status_code == 200
    url = res.json()["url"]
    assert url.startswith("local:")
    path = url.split("local:")[1]
    assert os.path.abspath(path).startswith(os.path.abspath(str(tmp_path / "content" / "projects")))
    assert not os.path.abspath(path).startswith(os.path.abspath(str(tmp_path / "drive")))
    assert os.path.exists(path)
