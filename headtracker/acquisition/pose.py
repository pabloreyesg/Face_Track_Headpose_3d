from __future__ import annotations

import cv2
import numpy as np


def crop_to_square(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    min_dim = min(h, w)
    top = (h - min_dim) // 2
    left = (w - min_dim) // 2
    square = frame[top:top + min_dim, left:left + min_dim]
    return cv2.flip(square, 1)


def get_head_orientation(landmarks, width: int, height: int) -> tuple[float, float, float]:
    indices = [33, 263, 1, 61, 291, 199]
    image_points = np.array(
        [[landmarks[i].x * width, landmarks[i].y * height] for i in indices],
        dtype=np.float64,
    )
    model_points = np.array([
        [-30.0, 0.0, -30.0],
        [30.0, 0.0, -30.0],
        [0.0, 0.0, 0.0],
        [-25.0, -30.0, -20.0],
        [25.0, -30.0, -20.0],
        [0.0, -60.0, -10.0],
    ], dtype=np.float64)

    focal_length = width
    center = (width / 2, height / 2)
    camera_matrix = np.array([
        [focal_length, 0, center[0]],
        [0, focal_length, center[1]],
        [0, 0, 1],
    ], dtype=np.float64)
    dist_coeffs = np.zeros((4, 1))

    try:
        success, rotation_vector, _ = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not success:
            return 0.0, 0.0, 0.0
        rmat, _ = cv2.Rodrigues(rotation_vector)
        sy = np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        pitch = np.degrees(np.arctan2(rmat[2, 1], rmat[2, 2]))
        yaw = np.degrees(np.arctan2(-rmat[2, 0], sy))
        roll = np.degrees(np.arctan2(rmat[1, 0], rmat[0, 0]))
        return float(yaw), float(pitch), float(roll)
    except Exception:
        return 0.0, 0.0, 0.0


def get_eye_distance_px(landmarks, width: int, height: int) -> float:
    left_eye = np.array([landmarks[33].x * width, landmarks[33].y * height])
    right_eye = np.array([landmarks[263].x * width, landmarks[263].y * height])
    return float(np.linalg.norm(left_eye - right_eye))


def get_distance_mm(landmarks, width: int, height: int, focal_length_px: float,
                    known_eye_distance_mm: float = 63.0) -> float:
    eye_distance_px = get_eye_distance_px(landmarks, width, height)
    if eye_distance_px == 0:
        return 0.0
    return float((known_eye_distance_mm * focal_length_px) / eye_distance_px)


def smooth_value(prev: float, current: float, alpha: float = 0.9) -> float:
    return float(alpha * prev + (1.0 - alpha) * current)


def landmarks_to_numpy(landmarks, width: int, height: int) -> np.ndarray:
    arr = np.empty((len(landmarks), 3), dtype=np.float32)
    for i, lm in enumerate(landmarks):
        arr[i, 0] = lm.x * width
        arr[i, 1] = lm.y * height
        arr[i, 2] = lm.z
    return arr
