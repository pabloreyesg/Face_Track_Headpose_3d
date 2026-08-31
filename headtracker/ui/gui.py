from __future__ import annotations

import queue
import sys
import threading
import subprocess
import tempfile
import json
from pathlib import Path
import time
from dataclasses import dataclass

import cv2
import numpy as np
from pylsl import StreamInlet, resolve_streams
from PySide6.QtCore import QThread, QTimer, Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..acquisition.calibration import calibrate
from ..acquisition.camera import CameraMode, apply_camera_mode, probe_camera_modes, recommend_mode, CameraWorker
from ..core.config import load_config
from ..core.i18n import set_language
from ..io.logger import AsyncSessionLogger
from ..io.lsl import (
    MarkerBuffer,
    MarkerReceiver,
    LSLIntegrityState,
    LSLWatchdog,
    create_outlet,
    get_time_correction,
    stream_info_to_dict,
)
from ..core.models import RuntimeStats
from ..core.session import create_session_dir, write_metadata
from ..acquisition.tracking import FaceLandmarkerTracker, TrackingProcessor, ensure_model
from ..io.video import SyncedVideoRecorder
from ..acquisition.worker import TrackingWorker


GUI_TEXT = {
    "es": {
        "language_title": "Idioma / Language",
        "language_prompt": "Seleccione el idioma de la interfaz:",
        "spanish": "Español",
        "english": "English",
        "window_title": "HeadTracker — adquisición de laboratorio",
        "setup": "Preparación",
        "experiment": "Experimento / prefijo",
        "distance": "Distancia cara-cámara",
        "cm": "cm",
        "camera": "Cámara",
        "detect_modes": "Detectar modos",
        "detecting_modes": "Detectando resoluciones y FPS reales…",
        "camera_mode": "Modo de cámara",
        "recommended": "RECOMENDADO",
        "camera_help": "La recomendación prioriza la mayor resolución viable. Puede seleccionar cualquier otro modo detectado.",
        "no_modes": "No se han detectado modos todavía.",
        "calibration": "Calibración",
        "calibrate": "Calibrar",
        "calibration_pending": "Pendiente",
        "calibration_ok": "Completada — calidad OK",
        "calibration_low": "Completada — calidad marginal",
        "calibration_running": "Calibrando… use la ventana de targets.",
        "lsl": "LSL / markers",
        "search_lsl": "Buscar streams",
        "search_again": "Volver a buscar",
        "searching": "Buscando streams LSL… {remaining} s",
        "lsl_none": "No se encontraron streams en 40 s.",
        "continue_no_lsl": "Continuar sin LSL",
        "select_stream": "Seleccione un stream de markers:",
        "connect": "Usar stream seleccionado",
        "lsl_connected": "CONECTADO",
        "lsl_disabled": "SIN LSL",
        "lsl_warning": "No se grabarán markers/triggers. Los resultados pueden no ser interpretables temporalmente respecto a estímulos, respuestas u otros eventos experimentales.",
        "source_id_warning": "El stream no tiene source_id estable; la recuperación automática será limitada.",
        "video": "Video",
        "video_checkbox": "Grabar video sincronizado",
        "video_help_off": "OFF por defecto. El preview no se guarda.",
        "video_help_need_lsl": "El video solo se habilita con un stream LSL seleccionado.",
        "acquisition": "Adquisición",
        "start": "INICIAR ADQUISICIÓN",
        "stop": "DETENER",
        "ready": "Listo para iniciar",
        "not_ready": "Complete detección de cámara y calibración.",
        "preview": "Preview",
        "no_preview": "Sin adquisición activa",
        "face": "Cara",
        "camera_fps": "Cámara",
        "tracking_fps": "Tracking",
        "processing": "Procesamiento",
        "dropped": "Frames descartados",
        "markers": "Markers",
        "lsl_state": "LSL",
        "video_state": "Video",
        "privacy": "PRIVACY MODE — no se persisten frames",
        "video_sync": "VIDEO SYNC — MP4 + timestamps",
        "session": "Sesión",
        "session_started": "Adquisición iniciada.",
        "session_stopped": "Adquisición finalizada.",
        "confirm_no_lsl_title": "Continuar sin LSL",
        "confirm_no_lsl": "No hay un stream LSL seleccionado.\n\nNo se grabarán markers/triggers y los resultados pueden no ser interpretables temporalmente respecto a eventos experimentales.\n\n¿Desea iniciar de todos modos?",
        "error": "Error",
        "camera_error": "No se pudo abrir la cámara.",
        "model_error": "No se pudo cargar el modelo MediaPipe.",
        "select_camera_first": "Primero detecte y seleccione un modo de cámara.",
        "calibrate_first": "Debe completar la calibración antes de iniciar.",
        "prefix_required": "Ingrese un nombre/prefijo para el experimento.",
        "lsl_lost": "PERDIDO / RECUPERANDO",
        "close_running": "Hay una adquisición en curso. Deténgala antes de cerrar la aplicación.",
    },
    "en": {
        "language_title": "Language / Idioma",
        "language_prompt": "Select the interface language:",
        "spanish": "Español",
        "english": "English",
        "window_title": "HeadTracker — laboratory acquisition",
        "setup": "Preparation",
        "experiment": "Experiment / prefix",
        "distance": "Face-to-camera distance",
        "cm": "cm",
        "camera": "Camera",
        "detect_modes": "Detect modes",
        "detecting_modes": "Detecting actual resolutions and FPS…",
        "camera_mode": "Camera mode",
        "recommended": "RECOMMENDED",
        "camera_help": "The recommendation prioritizes the highest viable resolution. You may select any other detected mode.",
        "no_modes": "No modes have been detected yet.",
        "calibration": "Calibration",
        "calibrate": "Calibrate",
        "calibration_pending": "Pending",
        "calibration_ok": "Completed — quality OK",
        "calibration_low": "Completed — marginal quality",
        "calibration_running": "Calibrating… use the target window.",
        "lsl": "LSL / markers",
        "search_lsl": "Search streams",
        "search_again": "Search again",
        "searching": "Searching LSL streams… {remaining} s",
        "lsl_none": "No streams found in 40 s.",
        "continue_no_lsl": "Continue without LSL",
        "select_stream": "Select a marker stream:",
        "connect": "Use selected stream",
        "lsl_connected": "CONNECTED",
        "lsl_disabled": "NO LSL",
        "lsl_warning": "Markers/triggers will not be recorded. Results may not be temporally interpretable relative to stimuli, responses, or other experimental events.",
        "source_id_warning": "The stream has no stable source_id; automatic recovery will be limited.",
        "video": "Video",
        "video_checkbox": "Record synchronized video",
        "video_help_off": "OFF by default. Preview is not saved.",
        "video_help_need_lsl": "Video is only enabled with a selected LSL stream.",
        "acquisition": "Acquisition",
        "start": "START ACQUISITION",
        "stop": "STOP",
        "ready": "Ready to start",
        "not_ready": "Complete camera detection and calibration.",
        "preview": "Preview",
        "no_preview": "No active acquisition",
        "face": "Face",
        "camera_fps": "Camera",
        "tracking_fps": "Tracking",
        "processing": "Processing",
        "dropped": "Dropped frames",
        "markers": "Markers",
        "lsl_state": "LSL",
        "video_state": "Video",
        "privacy": "PRIVACY MODE — frames are not persisted",
        "video_sync": "VIDEO SYNC — MP4 + timestamps",
        "session": "Session",
        "session_started": "Acquisition started.",
        "session_stopped": "Acquisition finished.",
        "confirm_no_lsl_title": "Continue without LSL",
        "confirm_no_lsl": "No LSL stream is selected.\n\nMarkers/triggers will not be recorded and results may not be temporally interpretable relative to experimental events.\n\nStart anyway?",
        "error": "Error",
        "camera_error": "Could not open the camera.",
        "model_error": "Could not load the MediaPipe model.",
        "select_camera_first": "Detect and select a camera mode first.",
        "calibrate_first": "Calibration must be completed before starting.",
        "prefix_required": "Enter an experiment name/prefix.",
        "lsl_lost": "LOST / RECOVERING",
        "close_running": "An acquisition is running. Stop it before closing the application.",
    },
}


def choose_gui_language() -> str | None:
    dialog = QDialog()
    dialog.setWindowTitle("Idioma / Language")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Seleccione idioma / Select language:"))
    combo = QComboBox()
    combo.addItem("Español", "es")
    combo.addItem("English", "en")
    layout.addWidget(combo)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.Accepted:
        return None
    return str(combo.currentData())


def _mode_label(mode: CameraMode, recommended: CameraMode | None, lang: str) -> str:
    tags = []
    if mode.width >= 3800 and mode.height >= 2100:
        tags.append("4K/UHD")
    elif mode.width >= 2500 and mode.height >= 1400:
        tags.append("2K/QHD")
    elif mode.width >= 1900 and mode.height >= 1000:
        tags.append("Full HD")
    elif mode.width >= 1200 and mode.height >= 700:
        tags.append("HD")
    if recommended is not None and mode == recommended:
        tags.append(GUI_TEXT[lang]["recommended"])
    suffix = f"  [{' · '.join(tags)}]" if tags else ""
    return (
        f"{mode.width}×{mode.height} | ~{mode.measured_fps:.1f} FPS "
        f"(request {mode.requested_fps:g} Hz){suffix}"
    )


class CameraProbeThread(QThread):
    finished_modes = Signal(object, object)
    failed = Signal(str)

    def __init__(self, camera_index, resolutions, fps_options, probe_frames, minimum_fps):
        super().__init__()
        self.camera_index = int(camera_index)
        self.resolutions = list(resolutions)
        self.fps_options = list(fps_options)
        self.probe_frames = int(probe_frames)
        self.minimum_fps = float(minimum_fps)

    def run(self):
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.failed.emit("camera")
            return
        try:
            modes = probe_camera_modes(
                cap,
                self.resolutions,
                self.fps_options,
                probe_frames=self.probe_frames,
            )
            recommended = recommend_mode(modes, minimum_fps=self.minimum_fps)
            modes = sorted(
                modes,
                key=lambda m: (m.pixels, m.measured_fps, m.requested_fps),
                reverse=True,
            )
            self.finished_modes.emit(modes, recommended)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            cap.release()


class CalibrationThread(QThread):
    """Run OpenCV HighGUI calibration in a separate Python process.

    OpenCV wheels on Linux bundle their own Qt runtime/plugins. Running cv2.imshow()
    in the same process as PySide6 can cause Qt thread/timer and font-path conflicts.
    The subprocess keeps OpenCV HighGUI isolated from the application's Qt event loop.
    """
    finished_calibration = Signal(object, float, bool)
    failed = Signal(str)

    def __init__(self, cfg, mode: CameraMode, known_distance_cm: float):
        super().__init__()
        self.cfg = cfg
        self.mode = mode
        self.known_distance_cm = float(known_distance_cm)
        self._proc = None

    def run(self):
        try:
            with tempfile.TemporaryDirectory(prefix="headtracker_cal_") as tmp:
                tmp = Path(tmp)
                config_path = tmp / "config.json"
                result_path = tmp / "result.json"
                self.cfg.save(config_path)
                if getattr(sys, "frozen", False):
                    # Frozen (PyInstaller) build: no separate Python interpreter
                    # to target with `-m`, so relaunch this same exe in worker mode.
                    args = [sys.executable, "--calibration-worker"]
                else:
                    args = [sys.executable, "-m", "headtracker.tools.calibration_worker"]
                args += [
                    "--config", str(config_path),
                    "--result", str(result_path),
                    "--language", str(self.cfg.language),
                    "--camera-index", str(self.cfg.camera.index),
                    "--requested-width", str(self.mode.requested_width),
                    "--requested-height", str(self.mode.requested_height),
                    "--requested-fps", str(self.mode.requested_fps),
                    "--width", str(self.mode.width),
                    "--height", str(self.mode.height),
                    "--measured-fps", str(self.mode.measured_fps),
                    "--distance-cm", str(self.known_distance_cm),
                ]
                self._proc = subprocess.Popen(args)
                code = self._proc.wait()
                self._proc = None
                # The worker writes result.json (with an "error" field) on every
                # failure path before returning its exit code, so prefer that
                # specific message over the bare exit code whenever it's there.
                data = None
                if result_path.exists():
                    try:
                        data = json.loads(result_path.read_text(encoding="utf-8"))
                    except Exception:
                        data = None
                if data is None:
                    if code != 0:
                        self.failed.emit(f"calibration process exited with code {code}")
                    else:
                        self.failed.emit("calibration result missing")
                    return
                if not data.get("ok", False):
                    self.failed.emit(str(data.get("error", "calibration")))
                    return
                offset = np.array(data["offset"], dtype=float)
                self.finished_calibration.emit(
                    offset, float(data["focal_length_px"]), bool(data["quality_ok"])
                )
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self):
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass


class LSLSearchThread(QThread):
    countdown = Signal(int)
    found = Signal(object)
    failed = Signal(str)

    def __init__(self, timeout_s=40):
        super().__init__()
        self.timeout_s = max(1, int(round(timeout_s)))
        self._stop = threading.Event()

    def cancel(self):
        self._stop.set()

    def run(self):
        deadline = time.monotonic() + self.timeout_s
        last_remaining = None
        try:
            while not self._stop.is_set():
                remaining = max(0, int(deadline - time.monotonic() + 0.999))
                if remaining != last_remaining:
                    self.countdown.emit(remaining)
                    last_remaining = remaining
                if remaining <= 0:
                    self.found.emit([])
                    return
                wait_time = min(0.5, max(0.05, deadline - time.monotonic()))
                try:
                    streams = resolve_streams(wait_time=wait_time)
                except TypeError:
                    streams = resolve_streams()
                if streams:
                    self.found.emit(streams)
                    return
                time.sleep(0.05)
        except Exception as exc:
            self.failed.emit(str(exc))


@dataclass
class CalibrationData:
    offset: np.ndarray
    focal_length_px: float
    quality_ok: bool
    known_distance_cm: float


class AcquisitionRuntime:
    def __init__(self, cfg, sessions_dir, prefix, mode, calibration: CalibrationData,
                 marker_inlet, marker_stream_info, video_requested):
        self.cfg = cfg
        self.sessions_dir = sessions_dir
        self.prefix = prefix
        self.mode = mode
        self.calibration = calibration
        self.marker_inlet = marker_inlet
        self.marker_stream_info = marker_stream_info
        self.video_requested = bool(video_requested)

        self.stop_event = threading.Event()
        self.stats = RuntimeStats()
        self.cap = None
        self.tracker = None
        self.logger = None
        self.marker_receiver = None
        self.watchdog = None
        self.video_recorder = None
        self.camera_worker = None
        self.tracking_worker = None
        self.preview_queue = queue.Queue(maxsize=1)
        self.frame_queue = queue.Queue(maxsize=2)
        self.marker_buffer = MarkerBuffer()
        self.marker_correction = 0.0
        self.lsl_integrity = None
        self.session_dir = None
        self.video_enabled = False
        self.measured_fps = float(mode.measured_fps)
        self._started_monotonic = None
        self._last_stats_time = None
        self._last_camera_frames = 0
        self._last_processed_frames = 0
        self.camera_fps_runtime = 0.0
        self.tracking_fps_runtime = 0.0

    def start(self):
        self.session_dir = create_session_dir(self.sessions_dir, self.prefix)
        self.cfg.save(self.session_dir / "config.json")

        self.cap = cv2.VideoCapture(self.cfg.camera.index)
        if not self.cap.isOpened():
            raise RuntimeError("camera")
        self.mode = apply_camera_mode(self.cap, self.mode)

        model_path = ensure_model(self.cfg.tracking.model_path, self.cfg.tracking.model_url)
        if model_path is None:
            raise RuntimeError("model")
        self.tracker = FaceLandmarkerTracker(model_path)

        self.marker_correction = get_time_correction(self.marker_inlet)
        enabled = self.marker_inlet is not None
        self.lsl_integrity = LSLIntegrityState(enabled, self.marker_stream_info)

        self.video_enabled = bool(self.video_requested and enabled)
        self.logger = AsyncSessionLogger(self.session_dir, self.cfg, self.stop_event)
        self.logger.start()

        if enabled:
            self.marker_receiver = MarkerReceiver(
                self.marker_inlet,
                self.marker_correction,
                self.marker_buffer,
                self.logger,
                self.stop_event,
                self.stats,
                integrity=self.lsl_integrity,
            )
            self.marker_receiver.start()
            if self.cfg.lsl.watchdog_enabled:
                self.watchdog = LSLWatchdog(
                    self.marker_stream_info,
                    self.lsl_integrity,
                    self.logger,
                    self.stop_event,
                    check_interval_s=self.cfg.lsl.watchdog_check_interval_s,
                    resolve_timeout_s=self.cfg.lsl.watchdog_resolve_timeout_s,
                    lost_after_misses=self.cfg.lsl.watchdog_lost_after_misses,
                )
                self.watchdog.start()

        if self.video_enabled:
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = self.measured_fps if self.measured_fps > 0 else self.cfg.camera.target_process_fps
            self.video_recorder = SyncedVideoRecorder(
                self.session_dir,
                width,
                height,
                fps,
                self.cfg.video.codec,
                self.cfg.video.queue_size,
                self.stop_event,
                self.stats,
            )
            self.video_recorder.start()

        outlet = create_outlet(self.cfg.lsl)
        processor = TrackingProcessor(
            self.tracker,
            float(self.calibration.offset[0]),
            float(self.calibration.offset[1]),
            float(self.calibration.offset[2]),
            self.calibration.focal_length_px,
            self.cfg.tracking.smoothing_alpha,
            self.cfg.calibration.known_eye_distance_mm,
            self.cfg.display.draw_landmarks,
        )
        self.camera_worker = CameraWorker(
            self.cap, self.frame_queue, self.stop_event, self.stats, self.video_recorder
        )
        self.tracking_worker = TrackingWorker(
            self.frame_queue,
            self.preview_queue,
            processor,
            self.marker_buffer,
            self.logger,
            outlet,
            self.stop_event,
            self.stats,
            lsl_integrity=self.lsl_integrity,
        )

        write_metadata(
            self.session_dir / "session.json",
            prefix=self.prefix,
            config=self.cfg,
            cap=self.cap,
            measured_fps=self.measured_fps,
            calibration_offset=self.calibration.offset,
            focal_length_px=self.calibration.focal_length_px,
            known_distance_cm=self.calibration.known_distance_cm,
            marker_stream_info=self.marker_stream_info,
            marker_time_correction=self.marker_correction,
            calibration_quality_ok=self.calibration.quality_ok,
            video_enabled=self.video_enabled,
            lsl_integrity=self.lsl_integrity,
            selected_camera_mode=self.mode,
        )

        self.camera_worker.start()
        self.tracking_worker.start()
        self._started_monotonic = time.monotonic()
        self._last_stats_time = self._started_monotonic

    def poll_preview(self):
        latest = None
        while True:
            try:
                latest = self.preview_queue.get_nowait()
                self.preview_queue.task_done()
            except queue.Empty:
                break
        return latest

    def update_rates(self):
        now = time.monotonic()
        if self._last_stats_time is None:
            self._last_stats_time = now
            return
        dt = now - self._last_stats_time
        if dt < 0.5:
            return
        dc = self.stats.camera_frames - self._last_camera_frames
        dp = self.stats.processed_frames - self._last_processed_frames
        self.camera_fps_runtime = dc / dt
        self.tracking_fps_runtime = dp / dt
        self._last_camera_frames = self.stats.camera_frames
        self._last_processed_frames = self.stats.processed_frames
        self._last_stats_time = now

    def stop(self):
        if self.stop_event.is_set() and self.cap is None:
            return
        self.stop_event.set()
        for worker, timeout in (
            (self.camera_worker, 2),
            (self.tracking_worker, 3),
            (self.marker_receiver, 2),
            (self.watchdog, 2),
            (self.video_recorder, 3),
        ):
            if worker is not None:
                worker.join(timeout=timeout)
        if self.video_recorder is not None:
            self.video_recorder.close()
        if self.logger is not None:
            self.logger.join(timeout=5)
            self.logger.close()
        if self.tracker is not None:
            self.tracker.close()

        if self.marker_inlet is not None:
            try:
                self.marker_inlet.close_stream()
            except Exception:
                pass

        if self.cap is not None and self.session_dir is not None:
            write_metadata(
                self.session_dir / "session.json",
                prefix=self.prefix,
                config=self.cfg,
                cap=self.cap,
                measured_fps=self.measured_fps,
                calibration_offset=self.calibration.offset,
                focal_length_px=self.calibration.focal_length_px,
                known_distance_cm=self.calibration.known_distance_cm,
                marker_stream_info=self.marker_stream_info,
                marker_time_correction=self.marker_correction,
                calibration_quality_ok=self.calibration.quality_ok,
                video_enabled=self.video_enabled,
                lsl_integrity=self.lsl_integrity,
                stats=self.stats,
                selected_camera_mode=self.mode,
            )
            self.cap.release()
            self.cap = None


class HeadTrackerWindow(QMainWindow):
    def __init__(self, config_path=None, sessions_dir="sessions", language="es"):
        super().__init__()
        self.language = "en" if language == "en" else "es"
        set_language(self.language)
        self.txt = GUI_TEXT[self.language]
        self.cfg = load_config(config_path)
        self.cfg.language = self.language
        self.sessions_dir = sessions_dir

        self.camera_modes = []
        self.recommended_mode = None
        self.calibration_data = None
        self.camera_probe_thread = None
        self.calibration_thread = None
        self.lsl_search_thread = None
        self.lsl_streams = []
        self.marker_inlet = None
        self.marker_stream_info = None
        self.runtime = None
        self.last_preview_result = None

        self.setWindowTitle(self.txt["window_title"])
        self.setMinimumSize(900, 650)
        self._build_ui()
        self._apply_lab_style()
        self._update_ready_state()

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(100)
        self.ui_timer.timeout.connect(self._update_runtime_ui)
        self.ui_timer.start()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        setup_panel = QWidget()
        setup_layout = QVBoxLayout(setup_panel)
        setup_layout.setContentsMargins(0, 0, 8, 0)
        setup_layout.setSpacing(10)
        splitter.addWidget(setup_panel)

        acquisition_panel = QWidget()
        acquisition_layout = QVBoxLayout(acquisition_panel)
        acquisition_layout.setContentsMargins(8, 0, 0, 0)
        acquisition_layout.setSpacing(10)
        splitter.addWidget(acquisition_panel)
        splitter.setSizes([430, 650])

        general = QGroupBox(self.txt["setup"])
        form = QFormLayout(general)
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("session")
        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(20.0, 300.0)
        self.distance_spin.setValue(60.0)
        self.distance_spin.setSuffix(f" {self.txt['cm']}")
        self.distance_spin.setDecimals(1)
        self.distance_spin.valueChanged.connect(self._distance_changed)
        form.addRow(self.txt["experiment"], self.prefix_edit)
        form.addRow(self.txt["distance"], self.distance_spin)
        setup_layout.addWidget(general)

        camera_group = QGroupBox(self.txt["camera"])
        camera_layout = QVBoxLayout(camera_group)
        cam_actions = QHBoxLayout()
        self.detect_camera_btn = QPushButton(self.txt["detect_modes"])
        self.detect_camera_btn.clicked.connect(self._detect_camera_modes)
        self.camera_progress = QProgressBar()
        self.camera_progress.setRange(0, 0)
        self.camera_progress.hide()
        cam_actions.addWidget(self.detect_camera_btn)
        cam_actions.addWidget(self.camera_progress, 1)
        camera_layout.addLayout(cam_actions)
        self.camera_combo = QComboBox()
        self.camera_combo.setEnabled(False)
        self.camera_combo.currentIndexChanged.connect(self._camera_mode_changed)
        camera_layout.addWidget(self.camera_combo)
        self.camera_status = QLabel(self.txt["no_modes"])
        self.camera_status.setWordWrap(True)
        camera_layout.addWidget(self.camera_status)
        camera_layout.addWidget(self._muted_label(self.txt["camera_help"]))
        setup_layout.addWidget(camera_group)

        calibration_group = QGroupBox(self.txt["calibration"])
        calibration_layout = QHBoxLayout(calibration_group)
        self.calibrate_btn = QPushButton(self.txt["calibrate"])
        self.calibrate_btn.clicked.connect(self._start_calibration)
        self.calibrate_btn.setEnabled(False)
        self.calibration_status = QLabel(self.txt["calibration_pending"])
        calibration_layout.addWidget(self.calibrate_btn)
        calibration_layout.addWidget(self.calibration_status, 1)
        setup_layout.addWidget(calibration_group)

        lsl_group = QGroupBox(self.txt["lsl"])
        lsl_layout = QVBoxLayout(lsl_group)
        lsl_actions = QHBoxLayout()
        self.search_lsl_btn = QPushButton(self.txt["search_lsl"])
        self.search_lsl_btn.clicked.connect(self._search_lsl)
        self.no_lsl_btn = QPushButton(self.txt["continue_no_lsl"])
        self.no_lsl_btn.clicked.connect(self._use_no_lsl)
        lsl_actions.addWidget(self.search_lsl_btn)
        lsl_actions.addWidget(self.no_lsl_btn)
        lsl_layout.addLayout(lsl_actions)
        self.lsl_countdown_label = QLabel("")
        lsl_layout.addWidget(self.lsl_countdown_label)
        self.lsl_list = QListWidget()
        self.lsl_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lsl_list.setMaximumHeight(130)
        lsl_layout.addWidget(self.lsl_list)
        self.use_lsl_btn = QPushButton(self.txt["connect"])
        self.use_lsl_btn.clicked.connect(self._use_selected_lsl)
        self.use_lsl_btn.setEnabled(False)
        lsl_layout.addWidget(self.use_lsl_btn)
        self.lsl_status = QLabel(self.txt["lsl_disabled"])
        self.lsl_status.setWordWrap(True)
        lsl_layout.addWidget(self.lsl_status)
        setup_layout.addWidget(lsl_group)

        video_group = QGroupBox(self.txt["video"])
        video_layout = QVBoxLayout(video_group)
        self.video_check = QCheckBox(self.txt["video_checkbox"])
        self.video_check.setEnabled(False)
        video_layout.addWidget(self.video_check)
        self.video_help = self._muted_label(
            self.txt["video_help_off"] + " " + self.txt["video_help_need_lsl"]
        )
        self.video_help.setWordWrap(True)
        video_layout.addWidget(self.video_help)
        setup_layout.addWidget(video_group)
        setup_layout.addStretch(1)

        acquisition_group = QGroupBox(self.txt["acquisition"])
        acquisition_box = QVBoxLayout(acquisition_group)

        self.preview_label = QLabel(self.txt["no_preview"])
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(520, 390)
        self.preview_label.setFrameShape(QFrame.Box)
        self.preview_label.setStyleSheet("background:#101010;color:#b8b8b8;")
        acquisition_box.addWidget(self.preview_label, 1)

        metrics = QGridLayout()
        self.metric_labels = {}
        metric_keys = [
            ("face", self.txt["face"]),
            ("camera_fps", self.txt["camera_fps"]),
            ("tracking_fps", self.txt["tracking_fps"]),
            ("processing", self.txt["processing"]),
            ("dropped", self.txt["dropped"]),
            ("markers", self.txt["markers"]),
            ("lsl", self.txt["lsl_state"]),
            ("video", self.txt["video_state"]),
        ]
        for i, (key, title) in enumerate(metric_keys):
            r = i // 2
            c = (i % 2) * 2
            metrics.addWidget(QLabel(f"{title}:"), r, c)
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            metrics.addWidget(value, r, c + 1)
            self.metric_labels[key] = value
        acquisition_box.addLayout(metrics)

        self.mode_banner = QLabel(self.txt["privacy"])
        self.mode_banner.setAlignment(Qt.AlignCenter)
        self.mode_banner.setStyleSheet("font-weight:600;padding:6px;border:1px solid #888;")
        acquisition_box.addWidget(self.mode_banner)

        controls = QHBoxLayout()
        self.start_btn = QPushButton(self.txt["start"])
        self.start_btn.clicked.connect(self._start_acquisition)
        self.stop_btn = QPushButton(self.txt["stop"])
        self.stop_btn.clicked.connect(self._stop_acquisition)
        self.stop_btn.setEnabled(False)
        controls.addWidget(self.start_btn, 2)
        controls.addWidget(self.stop_btn, 1)
        acquisition_box.addLayout(controls)

        self.ready_label = QLabel(self.txt["not_ready"])
        self.ready_label.setWordWrap(True)
        acquisition_box.addWidget(self.ready_label)
        acquisition_layout.addWidget(acquisition_group, 1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(self.txt["ready"])

    def _apply_lab_style(self):
        self.setStyleSheet(
            "QGroupBox { font-weight: 600; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
            "QPushButton { min-height: 30px; padding: 3px 10px; }"
            "QComboBox, QLineEdit, QDoubleSpinBox { min-height: 28px; }"
            "QListWidget { min-height: 80px; }"
        )

    @staticmethod
    def _muted_label(text):
        label = QLabel(text)
        label.setStyleSheet("color:#707070;")
        return label

    def _selected_mode(self):
        data = self.camera_combo.currentData()
        return data if isinstance(data, CameraMode) else None

    def _set_setup_enabled(self, enabled: bool):
        for widget in (
            self.prefix_edit,
            self.distance_spin,
            self.detect_camera_btn,
            self.camera_combo,
            self.calibrate_btn,
            self.search_lsl_btn,
            self.no_lsl_btn,
            self.lsl_list,
            self.use_lsl_btn,
            self.video_check,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self.camera_combo.setEnabled(bool(self.camera_modes))
            self.calibrate_btn.setEnabled(self._selected_mode() is not None)
            self.use_lsl_btn.setEnabled(bool(self.lsl_streams))
            self.video_check.setEnabled(self.marker_inlet is not None)

    def _detect_camera_modes(self):
        if self.camera_probe_thread is not None and self.camera_probe_thread.isRunning():
            return
        self.detect_camera_btn.setEnabled(False)
        self.camera_progress.show()
        self.camera_status.setText(self.txt["detecting_modes"])
        self.camera_combo.clear()
        self.camera_combo.setEnabled(False)
        self.calibration_data = None
        self.calibration_status.setText(self.txt["calibration_pending"])
        self.camera_probe_thread = CameraProbeThread(
            self.cfg.camera.index,
            self.cfg.camera.resolutions,
            self.cfg.camera.fps_options,
            self.cfg.camera.mode_probe_frames,
            self.cfg.camera.target_process_fps,
        )
        self.camera_probe_thread.finished_modes.connect(self._camera_modes_ready)
        self.camera_probe_thread.failed.connect(self._camera_probe_failed)
        self.camera_probe_thread.start()

    def _camera_modes_ready(self, modes, recommended):
        self.camera_progress.hide()
        self.detect_camera_btn.setEnabled(True)
        self.camera_modes = list(modes)
        self.recommended_mode = recommended
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        recommended_index = 0
        for i, mode in enumerate(self.camera_modes):
            self.camera_combo.addItem(_mode_label(mode, recommended, self.language), mode)
            if recommended is not None and mode == recommended:
                recommended_index = i
        self.camera_combo.setCurrentIndex(recommended_index)
        self.camera_combo.blockSignals(False)
        self.camera_combo.setEnabled(bool(self.camera_modes))
        if self.camera_modes:
            self.camera_status.setText(_mode_label(self.camera_combo.currentData(), recommended, self.language))
            self.calibrate_btn.setEnabled(True)
        else:
            self.camera_status.setText(self.txt["no_modes"])
        self._update_ready_state()

    def _camera_probe_failed(self, error):
        self.camera_progress.hide()
        self.detect_camera_btn.setEnabled(True)
        msg = self.txt["camera_error"] if error == "camera" else str(error)
        QMessageBox.critical(self, self.txt["error"], msg)

    def _distance_changed(self):
        # Distance participates in focal-length calibration; changing it invalidates
        # the previous calibration rather than silently reusing stale geometry.
        if self.calibration_data is not None:
            self.calibration_data = None
            self.calibration_status.setText(self.txt["calibration_pending"])
            self._update_ready_state()

    def _camera_mode_changed(self):
        mode = self._selected_mode()
        if mode is not None:
            self.camera_status.setText(_mode_label(mode, self.recommended_mode, self.language))
        self.calibration_data = None
        self.calibration_status.setText(self.txt["calibration_pending"])
        self._update_ready_state()

    def _start_calibration(self):
        mode = self._selected_mode()
        if mode is None:
            QMessageBox.warning(self, self.txt["error"], self.txt["select_camera_first"])
            return
        if self.calibration_thread is not None and self.calibration_thread.isRunning():
            return
        self.calibrate_btn.setEnabled(False)
        self.detect_camera_btn.setEnabled(False)
        self.camera_combo.setEnabled(False)
        self.calibration_status.setText(self.txt["calibration_running"])
        self.calibration_thread = CalibrationThread(self.cfg, mode, self.distance_spin.value())
        self.calibration_thread.finished_calibration.connect(self._calibration_ready)
        self.calibration_thread.failed.connect(self._calibration_failed)
        self.calibration_thread.start()

    def _calibration_ready(self, offset, focal_length_px, quality_ok):
        self.calibration_data = CalibrationData(
            offset=np.array(offset, dtype=float),
            focal_length_px=float(focal_length_px),
            quality_ok=bool(quality_ok),
            known_distance_cm=float(self.distance_spin.value()),
        )
        self.calibration_status.setText(
            self.txt["calibration_ok"] if quality_ok else self.txt["calibration_low"]
        )
        self.calibrate_btn.setEnabled(True)
        self.detect_camera_btn.setEnabled(True)
        self.camera_combo.setEnabled(True)
        self._update_ready_state()

    def _calibration_failed(self, error):
        self.calibration_status.setText(self.txt["calibration_pending"])
        self.calibrate_btn.setEnabled(True)
        self.detect_camera_btn.setEnabled(True)
        self.camera_combo.setEnabled(True)
        if error == "camera":
            msg = self.txt["camera_error"]
        elif error == "model":
            msg = self.txt["model_error"]
        else:
            msg = str(error)
        QMessageBox.critical(self, self.txt["error"], msg)
        self._update_ready_state()

    def _search_lsl(self):
        if self.lsl_search_thread is not None and self.lsl_search_thread.isRunning():
            return
        self.search_lsl_btn.setEnabled(False)
        self.use_lsl_btn.setEnabled(False)
        self.lsl_list.clear()
        self.lsl_streams = []
        self.lsl_search_thread = LSLSearchThread(self.cfg.lsl.stream_search_timeout_s)
        self.lsl_search_thread.countdown.connect(self._lsl_countdown)
        self.lsl_search_thread.found.connect(self._lsl_search_finished)
        self.lsl_search_thread.failed.connect(self._lsl_search_failed)
        self.lsl_search_thread.start()

    def _lsl_countdown(self, remaining):
        self.lsl_countdown_label.setText(self.txt["searching"].format(remaining=remaining))

    def _lsl_search_finished(self, streams):
        self.search_lsl_btn.setEnabled(True)
        self.search_lsl_btn.setText(self.txt["search_again"])
        self.lsl_countdown_label.setText("")
        self.lsl_streams = list(streams)
        self.lsl_list.clear()
        if not self.lsl_streams:
            self.lsl_status.setText(self.txt["lsl_none"] + " " + self.txt["lsl_warning"])
            self.use_lsl_btn.setEnabled(False)
            return
        for stream in self.lsl_streams:
            sid = stream.source_id() or "—"
            item = QListWidgetItem(
                f"{stream.name()} | {stream.type()} | {stream.channel_count()} ch | "
                f"{stream.nominal_srate():g} Hz | source_id={sid}"
            )
            self.lsl_list.addItem(item)
        self.lsl_list.setCurrentRow(0)
        self.use_lsl_btn.setEnabled(True)
        self.lsl_status.setText(self.txt["select_stream"])

    def _lsl_search_failed(self, error):
        self.search_lsl_btn.setEnabled(True)
        self.lsl_countdown_label.setText("")
        QMessageBox.critical(self, self.txt["error"], str(error))

    def _close_marker_inlet(self):
        if self.marker_inlet is not None:
            try:
                self.marker_inlet.close_stream()
            except Exception:
                pass
        self.marker_inlet = None
        self.marker_stream_info = None

    def _use_selected_lsl(self):
        row = self.lsl_list.currentRow()
        if row < 0 or row >= len(self.lsl_streams):
            return
        selected = self.lsl_streams[row]
        self._close_marker_inlet()
        try:
            try:
                self.marker_inlet = StreamInlet(selected, recover=True)
            except TypeError:
                self.marker_inlet = StreamInlet(selected)
            self.marker_stream_info = stream_info_to_dict(selected)
        except Exception as exc:
            QMessageBox.critical(self, self.txt["error"], str(exc))
            self._close_marker_inlet()
            return
        sid = self.marker_stream_info.get("source_id") or "—"
        text = f"{self.txt['lsl_connected']}: {self.marker_stream_info['name']} | source_id={sid}"
        if not self.marker_stream_info.get("source_id"):
            text += "\n⚠ " + self.txt["source_id_warning"]
        self.lsl_status.setText(text)
        self.video_check.setEnabled(True)
        self._update_ready_state()

    def _use_no_lsl(self):
        self._close_marker_inlet()
        self.video_check.setChecked(False)
        self.video_check.setEnabled(False)
        self.lsl_status.setText("⚠ " + self.txt["lsl_disabled"] + " — " + self.txt["lsl_warning"])
        self._update_ready_state()

    def _update_ready_state(self):
        ready = self._selected_mode() is not None and self.calibration_data is not None
        self.start_btn.setEnabled(ready and self.runtime is None)
        self.ready_label.setText(self.txt["ready"] if ready else self.txt["not_ready"])

    def _start_acquisition(self):
        if self.runtime is not None:
            return
        prefix = self.prefix_edit.text().strip()
        if not prefix:
            QMessageBox.warning(self, self.txt["error"], self.txt["prefix_required"])
            return
        mode = self._selected_mode()
        if mode is None:
            QMessageBox.warning(self, self.txt["error"], self.txt["select_camera_first"])
            return
        if self.calibration_data is None:
            QMessageBox.warning(self, self.txt["error"], self.txt["calibrate_first"])
            return
        if self.marker_inlet is None:
            answer = QMessageBox.warning(
                self,
                self.txt["confirm_no_lsl_title"],
                self.txt["confirm_no_lsl"],
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self.cfg.video.enabled = bool(self.video_check.isChecked())
        self.cfg.language = self.language
        runtime = AcquisitionRuntime(
            self.cfg,
            self.sessions_dir,
            prefix,
            mode,
            self.calibration_data,
            self.marker_inlet,
            self.marker_stream_info,
            self.video_check.isChecked(),
        )
        try:
            runtime.start()
        except Exception as exc:
            try:
                runtime.stop()
            except Exception:
                pass
            msg = self.txt["camera_error"] if str(exc) == "camera" else (
                self.txt["model_error"] if str(exc) == "model" else str(exc)
            )
            QMessageBox.critical(self, self.txt["error"], msg)
            return

        self.runtime = runtime
        self._set_setup_enabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.mode_banner.setText(self.txt["video_sync"] if runtime.video_enabled else self.txt["privacy"])
        self.statusBar().showMessage(f"{self.txt['session_started']} {runtime.session_dir}")
        self.ready_label.setText(f"{self.txt['session']}: {runtime.session_dir}")

    def _stop_acquisition(self):
        if self.runtime is None:
            return
        runtime = self.runtime
        self.stop_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            runtime.stop()
        finally:
            QApplication.restoreOverrideCursor()
        self.runtime = None
        self.marker_inlet = None  # runtime owned/used the inlet; require explicit reconnect for next session
        self.marker_stream_info = None
        self.video_check.setChecked(False)
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(self.txt["no_preview"])
        self.mode_banner.setText(self.txt["privacy"])
        self._set_setup_enabled(True)
        self.video_check.setEnabled(False)
        self.lsl_status.setText(self.txt["lsl_disabled"])
        self.statusBar().showMessage(f"{self.txt['session_stopped']} {runtime.session_dir}")
        self._clear_metrics()
        self._update_ready_state()

    def _clear_metrics(self):
        for label in self.metric_labels.values():
            label.setText("—")

    def _update_runtime_ui(self):
        runtime = self.runtime
        if runtime is None:
            return
        if runtime.stop_event.is_set():
            # A camera/read failure can stop workers without a button press.
            self._stop_acquisition()
            return

        result = runtime.poll_preview()
        if result is not None:
            self.last_preview_result = result
            frame = result.preview_frame
            if frame is not None:
                self._show_frame(frame)
            self.metric_labels["face"].setText("✓" if result.face_detected else "—")

        runtime.update_rates()
        self.metric_labels["camera_fps"].setText(f"{runtime.camera_fps_runtime:.1f} FPS")
        self.metric_labels["tracking_fps"].setText(f"{runtime.tracking_fps_runtime:.1f} FPS")
        self.metric_labels["processing"].setText(f"{runtime.stats.last_processing_ms:.1f} ms")
        self.metric_labels["dropped"].setText(str(runtime.stats.dropped_camera_frames))
        self.metric_labels["markers"].setText(str(runtime.stats.marker_count))
        snap = runtime.lsl_integrity.snapshot() if runtime.lsl_integrity else {"state": "DISABLED", "lsl_available": False}
        state = str(snap["state"])
        self.metric_labels["lsl"].setText(state)
        if state in ("LOST", "RECOVERING"):
            self.metric_labels["lsl"].setStyleSheet("font-weight:700;color:#b00020;")
        elif snap.get("lsl_available"):
            self.metric_labels["lsl"].setStyleSheet("font-weight:700;color:#1b6e1b;")
        else:
            self.metric_labels["lsl"].setStyleSheet("")
        self.metric_labels["video"].setText("SYNC" if runtime.video_enabled else "OFF")

    def _show_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.last_preview_result is not None and self.runtime is not None:
            frame = self.last_preview_result.preview_frame
            if frame is not None:
                self._show_frame(frame)

    def closeEvent(self, event):
        if self.runtime is not None:
            QMessageBox.warning(self, self.txt["error"], self.txt["close_running"])
            event.ignore()
            return
        if self.lsl_search_thread is not None and self.lsl_search_thread.isRunning():
            self.lsl_search_thread.cancel()
            self.lsl_search_thread.wait(1000)
        if self.calibration_thread is not None and self.calibration_thread.isRunning():
            self.calibration_thread.cancel()
            self.calibration_thread.wait(2000)
        if self.camera_probe_thread is not None and self.camera_probe_thread.isRunning():
            self.camera_probe_thread.wait(2000)
        self._close_marker_inlet()
        event.accept()
