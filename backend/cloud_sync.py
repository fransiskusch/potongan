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


def sync_source_to_persistent(local_project_dir: str) -> str:
    """Salin source/source_video.mp4 ke Drive. No-op di non-cloud."""
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
