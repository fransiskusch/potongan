# Task 6 Report

Status: implemented on `feat/web-ai-drive`.

Changes:
- Added `backend/face_tracker.py` with optional lazy MediaPipe detection.
- Added `_OneEuroFilter`, `_DominantFaceLock`, and `_detector()`.
- Added dominant-face trajectory tracking, smoothing, cancellation, and fallback logging.
- Renamed legacy Haar implementations to `_sample_face_trajectory_haar` and `_detect_video_layout_haar`.
- Added lazy `crop_utils` wrappers preserving public signatures and preventing circular recursion.
- Added `backend/tests/test_face_tracker.py`.
- Kept `mediapipe` out of `backend/requirements.txt`.

Tests:
- `pytest backend/tests/test_face_tracker.py -v`: 7 passed.
- `pytest backend/tests/test_face_tracker.py backend/tests/test_crop_utils.py -v`: 23 passed, 8 failed before legacy assertions because installed `cv2` has no `CascadeClassifier` attribute. This is an environment/package failure, not caused by MediaPipe import or tracker recursion.
- `git diff --check`: passed.

Concerns:
- MediaPipe was not installed, so real MediaPipe frame processing was not exercised in this environment.
- Existing Haar tests need an OpenCV build exposing `cv2.CascadeClassifier` to run.
