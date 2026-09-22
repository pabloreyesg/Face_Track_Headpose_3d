from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import os

import cv2

# OpenCV Linux wheels may point Qt at a non-existent bundled font directory.
# Use the system DejaVu directory when available; this affects only this child process.
_system_font_dir = "/usr/share/fonts/truetype/dejavu"
if Path(_system_font_dir).exists():
    os.environ["QT_QPA_FONTDIR"] = _system_font_dir

from headtracker.core.config import load_config
from headtracker.acquisition.camera import CameraMode, apply_camera_mode
from headtracker.acquisition.tracking import FaceLandmarkerTracker, ensure_model
from headtracker.acquisition.calibration import calibrate
from headtracker.core.i18n import set_language


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    p.add_argument('--result', required=True)
    p.add_argument('--language', choices=['es','en'], default='es')
    p.add_argument('--camera-index', type=int, required=True)
    p.add_argument('--requested-width', type=int, required=True)
    p.add_argument('--requested-height', type=int, required=True)
    p.add_argument('--requested-fps', type=float, required=True)
    p.add_argument('--width', type=int, required=True)
    p.add_argument('--height', type=int, required=True)
    p.add_argument('--measured-fps', type=float, required=True)
    p.add_argument('--distance-cm', type=float, required=True)
    return p.parse_args()


def write_result(path: Path, payload: dict):
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def main():
    args = parse_args()
    result_path = Path(args.result)
    set_language(args.language)
    cfg = load_config(args.config)
    cfg.language = args.language
    mode = CameraMode(
        requested_width=args.requested_width,
        requested_height=args.requested_height,
        requested_fps=args.requested_fps,
        width=args.width,
        height=args.height,
        measured_fps=args.measured_fps,
    )
    cap = cv2.VideoCapture(args.camera_index)
    tracker = None
    if not cap.isOpened():
        write_result(result_path, {'ok': False, 'error': 'camera'})
        return 2
    try:
        apply_camera_mode(cap, mode)
        model_path = ensure_model(cfg.tracking.model_path, cfg.tracking.model_url)
        if model_path is None:
            write_result(result_path, {'ok': False, 'error': 'model'})
            return 3
        tracker = FaceLandmarkerTracker(model_path)
        offset, focal_length_px, quality_ok = calibrate(
            tracker, cap, args.distance_cm * 10.0, cfg.calibration
        )
        write_result(result_path, {
            'ok': True,
            'offset': [float(x) for x in offset],
            'focal_length_px': float(focal_length_px),
            'quality_ok': bool(quality_ok),
        })
        return 0
    except Exception as exc:
        write_result(result_path, {'ok': False, 'error': str(exc)})
        return 4
    finally:
        if tracker is not None:
            try:
                tracker.close()
            except Exception:
                pass
        cap.release()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
