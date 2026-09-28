from __future__ import annotations

from collections import deque
import time
import cv2
import numpy as np

from .pose import crop_to_square, get_head_orientation, get_eye_distance_px
from ..core.i18n import t

TARGETS = [
    ("CENTER", 0.5, 0.5),
    ("LEFT", 0.12, 0.5),
    ("RIGHT", 0.88, 0.5),
    ("UP", 0.5, 0.12),
    ("DOWN", 0.5, 0.88),
]


def _capture_point(tracker, cap, window_name, label, tx, ty, cfg):
    buffer = deque(maxlen=cfg.stability_window)
    smoothed = None
    start_time = time.time()

    while time.time() - start_time < cfg.point_timeout_s:
        ret, frame = cap.read()
        if not ret:
            continue
        frame = crop_to_square(frame)
        h, w = frame.shape[:2]
        result = tracker.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        stable = False
        face_found = bool(result.face_landmarks)
        if face_found:
            landmarks = result.face_landmarks[0]
            raw = np.array([
                *get_head_orientation(landmarks, w, h),
                get_eye_distance_px(landmarks, w, h),
            ], dtype=float)
            smoothed = raw if smoothed is None else (
                cfg.smoothing_alpha * smoothed + (1.0 - cfg.smoothing_alpha) * raw
            )
            buffer.append(tuple(smoothed))
            if len(buffer) == buffer.maxlen:
                std = np.std(buffer, axis=0)
                stable = std[0] < cfg.stability_std_deg and std[1] < cfg.stability_std_deg

        cx, cy = int(tx * w), int(ty * h)
        color = (0, 255, 0) if stable else (0, 255, 255)
        cv2.circle(frame, (cx, cy), 18, color, 3)
        cv2.circle(frame, (cx, cy), 3, color, -1)
        remaining = max(0, int(cfg.point_timeout_s - (time.time() - start_time)))
        cv2.putText(frame, t("look_at", label=t(label), remaining=remaining), (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        if not face_found:
            cv2.putText(frame, t("no_face"), (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(frame, t("force_cancel"), (20, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.imshow(window_name, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            return None, True
        if key == ord(' ') and buffer:
            break
        if stable:
            break

    if buffer:
        return tuple(np.mean(buffer, axis=0)), False
    return None, False


def _summary(cap, window_name, corrected, lr_ok, lr_range, ud_ok, ud_range):
    quality_ok = lr_ok and ud_ok
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        frame = crop_to_square(frame)
        h, _ = frame.shape[:2]
        y = 30
        cv2.putText(frame, t("calibration_result"), (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        y += 30
        for label, v in corrected.items():
            text = f"{t(label)}: {t('no_data')}" if v is None else f"{t(label)}: Yaw={v[0]:+.1f} Pitch={v[1]:+.1f}"
            cv2.putText(frame, text, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
            y += 22
        status = t("quality_ok") if quality_ok else t("quality_low")
        cv2.putText(frame, status, (20, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if quality_ok else (0, 165, 255), 2)
        cv2.putText(frame, f"H={lr_range:.1f} deg  V={ud_range:.1f} deg", (20, y + 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.putText(frame, t("calibration_controls"), (20, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.imshow(window_name, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (13, 10):
            return "accept"
        if key in (ord('r'), ord('R')):
            return "retry"
        if key == 27:
            return "cancel"


def calibrate(tracker, cap, known_distance_mm: float, cfg):
    window = t("calibration_window")
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    size = int(getattr(cfg, "window_size_px", 900))
    cv2.resizeWindow(window, size, size)
    cv2.setWindowProperty(window, cv2.WND_PROP_TOPMOST, 1)
    print(t("calibration_intro"))

    while True:
        points = {}
        cancelled = False
        for label, tx, ty in TARGETS:
            sample, cancelled = _capture_point(tracker, cap, window, label, tx, ty, cfg)
            points[label] = sample
            if cancelled:
                break

        if cancelled:
            cv2.destroyWindow(window)
            return np.zeros(3), cfg.fallback_focal_length_px, False
        if points.get("CENTER") is None:
            print(t("center_no_face"))
            continue

        offset = np.array(points["CENTER"][:3], dtype=float)
        eye_distance_px = float(points["CENTER"][3])
        corrected = {
            label: (np.array(v[:3]) - offset if v is not None else None)
            for label, v in points.items()
        }

        def span(a, b, axis):
            if a is None or b is None:
                return False, 0.0
            delta = abs(float(a[axis] - b[axis]))
            return delta > cfg.min_range_deg, delta

        lr_ok, lr_range = span(corrected.get("LEFT"), corrected.get("RIGHT"), 0)
        ud_ok, ud_range = span(corrected.get("UP"), corrected.get("DOWN"), 1)
        decision = _summary(cap, window, corrected, lr_ok, lr_range, ud_ok, ud_range)
        if decision == "retry":
            continue
        cv2.destroyWindow(window)
        if decision == "cancel":
            return np.zeros(3), cfg.fallback_focal_length_px, False
        focal_length_px = (
            eye_distance_px * known_distance_mm / cfg.known_eye_distance_mm
            if eye_distance_px > 0 else cfg.fallback_focal_length_px
        )
        return offset, float(focal_length_px), bool(lr_ok and ud_ok)
