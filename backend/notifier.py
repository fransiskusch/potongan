"""Best-effort Telegram notifications for finished jobs."""

import os
import threading
from urllib.parse import quote

import requests

from backend.logger import log_app, log_error

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LEN = 4096


def _bot_token() -> str:
    return os.environ.get("AUTO_CLIPPER_TELEGRAM_BOT_TOKEN", "").strip()


def _chat_id() -> str:
    return os.environ.get("AUTO_CLIPPER_TELEGRAM_CHAT_ID", "").strip()


def _public_base_url() -> str:
    return os.environ.get(
        "AUTO_CLIPPER_PUBLIC_BASE_URL", "https://be-clipper.fransiskus.my.id"
    ).strip()


def send_telegram_message(text: str, bot_token: str, chat_id: str) -> bool:
    if not bot_token or not chat_id or not text:
        return False
    try:
        response = requests.post(
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        return response.status_code == 200
    except Exception as error:
        log_error("notifier.send_telegram_message", error)
        return False


def notify_job_finished(job_id: str, status: str, job: dict, metadata: dict) -> None:
    if status not in {"DONE", "ERROR"}:
        return

    bot_token = _bot_token()
    chat_id = _chat_id()
    if not bot_token or not chat_id:
        return

    title = (metadata.get("title") or job.get("title") or "").strip() or "Untitled"
    base_url = _public_base_url().rstrip("/")
    is_done = status == "DONE"
    emoji = "\u274c" if status == "ERROR" else "\U0001f3ac"
    status_line = "DONE" if is_done else f"ERROR: {str(job.get('error') or '')[:200]}".rstrip(": ")
    clips = job.get("clips", []) or []
    failed = job.get("failed", 0)
    duration = metadata.get("duration_seconds", 0)
    duration_text = f"{int(duration // 60)} menit" if duration >= 60 else f"{int(duration)} detik"
    status_emoji = "\u2705" if is_done else emoji

    lines = [
        f"{emoji} Potongan.id — Job Selesai",
        f"\U0001f4cc Judul: {title}",
        f"{status_emoji} Status: {status_line}",
        f"\U0001f39e Klip: {len(clips)} berhasil, {failed} gagal",
        f"\u23f1 Durasi proses: {duration_text}",
        "",
    ]
    if metadata.get("warning"):
        lines.append(str(metadata["warning"]))
        lines.append("")
    if clips:
        lines.append("\U0001f4e5 Unduh klip:")
        for index, clip in enumerate(clips, start=1):
            name = os.path.basename(clip.get("path", "")) or f"clip_{index}"
            path = quote(str(clip.get("path", "")), safe="")
            lines.append(f"{index}. {name} — {base_url}/video?path={path}")
    lines.extend(["", "\u23f3 Link aktif selama backend Colab menyala."])

    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_LEN:
        title_line = lines[1]
        if len(title_line) > 500:
            title_line = title_line[:497] + "..."
        lines = [lines[0], title_line, lines[2], lines[3], lines[4], ""]
        if metadata.get("warning"):
            lines.extend([str(metadata["warning"]), ""])
        lines.append("\U0001f4e5 Unduh klip:")
        footer = "\n\u23f3 Link aktif selama backend Colab menyala."
        for index, clip in enumerate(clips, start=1):
            name = os.path.basename(clip.get("path", "")) or f"clip_{index}"
            path = quote(str(clip.get("path", "")), safe="")
            line = f"{index}. {name} — {base_url}/video?path={path}"
            if len("\n".join(lines + [line]) + footer) > MAX_MESSAGE_LEN:
                break
            lines.append(line)
        if len(lines) - 7 < len(clips):
            lines.append(f"…dan {len(clips) - (len(lines) - 7)} klip lainnya, buka web untuk melihat semua.")
        lines.append("\u23f3 Link aktif selama backend Colab menyala.")
        text = "\n".join(lines)
        if len(text) > MAX_MESSAGE_LEN:
            text = text[: MAX_MESSAGE_LEN - 3] + "..."

    def _send(*_args) -> None:
        try:
            sent = send_telegram_message(text, bot_token, chat_id)
            log_app(f"[notifier] job {job_id} status={status} sent={sent}")
        except Exception as error:
            log_error("notifier.notify_job_finished", error)

    threading.Thread(target=_send, daemon=True).start()
