from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import numpy as np


@dataclass(slots=True)
class FramePacket:
    frame_id: int
    timestamp: float  # pylsl.local_clock(), sampled immediately after cap.read()
    frame: np.ndarray


@dataclass(slots=True)
class MarkerEvent:
    marker_id: int
    value: str
    timestamp: float  # corrected into this machine's LSL local_clock domain
    raw_timestamp: float


@dataclass(slots=True)
class LSLEvent:
    timestamp: float
    event: str
    source_id: str
    stream_name: str
    detail: str = ""


@dataclass(slots=True)
class TrackingResult:
    frame_id: int
    timestamp: float
    yaw_raw: float
    pitch_raw: float
    roll_raw: float
    distance_raw_mm: float
    yaw_filtered: float
    pitch_filtered: float
    roll_filtered: float
    distance_filtered_mm: float
    landmarks: np.ndarray  # shape (N, 3), pixel x/y + normalized z
    blendshapes: dict[str, float]
    face_detected: bool
    processing_ms: float
    preview_frame: Optional[np.ndarray] = None
    markers_since_previous_frame: list[MarkerEvent] = field(default_factory=list)
    lsl_available: bool = False
    lsl_state: str = "DISABLED"


@dataclass(slots=True)
class RuntimeStats:
    camera_frames: int = 0
    processed_frames: int = 0
    dropped_camera_frames: int = 0
    video_frames_written: int = 0
    video_frames_dropped: int = 0
    marker_count: int = 0
    last_processing_ms: float = 0.0
    last_camera_timestamp: float = 0.0
