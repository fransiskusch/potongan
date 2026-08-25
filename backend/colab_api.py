"""Entrypoint for running Auto Clipper backend in Google Colab or cloud environments.

Usage:
    python -m backend.colab_api [OPTIONS]

Example:
    python -m backend.colab_api --cloudflare-token <TOKEN> --api-token <SECRET>
"""

import argparse
import os
import signal
import subprocess
import sys
import time
import threading
from typing import List, Optional


DEFAULT_WORKSPACE = "/content/drive/MyDrive/AutoClipperData"
DEFAULT_LOCAL_WORKDIR = "/content/projects"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments with fallbacks to environment variables."""
    parser = argparse.ArgumentParser(
        description="Auto Clipper Cloud / Google Colab Backend Server"
    )

    env_cf_token = os.environ.get("CLOUDFLARE_TOKEN") or os.environ.get("CF_TUNNEL_TOKEN") or ""
    env_api_token = (
        os.environ.get("API_SECRET_TOKEN")
        or os.environ.get("AUTO_CLIPPER_DEV_TOKEN")
        or os.environ.get("AUTO_CLIPPER_WEB_TOKEN")
        or ""
    )
    env_workspace = os.environ.get("AUTO_CLIPPER_WORKSPACE") or DEFAULT_WORKSPACE
    env_host = os.environ.get("HOST") or DEFAULT_HOST
    env_port = int(os.environ.get("PORT") or DEFAULT_PORT)

    parser.add_argument(
        "--cloudflare-token",
        "--tunnel-token",
        dest="cloudflare_token",
        default=env_cf_token,
        help="Cloudflare tunnel token (default: env CLOUDFLARE_TOKEN / CF_TUNNEL_TOKEN)",
    )
    parser.add_argument(
        "--api-token",
        "--token",
        dest="api_token",
        default=env_api_token,
        help="API authentication secret token (default: env API_SECRET_TOKEN / AUTO_CLIPPER_DEV_TOKEN / AUTO_CLIPPER_WEB_TOKEN)",
    )
    parser.add_argument(
        "--workspace",
        default=env_workspace,
        help=f"Path to persistent project workspace (default: {DEFAULT_WORKSPACE} or env AUTO_CLIPPER_WORKSPACE)",
    )
    parser.add_argument(
        "--host",
        default=env_host,
        help=f"Host address to bind uvicorn server (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=env_port,
        help=f"Port to bind uvicorn server (default: {DEFAULT_PORT})",
    )
    env_local_workdir = os.environ.get("AUTO_CLIPPER_LOCAL_WORKDIR") or DEFAULT_LOCAL_WORKDIR
    parser.add_argument(
        "--local-workdir",
        dest="local_workdir",
        default=env_local_workdir,
        help=f"Fast local working directory for downloads/renders (default: {DEFAULT_LOCAL_WORKDIR})",
    )

    return parser.parse_args(args)


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


def verify_gpu(require_t4: bool = True) -> tuple:
    """Verify a CUDA GPU is available; warn (not crash) if it is not a T4."""
    try:
        import torch
    except Exception:
        return (False, "torch is not installed or importable")
    if torch is None:
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


def start_uvicorn(host: str, port: int) -> subprocess.Popen:
    """Spawn the FastAPI application via uvicorn subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    print(f"[Auto Clipper Colab] Starting Uvicorn API server on {host}:{port}...")
    return subprocess.Popen(cmd, env=os.environ.copy())


def start_cloudflared(token: str) -> Optional[subprocess.Popen]:
    """Spawn cloudflared tunnel subprocess if token is provided."""
    if not token or not token.strip():
        print("[Auto Clipper Colab] No Cloudflare tunnel token provided. Cloudflare Tunnel will not be started.")
        return None

    cmd = ["cloudflared", "tunnel", "run", "--token", token.strip()]
    print("[Auto Clipper Colab] Starting Cloudflare Tunnel...")
    try:
        return subprocess.Popen(cmd, env=os.environ.copy())
    except FileNotFoundError:
        print(
            "[Auto Clipper Colab] Warning: 'cloudflared' executable not found in PATH. "
            "Please ensure cloudflared is installed (e.g. 'pip install cloudflared' or apt package).",
            file=sys.stderr,
        )
        return None
    except Exception as e:
        print(f"[Auto Clipper Colab] Error starting cloudflared: {e}", file=sys.stderr)
        return None


def gpu_keep_alive() -> None:
    """Background thread to keep GPU utilization > 0% occasionally so Colab doesn't reclaim it."""
    try:
        import torch
        if not torch.cuda.is_available():
            print("[Auto Clipper Colab] GPU Keep-Alive skipped: CUDA is not available.", file=sys.stderr)
            return
        
        print("[Auto Clipper Colab] Starting GPU keep-alive thread to prevent Colab timeout...")
        # Allocate a persistent ~400MB tensor to keep GPU Memory Utilization > 0%
        persistent_tensor = torch.ones((10000, 10000), device="cuda")
        
        while True:
            # Perform a minor operation on the persistent tensor
            _ = persistent_tensor * 1.01
            time.sleep(15)  # Pulse every 15 seconds
    except ImportError:
        print("[Auto Clipper Colab] GPU Keep-Alive skipped: torch not installed.", file=sys.stderr)
    except Exception as e:
        print(f"[Auto Clipper Colab] GPU keep-alive stopped: {e}", file=sys.stderr)


def terminate_processes(processes: List[subprocess.Popen], timeout: float = 5.0) -> None:
    """Terminate and clean up child processes gracefully."""
    print("\n[Auto Clipper Colab] Shutting down subprocesses...")
    for proc in processes:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception as e:
                print(f"[Auto Clipper Colab] Error sending SIGTERM to PID {proc.pid}: {e}", file=sys.stderr)

    start_time = time.monotonic()
    for proc in processes:
        if proc and proc.poll() is None:
            remaining = max(0.1, timeout - (time.monotonic() - start_time))
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                print(f"[Auto Clipper Colab] Process {proc.pid} did not terminate within {timeout}s, killing...")
                try:
                    proc.kill()
                except Exception:
                    pass


def run_server(args: Optional[List[str]] = None) -> int:
    """Main execution loop for Colab entrypoint."""
    parsed = parse_args(args)

    setup_environment(parsed.workspace, parsed.api_token, local_workdir=parsed.local_workdir)

    ok_gpu, gpu_msg = verify_gpu()
    print(f"[Auto Clipper Colab] GPU check: {'OK' if ok_gpu else 'FAILED'} — {gpu_msg}")
    if not ok_gpu:
        print("[Auto Clipper Colab] ERROR: GPU tidak tersedia. Set Runtime > Change runtime type > T4 GPU, lalu jalankan ulang.", file=sys.stderr)
        return 1

    removed = cleanup_stale_uploads(os.path.join(parsed.local_workdir, "uploads"))
    if removed:
        print(f"[Auto Clipper Colab] Cleaned {removed} stale upload file(s).")

    running_procs: List[subprocess.Popen] = []
    shutdown_initiated = False

    def handle_signal(signum, frame):
        nonlocal shutdown_initiated
        if not shutdown_initiated:
            shutdown_initiated = True
            print(f"\n[Auto Clipper Colab] Received signal {signum}, initiating graceful shutdown...")
            terminate_processes(running_procs)
            sys.exit(0)

    try:
        signal.signal(signal.SIGINT, handle_signal)
    except Exception:
        pass

    try:
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handle_signal)
    except Exception:
        pass

    # Start GPU keep-alive thread
    keep_alive_thread = threading.Thread(target=gpu_keep_alive, daemon=True)
    keep_alive_thread.start()

    api_proc = start_uvicorn(parsed.host, parsed.port)
    running_procs.append(api_proc)

    cf_proc = start_cloudflared(parsed.cloudflare_token)
    if cf_proc:
        running_procs.append(cf_proc)

    print("[Auto Clipper Colab] Services started successfully. Press Ctrl+C to terminate.")

    exit_code = 0
    try:
        while True:
            # Check API server status
            if api_proc.poll() is not None:
                print(f"[Auto Clipper Colab] FastAPI uvicorn process exited with code {api_proc.returncode}")
                exit_code = api_proc.returncode
                break

            # Check Cloudflare tunnel status (if running)
            if cf_proc and cf_proc.poll() is not None:
                print(f"[Auto Clipper Colab] Cloudflare tunnel process exited with code {cf_proc.returncode}")
                exit_code = cf_proc.returncode
                break

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Auto Clipper Colab] KeyboardInterrupt received.")
    finally:
        terminate_processes(running_procs)

    return exit_code


if __name__ == "__main__":
    sys.exit(run_server())
