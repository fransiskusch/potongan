"""Optional MediaPipe face tracker with dominant-face lock and Haar fallback."""
import math

from backend.crop_utils import to_seconds
from backend.logger import log_error


def _mediapipe_available() -> bool:
    try:
        import mediapipe  # noqa: F401
        return True
    except Exception:
        return False


def _detector():
    if not _mediapipe_available():
        return None
    import mediapipe as mp
    return mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.4)


class _OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    def _alpha(self, dt):
        tau = 1.0 / (2 * math.pi * self.min_cutoff)
        return 1.0 / (1.0 + tau / max(dt, 1e-6))

    def __call__(self, t, x):
        if self.x_prev is None:
            self.x_prev, self.t_prev = x, t
            return x
        dt = t - self.t_prev
        if dt <= 0:
            return self.x_prev
        dx = (x - self.x_prev) / dt
        alpha_d = self._alpha(dt)
        self.dx_prev += alpha_d * (dx - self.dx_prev)
        cutoff = self.min_cutoff + self.beta * abs(self.dx_prev)
        alpha = 1.0 / (1.0 + 1.0 / (2 * math.pi * cutoff) / dt)
        self.x_prev += alpha * (x - self.x_prev)
        self.t_prev = t
        return self.x_prev


class _DominantFaceLock:
    HOLD_SECONDS = 5.0
    RESCAN_SECONDS = 15.0

    def __init__(self):
        self.target = None
        self.last_seen = None
        self.anchor = None
        self.missing_since = None

    def update(self, t, faces):
        if not faces:
            if self.target is not None and self.missing_since is None:
                self.missing_since = t
            if self.missing_since is not None and t - self.missing_since > self.RESCAN_SECONDS:
                self.target = self.anchor = self.missing_since = None
            return self.target[0] if self.target is not None else None
        if self.target is None:
            cx, cy, _, _ = max(faces, key=lambda f: f[2] * f[3])
            self.target = self.anchor = (cx, cy)
        else:
            cx, cy, _, _ = min(faces, key=lambda f: abs(f[0] - self.target[0]) + abs(f[1] - self.target[1]))
            self.target = (cx, cy)
        self.last_seen, self.missing_since = t, None
        return self.target[0]


def sample_face_trajectory_haar(video_path, start_time, end_time, interval=0.5, should_cancel=None):
    from backend.crop_utils import _sample_face_trajectory_haar
    return _sample_face_trajectory_haar(video_path, start_time, end_time, interval=interval, should_cancel=should_cancel)


def sample_face_trajectory(video_path: str, start_time: float, end_time: float, interval: float = 0.25, should_cancel=None) -> list[tuple[float, float]]:
    if not _mediapipe_available():
        return sample_face_trajectory_haar(video_path, start_time, end_time, interval=interval, should_cancel=should_cancel)
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            return [(0.0, 0.5)]
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        half_window = (frame_h * 9 / 16) / frame_w / 2 if frame_w and frame_h else 0.28
        lo, hi = half_window, 1.0 - half_window
        duration = max(0.1, end_time - start_time)
        detector = _detector()
        lock, filt = _DominantFaceLock(), _OneEuroFilter(min_cutoff=0.8, beta=0.4)
        trajectory = []
        for i in range(max(2, int(duration / interval) + 1)):
            if should_cancel and should_cancel():
                break
            rel_t = min(duration, i * interval)
            cap.set(cv2.CAP_PROP_POS_MSEC, (start_time + rel_t) * 1000.0)
            ret, frame = cap.read()
            faces = []
            if ret:
                for detection in detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).detections or []:
                    box = detection.location_data.relative_bounding_box
                    faces.append((box.xmin + box.width / 2, box.ymin + box.height / 2, box.width, box.height))
            x = filt(rel_t, lock.update(rel_t, faces) or 0.5)
            trajectory.append((rel_t, max(lo, min(hi, x)) if lo <= hi else x))
        cap.release()
        detector.close()
        return trajectory
    except Exception as exc:
        log_error("face_tracker.sample_face_trajectory", f"MediaPipe failed ({exc}); fallback to Haar.")
        return sample_face_trajectory_haar(video_path, start_time, end_time, interval=interval, should_cancel=should_cancel)


def detect_video_layout(video_path, start_time=None, end_time=None, samples: int = 12, should_cancel=None) -> dict:
    if not _mediapipe_available():
        return _detect_video_layout_haar(video_path, start_time=start_time, end_time=end_time, samples=samples, should_cancel=should_cancel)
    try:
        import cv2
        import statistics
        result = {"mode": "standard", "face_box": None, "face_area_ratio": 0.0, "face_center": (0.5, 0.5)}
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            return result
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total_frames / fps if fps else 0.0
        s = to_seconds(start_time) if start_time is not None else 0.0
        e = to_seconds(end_time) if end_time is not None else (s + 30.0 if start_time is not None else duration or 1.0)
        if e <= s:
            e = s + 1.0
        detector = _detector()
        found = []
        for i in range(samples):
            if should_cancel and should_cancel():
                break
            t = s + (e - s) * (i / (samples - 1) if samples > 1 else 0.5)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ret, frame = cap.read()
            if not ret:
                continue
            for detection in detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).detections or []:
                box = detection.location_data.relative_bounding_box
                cx, cy, area = box.xmin + box.width / 2, box.ymin + box.height / 2, box.width * box.height
                if area < 0.25 and (abs(cx - 0.5) > 0.1 or abs(cy - 0.5) > 0.1):
                    found.append((cx, cy, area, box.xmin, box.ymin, box.width, box.height))
        cap.release()
        detector.close()
        clusters = []
        for face in found:
            for cluster in clusters:
                if abs(cluster["cx"] - face[0]) < 0.1 and abs(cluster["cy"] - face[1]) < 0.1:
                    cluster["faces"].append(face)
                    cluster["cx"] = sum(f[0] for f in cluster["faces"]) / len(cluster["faces"])
                    cluster["cy"] = sum(f[1] for f in cluster["faces"]) / len(cluster["faces"])
                    break
            else:
                clusters.append({"cx": face[0], "cy": face[1], "faces": [face]})
        if clusters:
            best = max(clusters, key=lambda cluster: len(cluster["faces"]))
            if len(best["faces"]) >= max(2, int(samples * 0.2)):
                median = lambda index: statistics.median(f[index] for f in best["faces"])
                result = {"mode": "gaming", "face_box": tuple(median(i) for i in range(3, 7)),
                          "face_area_ratio": median(2), "face_center": (median(0), median(1))}
        return result
    except Exception as exc:
        log_error("face_tracker.detect_video_layout", f"MediaPipe failed ({exc}); fallback to Haar.")
        return _detect_video_layout_haar(video_path, start_time=start_time, end_time=end_time, samples=samples, should_cancel=should_cancel)


def _detect_video_layout_haar(video_path, start_time=None, end_time=None, samples=12, should_cancel=None):
    from backend.crop_utils import _detect_video_layout_haar as haar_layout
    return haar_layout(video_path, start_time=start_time, end_time=end_time, samples=samples, should_cancel=should_cancel)
