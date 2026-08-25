import os
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
