import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_sample_face_trajectory_returns_identity_format(monkeypatch):
    monkeypatch.setattr("backend.face_tracker._mediapipe_available", lambda: False)
    monkeypatch.setattr(
        "backend.face_tracker.sample_face_trajectory_haar",
        lambda *a, **k: [(0.0, 0.5), (0.25, 0.5)],
    )
    from backend.face_tracker import sample_face_trajectory

    traj = sample_face_trajectory("dummy.mp4", 0.0, 0.5, interval=0.25)
    assert traj == [(0.0, 0.5), (0.25, 0.5)]


def test_one_euro_filter_static_is_flat():
    from backend.face_tracker import _OneEuroFilter

    f = _OneEuroFilter(min_cutoff=1.0, beta=0.0)
    out = [f(t, 0.5) for t in [0.0, 0.1, 0.2, 0.3]]
    assert all(abs(x - 0.5) < 1e-9 for x in out)


def test_one_euro_filter_responds_to_jump():
    from backend.face_tracker import _OneEuroFilter

    f = _OneEuroFilter(min_cutoff=1.0, beta=0.0)
    f(0.0, 0.5)
    f(0.1, 0.5)
    out = f(0.2, 0.9)
    assert out > 0.5


def test_dominant_face_lock_holds_when_missing():
    from backend.face_tracker import _DominantFaceLock

    lock = _DominantFaceLock()
    lock.update(0.0, [(0.5, 0.5, 0.1, 0.1)])
    x = lock.update(1.0, [])
    assert x == 0.5


def test_crop_utils_sample_wrapper_uses_face_tracker(monkeypatch):
    from backend import crop_utils

    monkeypatch.setattr("backend.face_tracker._mediapipe_available", lambda: True)
    with patch("backend.face_tracker.sample_face_trajectory", return_value=[(0.0, 0.6)]) as tracked:
        result = crop_utils.sample_face_trajectory("clip.mp4", 0.0, 1.0, interval=0.25)
    assert result == [(0.0, 0.6)]
    tracked.assert_called_once_with("clip.mp4", 0.0, 1.0, interval=0.25, should_cancel=None)


def test_crop_utils_sample_wrapper_uses_private_haar_when_mediapipe_missing(monkeypatch):
    from backend import crop_utils

    monkeypatch.setattr("backend.face_tracker._mediapipe_available", lambda: False)
    with patch("backend.face_tracker.sample_face_trajectory_haar", return_value=[(0.0, 0.4)]) as haar:
        result = crop_utils.sample_face_trajectory("clip.mp4", 0.0, 1.0)
    assert result == [(0.0, 0.4)]
    haar.assert_called_once_with("clip.mp4", 0.0, 1.0, interval=0.5, should_cancel=None)


def test_crop_utils_layout_wrapper_uses_private_haar_without_recursion(monkeypatch):
    from backend import crop_utils

    monkeypatch.setattr("backend.face_tracker._mediapipe_available", lambda: False)
    expected = {"mode": "standard", "face_box": None, "face_area_ratio": 0.0, "face_center": (0.5, 0.5)}
    with patch("backend.face_tracker._detect_video_layout_haar", return_value=expected) as haar:
        result = crop_utils.detect_video_layout("clip.mp4", samples=4)
    assert result == expected
    haar.assert_called_once_with("clip.mp4", start_time=None, end_time=None, samples=4, should_cancel=None)


def test_sample_mediapipe_failure_releases_capture_and_detector(monkeypatch):
    import backend.face_tracker as tracker

    cap = MagicMock(isOpened=lambda: True)
    cap.get.side_effect = lambda prop: 640 if prop == 3 else 360
    cap.read.return_value = (True, object())
    detector = MagicMock()
    detector.process.side_effect = RuntimeError("process failed")
    cv2 = SimpleNamespace(
        VideoCapture=MagicMock(return_value=cap),
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        CAP_PROP_POS_MSEC=5,
        cvtColor=MagicMock(return_value=object()),
        COLOR_BGR2RGB=6,
    )
    monkeypatch.setattr(tracker, "_mediapipe_available", lambda: True)
    monkeypatch.setattr(tracker, "_detector", lambda: detector)
    with patch.dict(sys.modules, {"cv2": cv2}), patch.object(
        tracker, "sample_face_trajectory_haar", return_value=[(0.0, 0.5)]
    ) as haar:
        result = tracker.sample_face_trajectory("clip.mp4", 0.0, 1.0)
    assert result == [(0.0, 0.5)]
    haar.assert_called_once()
    cap.release.assert_called_once()
    detector.close.assert_called_once()


def test_layout_mediapipe_failure_releases_capture_and_detector(monkeypatch):
    import backend.face_tracker as tracker

    cap = MagicMock(isOpened=lambda: True)
    cap.get.side_effect = lambda prop: 25.0 if prop == 5 else 25
    cap.read.return_value = (True, object())
    detector = MagicMock()
    detector.process.side_effect = RuntimeError("process failed")
    cv2 = SimpleNamespace(
        VideoCapture=MagicMock(return_value=cap),
        CAP_PROP_FPS=5,
        CAP_PROP_FRAME_COUNT=7,
        CAP_PROP_POS_MSEC=8,
        cvtColor=MagicMock(return_value=object()),
        COLOR_BGR2RGB=9,
    )
    monkeypatch.setattr(tracker, "_mediapipe_available", lambda: True)
    monkeypatch.setattr(tracker, "_detector", lambda: detector)
    expected = {"mode": "standard", "face_box": None, "face_area_ratio": 0.0, "face_center": (0.5, 0.5)}
    with patch.dict(sys.modules, {"cv2": cv2}), patch.object(
        tracker, "_detect_video_layout_haar", return_value=expected
    ) as haar:
        result = tracker.detect_video_layout("clip.mp4", samples=2)
    assert result == expected
    haar.assert_called_once()
    cap.release.assert_called_once()
    detector.close.assert_called_once()
