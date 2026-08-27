from backend.video_utils import download_youtube_video
from backend.video_utils import humanize_download_error, resolve_cookie_file
from unittest.mock import patch, MagicMock

@patch('backend.video_utils.yt_dlp.YoutubeDL')
def test_download_youtube_video(mock_ytdl, tmp_path):
    # Mock the YoutubeDL context manager and download method
    mock_instance = MagicMock()
    mock_ytdl.return_value.__enter__.return_value = mock_instance
    
    url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ" 
    output_path = tmp_path / "video.mp4"
    
    # Create a dummy file to simulate successful download
    output_path.write_text("dummy video content")
    
    result_path = download_youtube_video(url, str(output_path))
    
    # Verify YoutubeDL was called with correct URL
    mock_instance.download.assert_called_once_with([url])
    assert result_path.exists()


def test_quality_to_format_caps_height():
    from backend.video_utils import quality_to_format
    assert "height<=2160" in quality_to_format("2160p")
    assert "height<=1440" in quality_to_format("1440p")
    assert "height<=1080" in quality_to_format("1080p")
    assert "height<=720" in quality_to_format("720p")
    assert "height<=480" in quality_to_format("480p")
    # best (and unknown) => no height cap
    assert "height<=" not in quality_to_format("best")
    assert "height<=" not in quality_to_format("weird")


def test_humanize_download_error_bot_message():
    msg = humanize_download_error(Exception("Sign in to confirm you're not a bot"))
    assert "cookies.txt" in msg.lower()
    assert "bot" in msg.lower()


def test_humanize_download_error_unknown_preserves_text():
    msg = humanize_download_error(Exception("some obscure detail abc"))
    assert msg == "some obscure detail abc"


def test_resolve_cookie_file_finds_existing(tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    found = resolve_cookie_file([str(tmp_path / "missing.txt"), str(f)])
    assert found == str(f)


def test_resolve_cookie_file_none_when_absent(tmp_path):
    assert resolve_cookie_file([str(tmp_path / "missing.txt")]) is None


@patch('backend.video_utils.yt_dlp.YoutubeDL')
def test_download_youtube_video_uses_cookie_file(mock_ytdl, tmp_path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n")
    mock_instance = MagicMock()
    mock_ytdl.return_value.__enter__.return_value = mock_instance
    out = tmp_path / "video.mp4"
    out.write_text("dummy")
    with patch("backend.video_utils.default_cookie_candidates", return_value=[str(cookie)]):
        download_youtube_video("https://www.youtube.com/watch?v=abc", str(out))
    args, kwargs = mock_ytdl.call_args
    opts = kwargs.get("opts") if kwargs else None
    if opts is None and args:
        opts = args[0]
    assert opts["cookiefile"] == str(cookie)
    assert "cookiesfrombrowser" not in opts


@patch('backend.video_utils.yt_dlp.YoutubeDL')
def test_probe_formats_returns_sorted_unique_heights(mock_ytdl):
    from backend.video_utils import probe_formats
    inst = MagicMock()
    mock_ytdl.return_value.__enter__.return_value = inst
    inst.extract_info.return_value = {
        "formats": [
            {"height": 720}, {"height": 1080}, {"height": 1080},
            {"height": None}, {"height": 480}, {}, {"height": 2160},
        ]
    }
    heights = probe_formats("https://youtu.be/x")
    assert heights == [2160, 1080, 720, 480]
    _, kwargs = inst.extract_info.call_args
    assert kwargs.get("download") is False
