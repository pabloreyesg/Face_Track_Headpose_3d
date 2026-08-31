from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from pylsl import local_clock


def create_session_dir(root: str | Path, prefix: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = Path(root) / f"{prefix}_{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_metadata(path: Path, *, prefix, config, cap, measured_fps,
                   calibration_offset, focal_length_px, known_distance_cm,
                   marker_stream_info, marker_time_correction, calibration_quality_ok,
                   video_enabled, lsl_integrity=None, stats=None, selected_camera_mode=None):
    marker_info = None
    if marker_stream_info is not None:
        marker_info = dict(marker_stream_info)
        marker_info["time_correction"] = marker_time_correction

    integrity = lsl_integrity.snapshot() if lsl_integrity is not None else {
        "state": "DISABLED",
        "connected_at_start": False,
        "disconnect_count": 0,
        "reconnect_count": 0,
        "total_unavailable_seconds": 0.0,
        "recovery_limited": False,
        "lsl_available": False,
    }

    data = {
        "prefix": prefix,
        "session_start_iso": dt.datetime.now().isoformat(),
        "lsl_local_clock_at_metadata": local_clock(),
        "camera": {
            "width": int(cap.get(3)),
            "height": int(cap.get(4)),
            "measured_fps": measured_fps,
            "requested_width": (selected_camera_mode.requested_width if selected_camera_mode is not None else None),
            "requested_height": (selected_camera_mode.requested_height if selected_camera_mode is not None else None),
            "requested_fps": (selected_camera_mode.requested_fps if selected_camera_mode is not None else None),
            "selection_policy": "highest viable pixel count first; measured FPS second",
        },
        "calibration": {
            "offset_yaw": float(calibration_offset[0]),
            "offset_pitch": float(calibration_offset[1]),
            "offset_roll": float(calibration_offset[2]),
            "quality_ok": calibration_quality_ok,
            "known_distance_cm": known_distance_cm,
            "focal_length_px": focal_length_px,
        },
        "lsl_marker_stream": marker_info,
        "lsl_status": {
            "markers_enabled": marker_stream_info is not None,
            "markers_recorded": marker_stream_info is not None,
            "interpretability_warning": (
                None if marker_stream_info is not None else
                "No LSL marker/trigger stream was connected. Experimental events were not recorded; "
                "temporal interpretation relative to stimuli, responses, or external events may be limited."
            ),
        },
        "lsl_integrity": integrity,
        "privacy": {
            "raw_frames_persisted": bool(video_enabled),
            "video_recording_enabled": bool(video_enabled),
            "video_requires_marker_stream": bool(config.video.require_marker_stream),
            "preview_enabled": bool(config.display.show_preview),
        },
        "timing": {
            "frame_timestamp_clock": "pylsl.local_clock sampled immediately after cap.read()",
            "marker_timestamp_clock": "source LSL timestamp + inlet.time_correction()",
            "video_timestamp_table": "video_timestamps.parquet" if video_enabled else None,
            "video_timing_report": "video_timing_report.json" if video_enabled else None,
            "mp4_playback_time_is_authoritative": False,
            "mp4_timing_policy": "retimed to observed timestamp duration; video_timestamps.parquet remains authoritative",
        },
        "config": config.to_dict(),
    }
    if stats is not None:
        data["runtime_stats"] = {
            "camera_frames": stats.camera_frames,
            "processed_frames": stats.processed_frames,
            "dropped_camera_frames": stats.dropped_camera_frames,
            "video_frames_written": stats.video_frames_written,
            "video_frames_dropped": stats.video_frames_dropped,
            "marker_count": stats.marker_count,
        }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
