from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time
import cv2
from pylsl import local_clock

from ..core.i18n import t
from ..core.models import FramePacket, RuntimeStats


@dataclass(frozen=True)
class CameraMode:
    requested_width: int
    requested_height: int
    requested_fps: float
    width: int
    height: int
    measured_fps: float

    @property
    def pixels(self) -> int:
        return self.width * self.height


def _resolution_label(w: int, h: int) -> str:
    if w >= 3800 and h >= 2100:
        return "4K/UHD"
    if w >= 2500 and h >= 1400:
        return "2K/QHD"
    if w >= 1900 and h >= 1000:
        return "Full HD"
    if w >= 1200 and h >= 700:
        return "HD"
    return ""


def probe_camera_modes(cap, resolutions, fps_options, probe_frames=12, stabilization_frames=3):
    """Probe requested resolution/FPS combinations and return deduplicated actual modes.

    OpenCV cannot reliably enumerate all UVC modes on every backend, so we actively probe
    common/user-configured combinations and measure the delivered frame rate. The menu
    reports *actual* width/height and measured FPS instead of trusting driver claims.
    """
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    print(t("camera_probe_title"))
    candidates = []
    seen_requests = set()

    for width, height in resolutions:
        for requested_fps in fps_options:
            req = (int(width), int(height), float(requested_fps))
            if req in seen_requests:
                continue
            seen_requests.add(req)

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, requested_fps)
            for _ in range(stabilization_frames):
                cap.read()

            start = time.perf_counter()
            grabbed = 0
            for _ in range(probe_frames):
                ret, _ = cap.read()
                grabbed += int(bool(ret))
            elapsed = time.perf_counter() - start
            measured = grabbed / elapsed if elapsed > 0 else 0.0
            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(t("camera_probe_line", rw=width, rh=height, rfps=requested_fps,
                    aw=actual_w, ah=actual_h, mfps=measured))
            if grabbed and actual_w > 0 and actual_h > 0 and measured > 0:
                candidates.append(CameraMode(width, height, requested_fps, actual_w, actual_h, measured))

    # Many drivers map unsupported requests to the same actual mode. Keep the best
    # measurement for each actual resolution + requested FPS combination.
    dedup = {}
    fps_refs = [float(x) for x in fps_options] or [30.0]
    for mode in candidates:
        # Collapse requests that the driver maps to the same real mode. Example:
        # requesting 120 and 60 Hz may both deliver ~30 FPS at 4K.
        observed_class = min(fps_refs, key=lambda x: abs(x - mode.measured_fps))
        key = (mode.width, mode.height, observed_class)
        old = dedup.get(key)
        if old is None or mode.measured_fps > old.measured_fps:
            dedup[key] = mode
    return list(dedup.values())


def recommend_mode(modes, minimum_fps=30.0):
    """Resolution is the primary criterion; FPS breaks ties.

    Prefer the highest pixel count among modes that actually sustain minimum_fps.
    If none do, choose the highest-resolution detected mode and then the fastest one.
    """
    if not modes:
        return None
    viable = [m for m in modes if m.measured_fps >= minimum_fps]
    pool = viable if viable else modes
    return max(pool, key=lambda m: (m.pixels, m.measured_fps, m.requested_fps))


def apply_camera_mode(cap, mode: CameraMode, settle_frames=3) -> CameraMode:
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, mode.requested_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, mode.requested_height)
    cap.set(cv2.CAP_PROP_FPS, mode.requested_fps)
    for _ in range(settle_frames):
        cap.read()
    return CameraMode(
        mode.requested_width, mode.requested_height, mode.requested_fps,
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        mode.measured_fps,
    )


def select_camera_mode(cap, resolutions, fps_options, minimum_fps=30.0, probe_frames=12):
    modes = probe_camera_modes(cap, resolutions, fps_options, probe_frames=probe_frames)
    if not modes:
        print(t("camera_no_modes"))
        return None

    recommended = recommend_mode(modes, minimum_fps=minimum_fps)
    # Pixel count is deliberately primary in display ordering.
    modes = sorted(modes, key=lambda m: (m.pixels, m.measured_fps, m.requested_fps), reverse=True)

    print(t("camera_modes"))
    for i, mode in enumerate(modes, 1):
        label = _resolution_label(mode.width, mode.height)
        rec = f"  ← {t('camera_recommended')}" if mode == recommended else ""
        label_text = f" {label}" if label else ""
        print(
            f" [{i}] {mode.width}x{mode.height}{label_text} | "
            f"request {mode.requested_fps:g} Hz | ~{mode.measured_fps:.1f} FPS{rec}"
        )
    print(t("camera_auto"))

    while True:
        choice = input(t("camera_choose", n=len(modes))).strip().lower()
        if choice in ("", "a", "auto"):
            selected = recommended
            break
        try:
            idx = int(choice) - 1
        except ValueError:
            print(t("camera_invalid"))
            continue
        if 0 <= idx < len(modes):
            selected = modes[idx]
            break
        print(t("camera_invalid"))

    selected = apply_camera_mode(cap, selected)
    print(t("camera_selected", w=selected.width, h=selected.height, fps=selected.measured_fps))
    return selected


# Backwards-compatible wrapper used by older code.
def autodetect_camera_settings(cap, resolutions, requested_fps=120, probe_frames=10,
                               target_fps=30, fps_safety_margin=1.2):
    mode = select_camera_mode(
        cap, resolutions, [requested_fps, 60, 30],
        minimum_fps=target_fps, probe_frames=probe_frames,
    )
    return mode.measured_fps if mode is not None else 0.0


class CameraWorker(threading.Thread):
    """Continuously captures frames. Queue semantics are latest-frame-wins."""

    def __init__(self, cap, out_queue: queue.Queue, stop_event: threading.Event,
                 stats: RuntimeStats, video_recorder=None):
        super().__init__(name="CameraWorker", daemon=True)
        self.cap = cap
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.stats = stats
        self.video_recorder = video_recorder
        self.frame_id = 0

    def run(self):
        while not self.stop_event.is_set():
            ret, frame = self.cap.read()
            if not ret:
                self.stop_event.set()
                break
            ts = local_clock()
            self.frame_id += 1
            packet = FramePacket(self.frame_id, ts, frame)
            self.stats.camera_frames += 1
            self.stats.last_camera_timestamp = ts

            if self.video_recorder is not None:
                self.video_recorder.submit(packet)

            try:
                self.out_queue.put_nowait(packet)
            except queue.Full:
                try:
                    self.out_queue.get_nowait()
                    self.stats.dropped_camera_frames += 1
                except queue.Empty:
                    pass
                try:
                    self.out_queue.put_nowait(packet)
                except queue.Full:
                    self.stats.dropped_camera_frames += 1
