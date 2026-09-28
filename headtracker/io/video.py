from __future__ import annotations

import json
import math
import queue
import shutil
import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..core.models import FramePacket, RuntimeStats


class SyncedVideoRecorder(threading.Thread):
    """Optional synchronized video recorder.

    Frames are first written to a temporary constant-frame-rate MP4 because
    OpenCV VideoWriter cannot assign an independent presentation timestamp to
    every frame. The authoritative timing is always ``video_timestamps.parquet``.

    At close(), the temporary MP4 is retimed with FFmpeg (when available) so
    its playback duration matches the timestamps actually observed during the
    acquisition. This fixes the common case where a camera probed at e.g. 60
    FPS actually sustains 48--58 FPS while recording, which otherwise produces
    visibly accelerated video.

    Local irregularities/gaps remain represented exactly in
    ``video_timestamps.parquet``; the corrected MP4 is intentionally a CFR
    convenience representation, not the scientific clock.
    """

    def __init__(self, session_dir: Path, width: int, height: int, fps: float,
                 codec: str, queue_size: int, stop_event: threading.Event,
                 stats: RuntimeStats):
        super().__init__(name="SyncedVideoRecorder", daemon=True)
        self.session_dir = Path(session_dir)
        self.stop_event = stop_event
        self.stats = stats
        self.queue = queue.Queue(maxsize=queue_size)

        self.nominal_fps = max(float(fps), 1.0)
        self.codec = codec
        self.raw_path = self.session_dir / "video_raw.mp4"
        self.final_path = self.session_dir / "video.mp4"
        self.timestamp_path = self.session_dir / "video_timestamps.parquet"
        self.report_path = self.session_dir / "video_timing_report.json"

        fourcc = cv2.VideoWriter_fourcc(*codec)
        self.writer = cv2.VideoWriter(
            str(self.raw_path), fourcc, self.nominal_fps, (width, height)
        )
        if not self.writer.isOpened():
            raise RuntimeError("No se pudo abrir VideoWriter")

        self.timestamp_rows: list[dict] = []
        self.video_frame_index = 0
        self.timing_report: dict | None = None

    def submit(self, packet: FramePacket):
        try:
            self.queue.put_nowait(packet)
        except queue.Full:
            self.stats.video_frames_dropped += 1

    def run(self):
        while not self.stop_event.is_set() or not self.queue.empty():
            try:
                packet = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.writer.write(packet.frame)
                self.timestamp_rows.append({
                    "video_frame_index": self.video_frame_index,
                    "camera_frame_id": packet.frame_id,
                    "timestamp": packet.timestamp,
                })
                self.video_frame_index += 1
                self.stats.video_frames_written += 1
            finally:
                self.queue.task_done()

    @staticmethod
    def _safe_float(value):
        value = float(value)
        return value if math.isfinite(value) else None

    def _build_timing_report(self) -> dict:
        timestamps = np.asarray([r["timestamp"] for r in self.timestamp_rows], dtype=np.float64)
        n = int(timestamps.size)
        if n >= 2:
            intervals = np.diff(timestamps)
            positive = intervals[intervals > 0]
            observed_span = float(timestamps[-1] - timestamps[0])
            effective_fps = float((n - 1) / observed_span) if observed_span > 0 else None
            median_dt = float(np.median(positive)) if positive.size else None
            mean_dt = float(np.mean(positive)) if positive.size else None
            p95_dt = float(np.percentile(positive, 95)) if positive.size else None
            max_dt = float(np.max(positive)) if positive.size else None
        else:
            intervals = np.asarray([], dtype=np.float64)
            observed_span = 0.0
            effective_fps = None
            median_dt = mean_dt = p95_dt = max_dt = None

        # OpenCV's CFR playback duration is determined by frame count / declared fps.
        raw_mp4_duration = float(n / self.nominal_fps) if n else 0.0
        # Add one representative frame duration to the timestamp span so the last
        # displayed frame occupies time as well. This is a better playback target
        # than last-first alone.
        representative_dt = median_dt if median_dt and median_dt > 0 else (1.0 / self.nominal_fps)
        target_playback_duration = observed_span + representative_dt if n else 0.0
        speed_ratio_before = (
            target_playback_duration / raw_mp4_duration
            if raw_mp4_duration > 0 and target_playback_duration > 0 else None
        )

        expected_dt = (1.0 / effective_fps) if effective_fps and effective_fps > 0 else None
        gap_threshold = max(0.100, 3.0 * expected_dt) if expected_dt else 0.100
        gap_count = int(np.sum(intervals > gap_threshold)) if intervals.size else 0

        report = {
            "timing_authority": "video_timestamps.parquet",
            "representation": "CFR MP4 retimed to observed session duration",
            "frames_written": n,
            "frames_dropped_by_video_queue": int(self.stats.video_frames_dropped),
            "nominal_writer_fps": self._safe_float(self.nominal_fps),
            "effective_fps_from_timestamps": self._safe_float(effective_fps) if effective_fps is not None else None,
            "timestamp_span_seconds": self._safe_float(observed_span),
            "target_playback_duration_seconds": self._safe_float(target_playback_duration),
            "raw_mp4_duration_seconds_estimated": self._safe_float(raw_mp4_duration),
            "playback_speed_ratio_before_correction": self._safe_float(speed_ratio_before) if speed_ratio_before is not None else None,
            "median_frame_interval_ms": self._safe_float(median_dt * 1000.0) if median_dt is not None else None,
            "mean_frame_interval_ms": self._safe_float(mean_dt * 1000.0) if mean_dt is not None else None,
            "p95_frame_interval_ms": self._safe_float(p95_dt * 1000.0) if p95_dt is not None else None,
            "max_frame_interval_ms": self._safe_float(max_dt * 1000.0) if max_dt is not None else None,
            "gap_threshold_ms": self._safe_float(gap_threshold * 1000.0),
            "large_gap_count": gap_count,
            "ffmpeg_available": bool(shutil.which("ffmpeg")),
            "retiming_applied": False,
            "retiming_status": "pending",
            "final_mp4_duration_seconds_estimated": None,
            "final_duration_error_seconds_estimated": None,
        }
        return report

    def _retime_mp4(self, report: dict) -> None:
        n = report["frames_written"]
        if not n:
            report["retiming_status"] = "no_frames"
            return

        target = report["target_playback_duration_seconds"] or 0.0
        raw_duration = report["raw_mp4_duration_seconds_estimated"] or 0.0
        if target <= 0 or raw_duration <= 0:
            shutil.move(str(self.raw_path), str(self.final_path))
            report["retiming_status"] = "invalid_duration_raw_kept"
            return

        factor = target / raw_duration
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            shutil.move(str(self.raw_path), str(self.final_path))
            report["retiming_status"] = "ffmpeg_not_found_raw_kept"
            report["final_mp4_duration_seconds_estimated"] = raw_duration
            report["final_duration_error_seconds_estimated"] = raw_duration - target
            return

        # If timing already matches within 0.5%, avoid an unnecessary transcode.
        if abs(factor - 1.0) <= 0.005:
            shutil.move(str(self.raw_path), str(self.final_path))
            report["retiming_status"] = "not_needed"
            report["final_mp4_duration_seconds_estimated"] = raw_duration
            report["final_duration_error_seconds_estimated"] = raw_duration - target
            return

        cmd = [
            ffmpeg, "-y", "-loglevel", "error",
            "-i", str(self.raw_path),
            "-an",
            "-vf", f"setpts=PTS*{factor:.12f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-movflags", "+faststart",
            str(self.final_path),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            report["retiming_applied"] = True
            report["retiming_status"] = "ok"
            # The setpts factor is what defines the new duration. This is an
            # estimate; timestamps remain authoritative.
            final_est = raw_duration * factor
            report["final_mp4_duration_seconds_estimated"] = final_est
            report["final_duration_error_seconds_estimated"] = final_est - target
            try:
                self.raw_path.unlink(missing_ok=True)
            except Exception:
                pass
        except Exception as exc:
            # Preserve the captured video even if FFmpeg/transcoding fails.
            if not self.final_path.exists() and self.raw_path.exists():
                shutil.move(str(self.raw_path), str(self.final_path))
            report["retiming_status"] = f"ffmpeg_failed: {exc}"
            report["final_mp4_duration_seconds_estimated"] = raw_duration
            report["final_duration_error_seconds_estimated"] = raw_duration - target

    def close(self):
        self.queue.join()
        self.writer.release()

        df = pd.DataFrame(self.timestamp_rows, columns=[
            "video_frame_index", "camera_frame_id", "timestamp"
        ])
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, self.timestamp_path)

        report = self._build_timing_report()
        self._retime_mp4(report)
        self.timing_report = report
        self.report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        ratio = report.get("playback_speed_ratio_before_correction")
        eff = report.get("effective_fps_from_timestamps")
        target = report.get("target_playback_duration_seconds")
        final_error = report.get("final_duration_error_seconds_estimated")
        print("\n🎞️ VIDEO TIMING")
        if target is not None:
            print(f"   Duración observada objetivo: {target:.3f} s")
        print(f"   Frames escritos: {report['frames_written']}")
        print(f"   Frames perdidos en cola de video: {report['frames_dropped_by_video_queue']}")
        if eff is not None:
            print(f"   FPS efectivo por timestamps: {eff:.3f}")
        print(f"   FPS nominal del writer: {self.nominal_fps:.3f}")
        if ratio is not None:
            if ratio > 1.005:
                print(f"   ⚠️ El MP4 sin corregir habría reproducido ~{ratio:.3f}× más rápido.")
            elif ratio < 0.995:
                print(f"   ⚠️ El MP4 sin corregir habría reproducido ~{1.0/ratio:.3f}× más lento.")
            else:
                print("   Velocidad original dentro de ±0.5%.")
        print(f"   Retiming: {report['retiming_status']}")
        if final_error is not None:
            print(f"   Error temporal final estimado: {final_error:+.4f} s")
        if report.get("large_gap_count", 0):
            print(
                f"   ⚠️ Gaps grandes detectados: {report['large_gap_count']}. "
                "Consulte video_timestamps.parquet para timing local exacto."
            )
