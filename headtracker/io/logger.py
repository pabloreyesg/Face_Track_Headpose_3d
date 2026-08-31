from __future__ import annotations

import queue
import threading
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..core.models import MarkerEvent, LSLEvent, TrackingResult


class ChunkedParquetWriter:
    def __init__(self, path: Path, chunk_size=300):
        self.path = Path(path)
        self.chunk_size = chunk_size
        self.buffer = []
        self.writer = None
        self.schema = None
        self.columns = None
        self.total_rows = 0

    def add(self, row: dict):
        self.buffer.append(row)
        if len(self.buffer) >= self.chunk_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        df = pd.DataFrame(self.buffer)
        if self.columns is None:
            self.columns = list(df.columns)
        else:
            df = df.reindex(columns=self.columns)
        table = pa.Table.from_pandas(df, preserve_index=False)
        if self.writer is None:
            self.schema = table.schema
            self.writer = pq.ParquetWriter(self.path, self.schema)
        else:
            table = table.cast(self.schema)
        self.writer.write_table(table)
        self.total_rows += len(self.buffer)
        self.buffer.clear()

    def close(self):
        self.flush()
        if self.writer:
            self.writer.close()


class AsyncSessionLogger(threading.Thread):
    def __init__(self, session_dir: Path, cfg, stop_event: threading.Event):
        super().__init__(name="LoggerWorker", daemon=True)
        self.session_dir = Path(session_dir)
        self.cfg = cfg
        self.stop_event = stop_event
        self.queue = queue.Queue(maxsize=2000)
        c = cfg.logging.chunk_size
        self.head = ChunkedParquetWriter(self.session_dir / "head_pose.parquet", c) if cfg.logging.save_head_pose else None
        self.landmarks = ChunkedParquetWriter(self.session_dir / "landmarks.parquet", c) if cfg.logging.save_landmarks else None
        self.blendshapes = ChunkedParquetWriter(self.session_dir / "blendshapes.parquet", c) if cfg.logging.save_blendshapes else None
        self.markers = ChunkedParquetWriter(self.session_dir / "markers.parquet", c) if cfg.logging.save_markers else None
        self.lsl_events = ChunkedParquetWriter(self.session_dir / "lsl_events.parquet", c)

    def submit_result(self, result: TrackingResult):
        self.queue.put(("tracking", result))

    def submit_marker(self, marker: MarkerEvent):
        self.queue.put(("marker", marker))

    def submit_lsl_event(self, event: LSLEvent):
        self.queue.put(("lsl_event", event))

    def run(self):
        while not self.stop_event.is_set() or not self.queue.empty():
            try:
                kind, obj = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if kind == "tracking":
                    self._write_tracking(obj)
                elif kind == "marker":
                    self._write_marker(obj)
                elif kind == "lsl_event":
                    self._write_lsl_event(obj)
            finally:
                self.queue.task_done()

    def _write_tracking(self, r: TrackingResult):
        if self.head:
            self.head.add({
                "frame_id": r.frame_id,
                "timestamp": r.timestamp,
                "face_detected": r.face_detected,
                "yaw_raw": r.yaw_raw,
                "pitch_raw": r.pitch_raw,
                "roll_raw": r.roll_raw,
                "distance_raw_mm": r.distance_raw_mm,
                "yaw_filtered": r.yaw_filtered,
                "pitch_filtered": r.pitch_filtered,
                "roll_filtered": r.roll_filtered,
                "distance_filtered_mm": r.distance_filtered_mm,
                "processing_ms": r.processing_ms,
                "lsl_available": r.lsl_available,
                "lsl_state": r.lsl_state,
            })
        if r.face_detected and self.landmarks:
            row = {"frame_id": r.frame_id, "timestamp": r.timestamp}
            for i in range(r.landmarks.shape[0]):
                row[f"L{i}_x"] = float(r.landmarks[i, 0])
                row[f"L{i}_y"] = float(r.landmarks[i, 1])
                row[f"L{i}_z"] = float(r.landmarks[i, 2])
            self.landmarks.add(row)
        if r.face_detected and self.blendshapes:
            row = {"frame_id": r.frame_id, "timestamp": r.timestamp, **r.blendshapes}
            self.blendshapes.add(row)

    def _write_marker(self, e: MarkerEvent):
        if self.markers:
            self.markers.add({
                "marker_id": e.marker_id,
                "value": e.value,
                "timestamp": e.timestamp,
                "raw_timestamp": e.raw_timestamp,
            })

    def _write_lsl_event(self, e: LSLEvent):
        self.lsl_events.add({
            "timestamp": e.timestamp,
            "event": e.event,
            "source_id": e.source_id,
            "stream_name": e.stream_name,
            "detail": e.detail,
        })

    def close(self):
        self.queue.join()
        for writer in (self.head, self.landmarks, self.blendshapes, self.markers, self.lsl_events):
            if writer:
                writer.close()
