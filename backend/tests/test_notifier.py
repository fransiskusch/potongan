from unittest.mock import patch

from backend.notifier import notify_job_finished, send_telegram_message


def _env(monkeypatch, bot="bot123", chat="42"):
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_BOT_TOKEN", bot)
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_CHAT_ID", chat)


def test_send_telegram_message_success(monkeypatch):
    with patch("backend.notifier.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        ok = send_telegram_message("hello", "bot123", "42")
        assert ok is True
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.telegram.org/botbot123/sendMessage"
        assert kwargs["json"] == {"chat_id": "42", "text": "hello"}
        assert kwargs["timeout"] == 10


def test_send_telegram_message_network_error_returns_false(monkeypatch):
    with patch("backend.notifier.requests.post", side_effect=Exception("boom")):
        ok = send_telegram_message("hello", "bot123", "42")
        assert ok is False


def test_send_telegram_message_empty_token_no_call(monkeypatch):
    with patch("backend.notifier.requests.post") as mock_post:
        ok = send_telegram_message("hello", "", "42")
        assert ok is False
        mock_post.assert_not_called()


def test_notify_job_finished_skips_when_no_env(monkeypatch):
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("AUTO_CLIPPER_TELEGRAM_CHAT_ID", "")
    with patch("backend.notifier.send_telegram_message") as mock_send, \
         patch("backend.notifier.threading.Thread", side_effect=lambda target, daemon: type("T", (), {"start": target})()):
        notify_job_finished("job-1", "DONE", {"title": "Judul"}, {"title": "Judul"})
        mock_send.assert_not_called()


def test_notify_job_finished_done_sends_message(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("AUTO_CLIPPER_PUBLIC_BASE_URL", "https://be.example.com")
    job = {"title": "Judul Proyek", "clips": [{"path": "/tmp/a_clip_1.mp4", "description": "d1"}], "failed": 0}
    metadata = {"title": "Judul Proyek", "duration_seconds": 720}
    with patch("backend.notifier.send_telegram_message") as mock_send, \
         patch("backend.notifier.threading.Thread", side_effect=lambda target, daemon: type("T", (), {"start": target})()):
        notify_job_finished("job-1", "DONE", job, metadata)
        assert mock_send.called
        text = mock_send.call_args.args[0]
        assert "Judul Proyek" in text
        assert "DONE" in text
        assert "1 berhasil" in text


def test_notify_job_finished_includes_source_copy_warning(monkeypatch):
    _env(monkeypatch)
    with patch("backend.notifier.send_telegram_message") as mock_send, \
         patch("backend.notifier.threading.Thread", side_effect=lambda target, daemon: type("T", (), {"start": target})()):
        notify_job_finished(
            "job-warning", "DONE", {"title": "Judul", "clips": [], "failed": 0},
            {"title": "Judul", "warning": "source video tidak tersimpan ke Drive"},
        )
        assert "source video tidak tersimpan ke Drive" in mock_send.call_args.args[0]


def test_notify_job_finished_error_sends_message(monkeypatch):
    _env(monkeypatch)
    job = {"title": "X", "clips": [], "failed": 0, "error": "gagal"}
    with patch("backend.notifier.send_telegram_message") as mock_send:
        notify_job_finished("job-2", "ERROR", job, {"title": "X"})
        assert mock_send.called
        assert "ERROR" in mock_send.call_args.args[0]


def test_notify_job_finished_ignores_unknown_status(monkeypatch):
    _env(monkeypatch)
    with patch("backend.notifier.send_telegram_message") as mock_send, \
         patch("backend.notifier.threading.Thread") as mock_thread:
        notify_job_finished("job-3", "RUNNING", {"title": "X"}, {"title": "X"})
        mock_send.assert_not_called()
        mock_thread.assert_not_called()


def test_notify_job_finished_truncates_oversized_message(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("AUTO_CLIPPER_PUBLIC_BASE_URL", "https://example.com/" + "b" * 2000)
    job = {
        "title": "Job " + "t" * 6000,
        "clips": [{"path": "/tmp/" + "clip" * 1000 + ".mp4"}],
        "failed": 0,
    }
    with patch("backend.notifier.send_telegram_message") as mock_send, \
         patch("backend.notifier.threading.Thread", side_effect=lambda target, daemon: type("T", (), {"start": target})()):
        notify_job_finished("job-4", "DONE", job, {"title": job["title"], "duration_seconds": 60})
        text = mock_send.call_args.args[0]
        assert len(text) <= 4096
        assert "Klip: 1 berhasil" in text
