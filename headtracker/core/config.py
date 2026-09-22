from __future__ import annotations

from dataclasses import dataclass, asdict, field
import json
from pathlib import Path


@dataclass
class CameraConfig:
    index: int = 0
    target_process_fps: float = 30.0
    requested_fps: float = 120.0  # legacy/default hint
    resolutions: list[tuple[int, int]] = field(default_factory=lambda: [
        (3840, 2160),  # 4K/UHD
        (2560, 1440),  # 2K/QHD
        (1920, 1080),  # Full HD
        (1600, 900),
        (1280, 720),
        (960, 540),
        (640, 480),
    ])
    fps_options: list[float] = field(default_factory=lambda: [120.0, 60.0, 30.0])
    mode_probe_frames: int = 12
    fps_safety_margin: float = 1.2


@dataclass
class TrackingConfig:
    smoothing_alpha: float = 0.9
    model_path: str = "face_landmarker.task"
    model_url: str = (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/latest/face_landmarker.task"
    )


@dataclass
class CalibrationConfig:
    smoothing_alpha: float = 0.5
    stability_window: int = 10
    stability_std_deg: float = 2.0
    point_timeout_s: float = 6.0
    window_size_px: int = 900
    min_range_deg: float = 6.0
    fallback_focal_length_px: float = 850.0
    known_eye_distance_mm: float = 63.0


@dataclass
class LSLConfig:
    outlet_name: str = "HeadTracking"
    outlet_type: str = "HeadPose"
    outlet_channels: int = 4
    outlet_srate: float = 30.0
    outlet_source_id: str = "headtracker"
    stream_search_timeout_s: float = 40.0
    watchdog_enabled: bool = True
    watchdog_check_interval_s: float = 3.0
    watchdog_resolve_timeout_s: float = 0.75
    watchdog_lost_after_misses: int = 2


@dataclass
class LoggingConfig:
    chunk_size: int = 300
    save_head_pose: bool = True
    save_landmarks: bool = True
    save_blendshapes: bool = True
    save_markers: bool = True


@dataclass
class VideoConfig:
    enabled: bool = False
    require_marker_stream: bool = True
    save_frame_timestamps: bool = True
    codec: str = "mp4v"
    queue_size: int = 180


@dataclass
class DisplayConfig:
    show_preview: bool = True
    draw_landmarks: bool = True


@dataclass
class AppConfig:
    language: str = "es"
    camera: CameraConfig = field(default_factory=CameraConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    lsl: LSLConfig = field(default_factory=LSLConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg = AppConfig()
    if path is None:
        return cfg
    p = Path(path)
    if not p.exists():
        return cfg
    raw = json.loads(p.read_text(encoding="utf-8"))
    if raw.get("language") in ("es", "en"):
        cfg.language = raw["language"]
    for section_name in ("camera", "tracking", "calibration", "lsl", "logging", "video", "display"):
        section = raw.get(section_name, {})
        target = getattr(cfg, section_name)
        for key, value in section.items():
            if hasattr(target, key):
                if section_name == "camera" and key == "resolutions":
                    value = [tuple(x) for x in value]
                setattr(target, key, value)
    return cfg
