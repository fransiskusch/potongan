import yt_dlp
import contextlib
import io
import subprocess
import os
import sys
import time
import shutil
from pathlib import Path
from backend.logger import log_error


def resolve_cookie_file(candidates: list) -> str | None:
    """Return the first existing cookies file from ``candidates``.

    Searches common project locations for a ``cookies.txt`` so users can drop
    a YouTube cookies export next to the repo (Colab: ``/content/potongan``,
    desktop: project root / ``bin``) without touching code.
    """
    for raw in candidates:
        if not raw:
            continue
        p = os.path.abspath(os.path.expanduser(str(raw)))
        if os.path.isfile(p):
            return p
    return None


def default_cookie_candidates() -> list:
    """Default search paths for a cookies file, most specific first."""
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        project_root / "cookies.txt",
        project_root / "bin" / "cookies.txt",
        Path.home() / ".config" / "auto-clipper" / "cookies.txt",
    ]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.extend([exe_dir / "cookies.txt", exe_dir / "bin" / "cookies.txt"])
    return [str(c) for c in candidates]


def get_ffmpeg_path() -> str | None:
    """Finds the absolute path to the ffmpeg executable."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        project_root / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
        project_root / "src-tauri" / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
    ]
    if getattr(sys, 'frozen', False):
        bin_dir = Path(sys.executable).parent
        candidates.extend([
            bin_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
            bin_dir / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
            bin_dir.parent / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
            bin_dir.parent / "Resources" / "bin" / "ffmpeg",
        ])
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# Ensure ffmpeg folder is prepended to system PATH
_ffmpeg_exec = get_ffmpeg_path()
if _ffmpeg_exec:
    _ffmpeg_dir = os.path.dirname(_ffmpeg_exec)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


class _SilentLogger:
    """Route all yt-dlp output away from stdout/stderr.

    When the backend runs as an Electron child process on Windows, its stderr
    handle can be invalid, so yt-dlp crashes with ``OSError: [Errno 22]`` the
    moment it tries to flush a warning. Giving yt-dlp a logger makes it send
    messages here instead of ever touching the broken stream.
    """

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


class DownloadCancelledError(Exception):
    pass


def humanize_download_error(exc: Exception) -> str:
    """Translate common yt-dlp/network errors into user-friendly messages.

    Raw yt-dlp errors (e.g. ``Sign in to confirm you're not a bot``) are
    technical and confusing for end users. This maps the frequent cases to
    clear Indonesian/English guidance while preserving unknown details.
    """
    text = str(exc) or exc.__class__.__name__
    lower = text.lower()

    if "sign in to confirm" in lower or "not a bot" in lower or "bot" in lower and "confirm" in lower:
        return (
            "YouTube memblokir akses dari server ini (\"Sign in to confirm you're not a bot\"). "
            "Solusi: (1) taruh file cookies.txt dari browser ke folder project, atau "
            "(2) gunakan upload file / Google Drive picker sebagai ganti link YouTube."
        )
    if "video unavailable" in lower or "private video" in lower or "removed" in lower:
        return "Video tidak tersedia (private, dihapus, atau dibatasi wilayah). Cek URL-nya."
    if "copyright" in lower or "strike" in lower:
        return "Video tidak bisa diunduh karena masalah hak cipta."
    if "age" in lower or "18+" in lower or "age-restricted" in lower:
        return "Video dibatasi umur (18+) dan tidak bisa diunduh tanpa login."
    if "members-only" in lower or "members only" in lower:
        return "Video khusus member dan tidak bisa diunduh."
    if "playlist" in lower and "single video" in lower:
        return "Link tampaknya playlist — kirim URL video tunggal."
    if "timed out" in lower or "timeout" in lower or "connection" in lower and "error" in lower:
        return "Koneksi ke server video gagal/timeout. Coba lagi beberapa saat."
    if "unsupported url" in lower or "not a valid url" in lower:
        return "URL tidak didukung. Gunakan link YouTube/TikTok/Instagram/X yang valid."
    if "sign in" in lower or "authentication" in lower or "login" in lower:
        return "Platform meminta login. Tambahkan cookies.txt agar unduhan diizinkan."
    if "403" in lower or "forbidden" in lower:
        return "Akses ditolak (403). Server/platform memblokir unduhan — coba cookies.txt atau sumber lain."
    if "429" in lower or "too many requests" in lower:
        return "Terlalu banyak permintaan (429). Tunggu beberapa menit lalu coba lagi."
    return text

def quality_to_format(quality: str) -> str:
    """yt-dlp format selector for a requested quality label.

    Heights use '<=' so yt-dlp gracefully falls back to the best resolution at
    or below the target when the exact one isn't available.
    """
    caps = {"2160p": 2160, "1440p": 1440, "1080p": 1080, "720p": 720, "480p": 480}
    h = caps.get(quality)
    if h:
        return f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best"
    return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'


def probe_formats(url: str) -> list:
    """Available video heights for a URL, descending & unique, via yt-dlp."""
    base_ydl_opts = {
        'quiet': True, 'no_warnings': True, 'skip_download': True,
        'logger': _SilentLogger(),
    }

    cookie_file = resolve_cookie_file(default_cookie_candidates())
    if cookie_file:
        base_ydl_opts['cookiefile'] = cookie_file

    browsers_to_try = ['chrome', 'edge', 'firefox', 'brave', 'opera', 'vivaldi', None]
    info = None
    last_error = None
    
    for browser in browsers_to_try:
        ydl_opts = dict(base_ydl_opts)
        if browser and not cookie_file:
            ydl_opts['cookiesfrombrowser'] = (browser,)
            
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            break
        except Exception as e:
            last_error = e

    if info is None and last_error:
        raise last_error

    formats = (info or {}).get("formats", []) if isinstance(info, dict) else []
    heights = {f.get("height") for f in formats if isinstance(f, dict) and f.get("height")}
    return sorted(heights, reverse=True)


def download_youtube_video(url: str, output_path: str, quality: str = "best", is_cancelled: callable = None) -> Path:
    format_str = quality_to_format(quality)

    base_ydl_opts = {
        'format': format_str,
        'outtmpl': output_path,
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'updatetime': False,
        'logger': _SilentLogger(),
    }
    ffmpeg_loc = get_ffmpeg_path()
    if ffmpeg_loc:
        base_ydl_opts['ffmpeg_location'] = ffmpeg_loc
    
    if is_cancelled:
        def hook(d):
            if is_cancelled():
                raise DownloadCancelledError("Download cancelled by user")
        base_ydl_opts['progress_hooks'] = [hook]

    # yt-dlp snapshots sys.stdout/stderr at construction and writes to them
    # directly for some messages (e.g. deprecation notices), bypassing the
    # logger. On a broken Windows child-process stream that flush raises
    # OSError [Errno 22], so we redirect both streams to an in-memory sink for
    # the whole call.
    max_retries = 3
    browsers_to_try = ['chrome', 'edge', 'firefox', 'brave', 'opera', 'vivaldi', None]

    cookie_file = resolve_cookie_file(default_cookie_candidates())
    if cookie_file:
        base_ydl_opts['cookiefile'] = cookie_file

    success = False
    last_error = None
    
    for browser in browsers_to_try:
        ydl_opts = dict(base_ydl_opts)
        if browser and not cookie_file:
            ydl_opts['cookiesfrombrowser'] = (browser,)
            
        for attempt in range(max_retries):
            try:
                sink = io.StringIO()
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                success = True
                break
            except Exception as e:
                last_error = e
                # If we were cancelled during download, don't retry and don't try other browsers
                if is_cancelled and is_cancelled():
                    raise DownloadCancelledError("Download cancelled by user")
                
                # If the error is about unsupported browser, no need to retry this browser
                err_str = str(e).lower()
                if "unsupported browser" in err_str or "unsupported platform" in err_str or "failed to load cookies" in err_str:
                    break # Break retry loop, move to next browser
                    
                # Wait a bit before retrying, especially useful for 403 blocks
                if attempt < max_retries - 1:
                    wait_secs = 2 ** attempt
                    end_t = time.time() + wait_secs
                    while time.time() < end_t:
                        if is_cancelled and is_cancelled():
                            raise DownloadCancelledError("Download cancelled by user")
                        time.sleep(min(0.2, max(0.0, end_t - time.time())))
                    
        if success:
            break
            
    if not success and last_error:
        raise last_error

    return Path(output_path)



def extract_audio(video_path: str, audio_path: str, register_proc: callable = None) -> str:
    """Extract a compact mono 16kHz audio track for speech-to-text.

    Whisper only accepts audio and caps uploads at 25MB, so sending the raw
    (often multi-GB) video fails on real long-form content. A mono 16kHz MP3
    stays tiny even for hour-long videos while keeping speech intelligible.
    """
    if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
        return audio_path

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "64k",
        audio_path,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if register_proc:
        register_proc(proc)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, stderr)
    return audio_path

def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffmpeg (bundled), parsing stderr."""
    import re
    cmd = ["ffmpeg", "-i", video_path]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)", res.stderr)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception as e:
        log_error("video_utils.get_video_duration", e)
    return 0.0
