from __future__ import annotations

import queue
import threading

from ..core.models import RuntimeStats


class TrackingWorker(threading.Thread):
    def __init__(self, frame_queue: queue.Queue, preview_queue: queue.Queue,
                 processor, marker_buffer, logger, outlet,
                 stop_event: threading.Event, stats: RuntimeStats,
                 lsl_integrity=None):
        super().__init__(name="TrackingWorker", daemon=True)
        self.frame_queue = frame_queue
        self.preview_queue = preview_queue
        self.processor = processor
        self.marker_buffer = marker_buffer
        self.logger = logger
        self.outlet = outlet
        self.stop_event = stop_event
        self.stats = stats
        self.lsl_integrity = lsl_integrity
        self.previous_timestamp = None

    def run(self):
        while not self.stop_event.is_set():
            try:
                packet = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            result = self.processor.process(packet)
            result.markers_since_previous_frame = self.marker_buffer.between(
                self.previous_timestamp, result.timestamp
            )
            self.previous_timestamp = result.timestamp

            if self.lsl_integrity is not None:
                snap = self.lsl_integrity.snapshot()
                result.lsl_available = bool(snap["lsl_available"])
                result.lsl_state = str(snap["state"])

            if result.face_detected:
                self.outlet.push_sample([
                    result.yaw_filtered,
                    result.pitch_filtered,
                    result.roll_filtered,
                    result.distance_filtered_mm,
                ], timestamp=result.timestamp)
            self.logger.submit_result(result)
            self.stats.processed_frames += 1
            self.stats.last_processing_ms = result.processing_ms

            if result.preview_frame is not None:
                try:
                    self.preview_queue.put_nowait(result)
                except queue.Full:
                    try:
                        self.preview_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.preview_queue.put_nowait(result)
                    except queue.Full:
                        pass
            self.frame_queue.task_done()
