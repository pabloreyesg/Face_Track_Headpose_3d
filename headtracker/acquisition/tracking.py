from __future__ import annotations

import contextlib
import os
import sys
import time
import urllib.request
import cv2
import mediapipe as mp
import numpy as np

from ..core.models import FramePacket, TrackingResult
from ..core.i18n import t
from .pose import crop_to_square, get_head_orientation, get_distance_mm, landmarks_to_numpy, smooth_value


@contextlib.contextmanager
def suppress_native_stderr():
    stderr_fd = sys.stderr.fileno()
    saved_fd = os.dup(stderr_fd)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, stderr_fd)
        yield
    finally:
        os.dup2(saved_fd, stderr_fd)
        os.close(devnull)
        os.close(saved_fd)


def ensure_model(path: str, url: str) -> str | None:
    if os.path.exists(path):
        return path
    print(t("model_download", path=path))
    try:
        urllib.request.urlretrieve(url, path)
        return path
    except Exception as exc:
        print(t("model_error", error=exc))
        return None


class FaceLandmarkerTracker:
    def __init__(self, model_path: str):
        base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=False,
        )
        with suppress_native_stderr():
            self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        self.start = time.monotonic()
        self.last_ts_ms = -1

    def detect(self, rgb_frame):
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        ts_ms = int((time.monotonic() - self.start) * 1000)
        if ts_ms <= self.last_ts_ms:
            ts_ms = self.last_ts_ms + 1
        self.last_ts_ms = ts_ms
        return self.landmarker.detect_for_video(image, ts_ms)

    def close(self):
        with suppress_native_stderr():
            self.landmarker.close()


class TrackingProcessor:
    def __init__(self, tracker: FaceLandmarkerTracker, yaw_offset: float, pitch_offset: float,
                 roll_offset: float, focal_length_px: float, smoothing_alpha: float,
                 known_eye_distance_mm: float, draw_landmarks=True):
        self.tracker = tracker
        self.offset = np.array([yaw_offset, pitch_offset, roll_offset], dtype=float)
        self.focal_length_px = focal_length_px
        self.alpha = smoothing_alpha
        self.known_eye_distance_mm = known_eye_distance_mm
        self.draw_landmarks = draw_landmarks
        self.prev = None
        self.connections = mp.tasks.vision.FaceLandmarksConnections.FACE_LANDMARKS_CONTOURS
        self.drawing_utils = mp.tasks.vision.drawing_utils

    def process(self, packet: FramePacket) -> TrackingResult:
        t0 = time.perf_counter()
        frame = crop_to_square(packet.frame)
        h, w = frame.shape[:2]
        result = self.tracker.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        if not result.face_landmarks:
            return TrackingResult(
                packet.frame_id, packet.timestamp,
                0.0, 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0,
                np.empty((0, 3), dtype=np.float32), {}, False,
                (time.perf_counter() - t0) * 1000.0,
                preview_frame=frame,
            )

        landmarks = result.face_landmarks[0]
        if self.draw_landmarks:
            self.drawing_utils.draw_landmarks(frame, landmarks, self.connections)

        yaw, pitch, roll = get_head_orientation(landmarks, w, h)
        raw_pose = np.array([yaw, pitch, roll], dtype=float) - self.offset
        distance_raw = get_distance_mm(
            landmarks, w, h, self.focal_length_px, self.known_eye_distance_mm
        )
        raw = np.array([raw_pose[0], raw_pose[1], raw_pose[2], distance_raw], dtype=float)
        if self.prev is None:
            filtered = raw.copy()
        else:
            filtered = np.array([
                smooth_value(self.prev[i], raw[i], self.alpha) for i in range(4)
            ])
        self.prev = filtered
        landmark_array = landmarks_to_numpy(landmarks, w, h)
        blendshapes = {}
        if result.face_blendshapes:
            blendshapes = {c.category_name: float(c.score) for c in result.face_blendshapes[0]}

        processing_ms = (time.perf_counter() - t0) * 1000.0
        return TrackingResult(
            frame_id=packet.frame_id,
            timestamp=packet.timestamp,
            yaw_raw=float(raw[0]), pitch_raw=float(raw[1]), roll_raw=float(raw[2]),
            distance_raw_mm=float(raw[3]),
            yaw_filtered=float(filtered[0]), pitch_filtered=float(filtered[1]),
            roll_filtered=float(filtered[2]), distance_filtered_mm=float(filtered[3]),
            landmarks=landmark_array,
            blendshapes=blendshapes,
            face_detected=True,
            processing_ms=processing_ms,
            preview_frame=frame,
        )
