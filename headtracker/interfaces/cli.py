from __future__ import annotations

import argparse
import queue
import threading
import time
import cv2

from headtracker.acquisition.camera import CameraWorker, select_camera_mode
from headtracker.acquisition.calibration import calibrate
from headtracker.core.config import load_config
from headtracker.core.i18n import choose_language, set_language, t
from headtracker.io.logger import AsyncSessionLogger
from headtracker.io.lsl import (
    MarkerBuffer, MarkerReceiver, LSLIntegrityState, LSLWatchdog,
    create_outlet, get_time_correction, select_marker_stream,
)
from headtracker.core.models import RuntimeStats
from headtracker.core.session import create_session_dir, write_metadata
from headtracker.acquisition.tracking import FaceLandmarkerTracker, TrackingProcessor, ensure_model
from headtracker.io.video import SyncedVideoRecorder
from headtracker.acquisition.worker import TrackingWorker


def parse_args():
    p = argparse.ArgumentParser(description="HeadTracker modular con LSL y video sincronizado opcional")
    p.add_argument("--config", default=None, help="config.json opcional")
    p.add_argument("--prefix", default=None, help="Prefijo/nombre del experimento")
    p.add_argument("--sessions-dir", default="sessions")
    p.add_argument("--video", action="store_true", help="Solicita video sincronizado (OFF por defecto)")
    p.add_argument("--language", choices=["es", "en"], default=None, help="Idioma de interfaz / interface language")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = load_config(args.config)
    cfg.language = choose_language(args.language)
    set_language(cfg.language)
    prefix = args.prefix or input(t("experiment_prefix")).strip() or "session"
    session_dir = create_session_dir(args.sessions_dir, prefix)
    cfg.save(session_dir / "config.json")

    stop_event = threading.Event()
    stats = RuntimeStats()
    cap = cv2.VideoCapture(cfg.camera.index)
    if not cap.isOpened():
        raise RuntimeError("No se pudo abrir la cámara")

    selected_camera_mode = select_camera_mode(
        cap, cfg.camera.resolutions, cfg.camera.fps_options,
        minimum_fps=cfg.camera.target_process_fps,
        probe_frames=cfg.camera.mode_probe_frames,
    )
    measured_fps = selected_camera_mode.measured_fps if selected_camera_mode is not None else 0.0
    if selected_camera_mode is not None:
        cfg.camera.requested_fps = selected_camera_mode.requested_fps
    cfg.save(session_dir / "config.json")

    model_path = ensure_model(cfg.tracking.model_path, cfg.tracking.model_url)
    if model_path is None:
        raise RuntimeError("MediaPipe FaceLandmarker model no disponible")
    tracker = FaceLandmarkerTracker(model_path)

    distance_input = input(t("camera_distance")).strip()
    try:
        known_distance_cm = float(distance_input) if distance_input else 60.0
    except ValueError:
        known_distance_cm = 60.0
    offset, focal_length_px, calibration_ok = calibrate(
        tracker, cap, known_distance_cm * 10.0, cfg.calibration
    )

    marker_inlet, marker_stream_info = select_marker_stream(cfg.lsl.stream_search_timeout_s)
    marker_correction = get_time_correction(marker_inlet)
    lsl_markers_enabled = marker_inlet is not None
    lsl_integrity = LSLIntegrityState(lsl_markers_enabled, marker_stream_info)

    if lsl_markers_enabled:
        print(t("lsl_active"))
        if lsl_integrity.recovery_limited:
            print(t("lsl_limited"))
    else:
        print(t("lsl_disabled"))

    # Privacy rule: video is OFF unless explicitly requested. If configured to require
    # a marker stream, absence of that stream disables video rather than producing
    # scientifically unusable unsynchronized footage.
    video_requested = bool(args.video or cfg.video.enabled)
    video_enabled = video_requested
    if video_requested and cfg.video.require_marker_stream and marker_inlet is None:
        print(t("video_disabled_no_lsl"))
        video_enabled = False

    logger = AsyncSessionLogger(session_dir, cfg, stop_event)
    logger.start()
    marker_buffer = MarkerBuffer()

    marker_receiver = None
    watchdog = None
    if marker_inlet is not None:
        marker_receiver = MarkerReceiver(
            marker_inlet, marker_correction, marker_buffer, logger, stop_event, stats,
            integrity=lsl_integrity,
        )
        marker_receiver.start()

        if cfg.lsl.watchdog_enabled:
            watchdog = LSLWatchdog(
                marker_stream_info, lsl_integrity, logger, stop_event,
                check_interval_s=cfg.lsl.watchdog_check_interval_s,
                resolve_timeout_s=cfg.lsl.watchdog_resolve_timeout_s,
                lost_after_misses=cfg.lsl.watchdog_lost_after_misses,
            )
            watchdog.start()

    video_recorder = None
    if video_enabled:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = measured_fps if measured_fps > 0 else cfg.camera.target_process_fps
        video_recorder = SyncedVideoRecorder(
            session_dir, width, height, fps, cfg.video.codec,
            cfg.video.queue_size, stop_event, stats,
        )
        video_recorder.start()
        print(t("video_active"))
    else:
        print(t("privacy_mode"))

    outlet = create_outlet(cfg.lsl)
    processor = TrackingProcessor(
        tracker,
        float(offset[0]), float(offset[1]), float(offset[2]),
        focal_length_px,
        cfg.tracking.smoothing_alpha,
        cfg.calibration.known_eye_distance_mm,
        cfg.display.draw_landmarks,
    )

    frame_queue = queue.Queue(maxsize=2)
    preview_queue = queue.Queue(maxsize=1)
    camera_worker = CameraWorker(cap, frame_queue, stop_event, stats, video_recorder)
    tracking_worker = TrackingWorker(
        frame_queue, preview_queue, processor, marker_buffer, logger,
        outlet, stop_event, stats, lsl_integrity=lsl_integrity,
    )

    write_metadata(
        session_dir / "session.json",
        prefix=prefix, config=cfg, cap=cap, measured_fps=measured_fps,
        calibration_offset=offset, focal_length_px=focal_length_px,
        known_distance_cm=known_distance_cm,
        marker_stream_info=marker_stream_info, marker_time_correction=marker_correction,
        calibration_quality_ok=calibration_ok,
        video_enabled=video_enabled, lsl_integrity=lsl_integrity,
        selected_camera_mode=selected_camera_mode,
    )

    camera_worker.start()
    tracking_worker.start()
    print("\n" + t("session", path=session_dir))
    print(t("quit_help"))

    try:
        if cfg.display.show_preview:
            cv2.namedWindow("Tracking", cv2.WINDOW_NORMAL)
            cv2.setWindowProperty("Tracking", cv2.WND_PROP_TOPMOST, 1)
        last_status = 0.0
        while not stop_event.is_set():
            result = None
            try:
                result = preview_queue.get(timeout=0.05)
            except queue.Empty:
                pass

            if result is not None and cfg.display.show_preview:
                frame = result.preview_frame
                if result.face_detected:
                    cv2.putText(frame, f"Yaw {result.yaw_filtered:+.1f}", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    cv2.putText(frame, f"Pitch {result.pitch_filtered:+.1f}", (10, 55),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    cv2.putText(frame, f"Roll {result.roll_filtered:+.1f}", (10, 80),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    cv2.putText(frame, f"Dist {result.distance_filtered_mm:.0f} mm", (10, 105),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

                mode = "VIDEO SYNC" if video_enabled else "NO VIDEO"
                cv2.putText(frame, mode, (10, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (0, 0, 255) if video_enabled else (128, 128, 128), 2)
                lsl_snap = lsl_integrity.snapshot()
                lsl_text = f"LSL {lsl_snap['state']}"
                lsl_color = (0, 255, 0) if lsl_snap["lsl_available"] else (0, 0, 255)
                if lsl_snap["state"] == "DISABLED":
                    lsl_color = (0, 165, 255)
                cv2.putText(frame, lsl_text, (10, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            lsl_color, 2)
                cv2.imshow("Tracking", frame)
                preview_queue.task_done()

            if cfg.display.show_preview:
                key = cv2.waitKey(1) & 0xFF
                if key in (ord('q'), 27):
                    stop_event.set()
                    break

            now = time.monotonic()
            if now - last_status > 2.0:
                lsl_snap = lsl_integrity.snapshot()
                print(
                    f"📊 cam={stats.camera_frames} proc={stats.processed_frames} "
                    f"dropCam={stats.dropped_camera_frames} markers={stats.marker_count} "
                    f"proc={stats.last_processing_ms:.1f}ms "
                    f"LSL={lsl_snap['state']} "
                    f"video={stats.video_frames_written if video_enabled else 'OFF'}"
                )
                last_status = now

    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        camera_worker.join(timeout=2)
        tracking_worker.join(timeout=3)
        if marker_receiver:
            marker_receiver.join(timeout=2)
        if watchdog:
            watchdog.join(timeout=2)
        if video_recorder:
            video_recorder.join(timeout=3)
            video_recorder.close()
        logger.join(timeout=5)
        logger.close()
        tracker.close()

        write_metadata(
            session_dir / "session.json",
            prefix=prefix, config=cfg, cap=cap, measured_fps=measured_fps,
            calibration_offset=offset, focal_length_px=focal_length_px,
            known_distance_cm=known_distance_cm,
            marker_stream_info=marker_stream_info, marker_time_correction=marker_correction,
            calibration_quality_ok=calibration_ok,
            video_enabled=video_enabled, lsl_integrity=lsl_integrity,
            stats=stats, selected_camera_mode=selected_camera_mode,
        )
        cap.release()
        cv2.destroyAllWindows()
        snap = lsl_integrity.snapshot()
        if snap["disconnect_count"]:
            print(
                f"⚠️ Integridad LSL: {snap['disconnect_count']} caída(s), "
                f"{snap['reconnect_count']} reconexión(es), "
                f"~{snap['total_unavailable_seconds']:.2f}s no disponible(s)."
            )
        print(t("session_closed", path=session_dir))


if __name__ == "__main__":
    main()
