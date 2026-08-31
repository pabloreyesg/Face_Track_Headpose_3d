# === Verificación de dependencias ===
import importlib
import importlib.util
import sys

required_modules = {
    'cv2': 'opencv-python',
    'mediapipe': 'mediapipe',
    'pandas': 'pandas',
    'pyarrow': 'pyarrow',
    'pylsl': 'pylsl',
    'numpy': 'numpy'
}

missing = [pkg for mod, pkg in required_modules.items() if importlib.util.find_spec(mod) is None]
if missing:
    print("🚫 Faltan librerías necesarias:")
    print(f"pip install {' '.join(missing)}")
    sys.exit(1)

# === Librerías ===
import os
import sys
import contextlib
import cv2
import json
import time
import datetime
import urllib.request
from collections import deque
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import mediapipe as mp
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_streams, local_clock


@contextlib.contextmanager
def suppress_native_stderr():
    """Silencia temporalmente los logs nativos de mediapipe (C++, vía glog/absl:
    inicialización de GPU/XNNPACK, y el intento de telemetría 'clearcut' de Google al
    cerrar el FaceLandmarker). GLOG_minloglevel no sirve acá porque este build no lo
    respeta (probado); esto redirige el file descriptor 2 (stderr) a nivel de sistema
    operativo, que sí captura esos prints nativos sin importar qué libería de logging
    usen internamente. Pensado para lab cerrado, donde no interesa ver esa telemetría
    fallida ni el ruido de inicialización. No afecta a las excepciones de Python: se
    restaura el stderr real antes de que termine el bloque, así que un traceback
    generado dentro sigue imprimiéndose normalmente después."""
    stderr_fd = sys.stderr.fileno()
    saved_fd = os.dup(stderr_fd)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, stderr_fd)
        yield
    finally:
        os.dup2(saved_fd, stderr_fd)
        os.close(devnull)
        os.close(saved_fd)

# === Configuración inicial ===
prefix = input("📂 Nombre del experimento o prefijo de archivo: ").strip() or "session"
TARGET_PROCESS_FPS = 30  # FPS objetivo de análisis/registro; el frame-skip se ajusta según el FPS real detectado en la cámara
CHUNK_SIZE = 150  # ~10s a 15 FPS: registros acumulados en RAM antes de volcarlos a disco

# Modelo del FaceLandmarker (Tasks API). mediapipe eliminó por completo la legacy
# Solutions API (mp.solutions.*); ya no hay forma de hacer face mesh sin este modelo,
# así que ahora es obligatorio (antes era opcional, solo para blendshapes).
FACE_LANDMARKER_MODEL_PATH = "face_landmarker.task"
FACE_LANDMARKER_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/"
                              "face_landmarker/face_landmarker/float16/latest/face_landmarker.task")

# Parámetros del stream LSL de salida (se reusan también en la metadata de sesión)
LSL_OUTLET_NAME = "HeadTracking"
LSL_OUTLET_TYPE = "HeadPose"
LSL_OUTLET_CHANNELS = 4
LSL_OUTLET_SRATE = 30
LSL_OUTLET_SOURCE_ID = "myuid34234"

# Calibración multi-punto (estilo eye-tracker): centro + 4 direcciones, como fracción
# (x, y) del frame donde se dibuja cada target.
CALIBRATION_TARGETS = [
    ("CENTRO", 0.5, 0.5),
    ("IZQUIERDA", 0.12, 0.5),
    ("DERECHA", 0.88, 0.5),
    ("ARRIBA", 0.5, 0.12),
    ("ABAJO", 0.5, 0.88),
]
CALIB_SMOOTHING_ALPHA = 0.5    # EMA sobre yaw/pitch antes de medir estabilidad (baja el jitter de solvePnP)
CALIB_STABILITY_WINDOW = 10    # muestras (ya suavizadas) que deben mantenerse quietas para aceptar un punto
CALIB_STABILITY_STD_DEG = 2.0  # desviación estándar máxima (°) en yaw/pitch para considerar "estable"
CALIB_POINT_TIMEOUT = 6.0      # segundos máximos de espera por punto antes de aceptar lo que haya
CALIB_MIN_RANGE_DEG = 6.0      # rango mínimo esperado entre extremos opuestos para validar la calibración

mp_drawing_utils = mp.tasks.vision.drawing_utils
mp_face_contours = mp.tasks.vision.FaceLandmarksConnections.FACE_LANDMARKS_CONTOURS

class ChunkedParquetLogger:
    """Acumula registros (dicts) en memoria y los vuelca a disco como row-group de
    parquet cada `chunk_size` registros, en vez de esperar al cierre del programa.
    Mantiene el uso de RAM acotado en sesiones largas y deja datos ya escritos en
    disco si el proceso termina de forma abrupta.

    El esquema se fija (tipos explícitos, no inferidos) en el primer flush: un chunk
    con una columna 100% None infiere tipo `null` en pyarrow, que luego no se puede
    castear a un tipo real en chunks posteriores. `dtype_overrides` evita ese problema
    para columnas de tipo ambiguo (p.ej. un marker LSL que puede llegar como None)."""

    def __init__(self, path, chunk_size=CHUNK_SIZE, dtype_overrides=None):
        self.path = path
        self.chunk_size = chunk_size
        self.buffer = []
        self.writer = None
        self.columns = None
        self.schema = None
        self.dtype_overrides = dtype_overrides or {}
        self.total_rows = 0

    def add(self, row):
        self.buffer.append(row)
        if len(self.buffer) >= self.chunk_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        df = pd.DataFrame(self.buffer)
        if self.columns is None:
            self.columns = list(df.columns)
            fields = [pa.field(c, self.dtype_overrides.get(c, pa.float64())) for c in self.columns]
            self.schema = pa.schema(fields)
        else:
            df = df.reindex(columns=self.columns)

        table = pa.Table.from_pandas(df, schema=self.schema, preserve_index=False)
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.path, self.schema)
        self.writer.write_table(table)

        self.total_rows += len(self.buffer)
        self.buffer = []

    def close(self):
        self.flush()
        if self.writer is not None:
            self.writer.close()

def crop_to_square(frame):
    """Recorta a cuadrado y espeja horizontalmente (vista 'selfie'). La cámara entrega
    la imagen cruda, sin espejar (como una cámara de seguridad): sin este flip, mover
    la cabeza hacia la izquierda real la mueve hacia la derecha en pantalla, lo cual es
    confuso al mirar los targets de calibración IZQUIERDA/DERECHA. Se espeja acá, antes
    de cualquier detección o dibujo, para que todo el pipeline (landmarks, yaw/distance,
    overlay, logging) sea consistente con lo que el usuario ve en pantalla."""
    h, w = frame.shape[:2]
    min_dim = min(h, w)
    top = (h - min_dim) // 2
    left = (w - min_dim) // 2
    square = frame[top:top + min_dim, left:left + min_dim]
    return cv2.flip(square, 1)

def get_head_orientation(landmarks, width, height):
    indices = [33, 263, 1, 61, 291, 199]
    image_points = np.array([
        [landmarks[i].x * width, landmarks[i].y * height] for i in indices
    ], dtype="double")

    model_points = np.array([
        [-30.0, 0.0, -30.0],
        [30.0, 0.0, -30.0],
        [0.0, 0.0, 0.0],
        [-25.0, -30.0, -20.0],
        [25.0, -30.0, -20.0],
        [0.0, -60.0, -10.0]
    ])

    focal_length = width
    center = (width / 2, height / 2)
    camera_matrix = np.array([
        [focal_length, 0, center[0]],
        [0, focal_length, center[1]],
        [0, 0, 1]
    ], dtype="double")

    dist_coeffs = np.zeros((4, 1))
    
    try:
        success, rotation_vector, _ = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE
        )
        
        if not success:
            return 0.0, 0.0, 0.0

        rmat, _ = cv2.Rodrigues(rotation_vector)
        sy = np.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)

        x = np.arctan2(rmat[2, 1], rmat[2, 2])
        y = np.arctan2(-rmat[2, 0], sy)
        z = np.arctan2(rmat[1, 0], rmat[0, 0])

        pitch = np.degrees(x)
        yaw = np.degrees(y)
        roll = np.degrees(z)

        return yaw, pitch, roll
    except:
        return 0.0, 0.0, 0.0

KNOWN_EYE_DISTANCE_MM = 63.0  # separación interpupilar promedio adulta
# Focal length de referencia SOLO para el caso en que la calibración de distancia
# falle (no se detectó cara en el punto CENTRO). Es un valor arbitrario que no
# corresponde a ninguna resolución de cámara real: si se usa, la distancia va a
# estar mal escalada. La calibración real (ver calibrate_distance_focal_length)
# la reemplaza por un valor medido con la resolución y cámara actuales.
FALLBACK_FOCAL_LENGTH_PX = 850.0


def get_eye_distance_px(landmarks, width, height):
    left_eye = np.array([landmarks[33].x * width, landmarks[33].y * height])
    right_eye = np.array([landmarks[263].x * width, landmarks[263].y * height])
    return np.linalg.norm(left_eye - right_eye)


def get_distance(landmarks, width, height, focal_length_px):
    """Distancia cámara-cara por triangulación monocular (fórmula pinhole):
    distancia_mm = (ancho_real_mm * focal_length_px) / ancho_aparente_px.
    `focal_length_px` tiene que estar calibrado para la resolución de captura
    actual (ver calibrate_distance_focal_length) — un valor fijo sin calibrar
    da resultados completamente errados si la resolución cambia entre sesiones."""
    eye_distance_px = get_eye_distance_px(landmarks, width, height)
    if eye_distance_px == 0:
        return 0.0
    return (KNOWN_EYE_DISTANCE_MM * focal_length_px) / eye_distance_px

def smooth_value(prev, current, alpha=0.9):
    return alpha * prev + (1 - alpha) * current

def initialize_lsl_stream():
    info = StreamInfo(LSL_OUTLET_NAME, LSL_OUTLET_TYPE, LSL_OUTLET_CHANNELS,
                       LSL_OUTLET_SRATE, 'float32', LSL_OUTLET_SOURCE_ID)
    outlet = StreamOutlet(info)
    return outlet

def ensure_face_landmarker_model(model_path=FACE_LANDMARKER_MODEL_PATH):
    """Descarga el modelo .task de Google si no está presente localmente.
    Devuelve la ruta al modelo, o None si no se pudo obtener."""
    if os.path.exists(model_path):
        return model_path

    print(f"⬇️ Modelo '{model_path}' no encontrado. Descargando desde Google...")
    try:
        urllib.request.urlretrieve(FACE_LANDMARKER_MODEL_URL, model_path)
        print(f"✅ Modelo descargado en '{model_path}'.")
        return model_path
    except Exception as e:
        print(f"❌ No se pudo descargar el modelo automáticamente: {e}")
        print(f"   Descárgalo manualmente desde: {FACE_LANDMARKER_MODEL_URL}")
        print(f"   y colocalo en '{model_path}'.")
        return None


class FaceLandmarkerTracker:
    """Envuelve FaceLandmarker (Tasks API, modo VIDEO) con un reloj monotónico propio
    para generar los timestamps en ms que exige `detect_for_video`. Reemplaza a la
    legacy Solutions API (mp.solutions.face_mesh), que mediapipe eliminó por completo:
    ya no existe `mp.solutions` en ninguna versión publicada, así que el face mesh
    (478 landmarks, incluyendo iris) y los blendshapes se obtienen ahora del mismo
    FaceLandmarker en una sola pasada."""

    def __init__(self, model_path):
        base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=False,
        )
        with suppress_native_stderr():
            self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        self._start = time.monotonic()
        self._last_ts_ms = -1

    def detect(self, rgb_frame):
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        ts_ms = int((time.monotonic() - self._start) * 1000)
        if ts_ms <= self._last_ts_ms:
            ts_ms = self._last_ts_ms + 1
        self._last_ts_ms = ts_ms
        return self._landmarker.detect_for_video(mp_image, ts_ms)

    def close(self):
        with suppress_native_stderr():
            self._landmarker.close()

def list_available_lsl_streams(max_wait_seconds=60):
    """Lista todos los streams LSL disponibles"""
    print("🔍 Buscando streams LSL disponibles...")
    start_time = time.time()
    
    while (time.time() - start_time) < max_wait_seconds:
        streams = resolve_streams()
        if streams:
            print(f"\n📡 Se encontraron {len(streams)} stream(s) disponible(s):")
            for i, stream in enumerate(streams):
                print(f"  [{i+1}] Nombre: '{stream.name()}' | Tipo: '{stream.type()}' | "
                      f"Canales: {stream.channel_count()} | Frecuencia: {stream.nominal_srate()}Hz | "
                      f"ID: '{stream.source_id()}'")
            return streams
        
        print("⏳ Esperando streams... (1 segundo)")
        time.sleep(1)
    
    print("⚠️ No se encontraron streams LSL disponibles.")
    return []

def select_lsl_stream():
    """Permite al usuario seleccionar un stream LSL o continuar sin él"""
    streams = list_available_lsl_streams()
    
    if not streams:
        print("\n❌ No hay streams disponibles.")
        choice = input("¿Desea continuar sin captura de markers? (y/n): ").lower().strip()
        if choice == 'y':
            return None
        else:
            print("Cerrando programa...")
            sys.exit(1)
    
    print(f"\n🎯 Opciones:")
    for i, stream in enumerate(streams):
        print(f"  [{i+1}] Seleccionar '{stream.name()}' ({stream.type()})")
    print(f"  [0] Continuar sin captura de markers")
    
    while True:
        try:
            choice = input(f"\nSeleccione una opción (0-{len(streams)}): ").strip()
            choice_num = int(choice)
            
            if choice_num == 0:
                print("▶️ Continuando sin captura de markers...")
                return None
            elif 1 <= choice_num <= len(streams):
                selected_stream = streams[choice_num - 1]
                print(f"✅ Stream seleccionado: '{selected_stream.name()}' ({selected_stream.type()})")
                try:
                    inlet = StreamInlet(selected_stream)
                    return inlet
                except Exception as e:
                    print(f"❌ Error al conectar con el stream: {e}")
                    return None
            else:
                print(f"❌ Opción inválida. Ingrese un número entre 0 y {len(streams)}")
                
        except ValueError:
            print("❌ Por favor ingrese un número válido")
        except KeyboardInterrupt:
            print("\n👋 Operación cancelada por el usuario")
            sys.exit(1)

def initialize_trigger_listener():
    """Inicializa el listener de triggers con selección de stream"""
    print("🎯 Configuración de captura de markers LSL")
    print("=" * 50)
    
    trigger_inlet = select_lsl_stream()
    
    if trigger_inlet:
        # Obtener información del stream seleccionado
        info = trigger_inlet.info()
        print(f"📊 Stream conectado:")
        print(f"   • Nombre: {info.name()}")
        print(f"   • Tipo: {info.type()}")
        print(f"   • Canales: {info.channel_count()}")
        print(f"   • Frecuencia: {info.nominal_srate()}Hz")
        print(f"   • ID: {info.source_id()}")
    else:
        print("⚠️ Funcionando sin captura de markers")
    
    print("=" * 50)
    return trigger_inlet

def get_trigger_time_correction(trigger_inlet, timeout=1.0):
    """El timestamp que devuelve `pull_sample` está en el reloj LSL del equipo que
    emite el marker, no en el de esta máquina. `time_correction()` da el offset para
    llevarlo al dominio de nuestro propio `local_clock()` y así poder comparar el
    instante real del marker contra el `Timestamp` de cada fila. Si el marker viene
    del mismo proceso/máquina el offset es ~0; si viene de otro equipo, es necesario."""
    if trigger_inlet is None:
        return 0.0
    try:
        return trigger_inlet.time_correction(timeout=timeout)
    except Exception as e:
        print(f"⚠️ No se pudo calcular la corrección de reloj LSL ({e}); se usará offset 0.0.")
        return 0.0

def autodetect_camera_settings(cap, resolutions=None, requested_fps=120, probe_frames=10,
                                target_fps=TARGET_PROCESS_FPS, fps_safety_margin=1.2):
    """Prueba resoluciones soportadas por la cámara y mide el FPS real entregado en
    cada una (no el que reporta el driver, que a veces no es fiable). En vez de elegir
    la de mayor FPS crudo (lo que puede terminar prefiriendo una resolución menor por
    una diferencia de décimas de frame, sin ningún beneficio real), prefiere la MAYOR
    resolución entre las que sostienen `target_fps` con margen (`fps_safety_margin`):
    una vez que el fps real supera el target de procesamiento, el frame-skip de
    main() (save_every_n) descarta igual el excedente, así que ganar fps de sobra no
    aporta nada, solo se pierde resolución/calidad de imagen sin necesidad."""
    if resolutions is None:
        resolutions = [(1920, 1080), (1280, 720), (960, 540), (640, 480)]

    # MJPG comprime en la propia cámara, lo que suele destrabar mayor FPS a resoluciones
    # altas en webcams USB limitadas por ancho de banda (vs. el YUYV crudo por defecto).
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    print(f"🔍 Buscando la mayor resolución que sostenga ~{target_fps * fps_safety_margin:.0f} fps reales...")
    results = []  # [(measured_fps, width, height), ...]

    for width, height in resolutions:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, requested_fps)

        for _ in range(2):  # frames de estabilización tras el cambio de modo
            cap.read()

        start_time = time.time()
        grabbed = 0
        for _ in range(probe_frames):
            ret, _ = cap.read()
            if ret:
                grabbed += 1
        elapsed = time.time() - start_time

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        measured_fps = grabbed / elapsed if elapsed > 0 else 0.0

        print(f"   • {actual_w}x{actual_h}: {measured_fps:.1f} fps reales")
        results.append((measured_fps, actual_w, actual_h))

    if not results or max(r[0] for r in results) <= 0:
        print("⚠️ No se pudo medir el framerate de la cámara; se usa la configuración por defecto.")
        return 0.0

    viable = [r for r in results if r[0] >= target_fps * fps_safety_margin]
    if viable:
        measured_fps, width, height = max(viable, key=lambda r: r[1] * r[2])
    else:
        measured_fps, width, height = max(results, key=lambda r: r[0])
        print(f"⚠️ Ninguna resolución sostiene {target_fps * fps_safety_margin:.0f} fps con margen; "
              "se usa la de mayor fps real medido.")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, requested_fps)
    print(f"✅ Configuración elegida: {width}x{height} (~{measured_fps:.1f} fps reales)")
    return measured_fps

def _capture_calibration_point(tracker, cap, window_name, label, tx, ty):
    """Muestra un target en (tx, ty) [fracción 0-1 del frame] y espera a que la
    orientación de cabeza se mantenga estable antes de aceptar el punto, en vez de
    promediar a ciegas como antes. La estabilidad se mide sobre una versión suavizada
    (EMA) de yaw/pitch, no sobre el valor crudo por-frame: solvePnP con solo 6 puntos
    es ruidoso (2-5° de jitter cuadro a cuadro incluso quieto), así que medir std()
    sobre el crudo casi nunca converge y el punto siempre termina cayendo al timeout.
    SPACE fuerza la aceptación con lo que haya; 'q'/ESC cancela toda la calibración.

    Devuelve (yaw, pitch, roll, eye_distance_px) promedio del tramo estable (o None
    si nunca detectó cara), y un flag `cancelled`. `eye_distance_px` viaja junto a la
    orientación para poder calibrar también la distancia en el punto CENTRO, sin
    agregar un paso extra: ver calibrate_distance_focal_length."""
    buffer = deque(maxlen=CALIB_STABILITY_WINDOW)
    smoothed = None
    start_time = time.time()

    while time.time() - start_time < CALIB_POINT_TIMEOUT:
        ret, frame = cap.read()
        if not ret:
            continue

        frame = crop_to_square(frame)
        h, w = frame.shape[:2]
        result = tracker.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        stable = False
        face_found = bool(result.face_landmarks)
        if face_found:
            landmarks = result.face_landmarks[0]
            raw = np.array([*get_head_orientation(landmarks, w, h),
                             get_eye_distance_px(landmarks, w, h)])
            smoothed = raw if smoothed is None else CALIB_SMOOTHING_ALPHA * smoothed + (1 - CALIB_SMOOTHING_ALPHA) * raw
            buffer.append(tuple(smoothed))

            if len(buffer) == buffer.maxlen:
                std = np.std(buffer, axis=0)
                stable = std[0] < CALIB_STABILITY_STD_DEG and std[1] < CALIB_STABILITY_STD_DEG

        # Target: amarillo mientras se estabiliza, verde cuando ya es válido
        cx, cy = int(tx * w), int(ty * h)
        color = (0, 255, 0) if stable else (0, 255, 255)
        cv2.circle(frame, (cx, cy), 18, color, 3)
        cv2.circle(frame, (cx, cy), 3, color, -1)

        remaining = max(0, int(CALIB_POINT_TIMEOUT - (time.time() - start_time)))
        cv2.putText(frame, f"Mire hacia: {label} ({remaining}s)", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        if not face_found:
            cv2.putText(frame, "No se detecta cara...", (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(frame, "SPACE: forzar   'q'/ESC: cancelar", (20, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.imshow(window_name, frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            return None, True
        if key == ord(' ') and buffer:
            print(f"   {label}: aceptado manualmente (SPACE).")
            break
        if stable:
            print(f"   {label}: ✅ estabilizado en {time.time() - start_time:.1f}s.")
            break
    else:
        if buffer:
            print(f"   {label}: ⏱️ no se estabilizó a tiempo, se usa el promedio de los últimos {len(buffer)} cuadros.")
        else:
            print(f"   {label}: ⚠️ no se detectó cara en {CALIB_POINT_TIMEOUT:.0f}s.")

    if buffer:
        return tuple(np.mean(buffer, axis=0)), False
    return None, False


def _show_calibration_summary(cap, window_name, offset, corrected, lr_ok, lr_range, ud_ok, ud_range):
    """Pantalla de validación (como el 'accuracy check' de un eye-tracker): muestra el
    valor medido en cada punto ya corregido por el offset central, y si el rango de
    movimiento detectado Izq/Der y Arriba/Abajo es suficiente. Deja aceptar, recalibrar
    o cancelar antes de seguir."""
    quality_ok = lr_ok and ud_ok

    print("\n📋 Resultado de calibración:")
    for label, v in corrected.items():
        if v is None:
            print(f"   {label:12s}: sin datos")
        else:
            print(f"   {label:12s}: Yaw={v[0]:+.1f}°  Pitch={v[1]:+.1f}°  Roll={v[2]:+.1f}°")
    print(f"   Rango horizontal (Izquierda/Derecha): {lr_range:.1f}° {'✅' if lr_ok else '⚠️ bajo'}")
    print(f"   Rango vertical (Arriba/Abajo): {ud_range:.1f}° {'✅' if ud_ok else '⚠️ bajo'}")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        frame = crop_to_square(frame)
        h, w = frame.shape[:2]

        y = 30
        cv2.putText(frame, "Resultado de calibracion:", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        y += 30
        for label, v in corrected.items():
            text = f"{label}: sin datos" if v is None else f"{label}: Yaw={v[0]:+.1f} Pitch={v[1]:+.1f}"
            cv2.putText(frame, text, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
            y += 22

        status_color = (0, 255, 0) if quality_ok else (0, 165, 255)
        status_text = "Calidad OK" if quality_ok else "Calidad marginal: rango de movimiento bajo"
        cv2.putText(frame, status_text, (20, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)
        cv2.putText(frame, "ENTER: aceptar   R: recalibrar   ESC: cancelar", (20, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
        cv2.imshow(window_name, frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (13, 10):
            return 'accept'
        if key in (ord('r'), ord('R')):
            return 'retry'
        if key == 27:
            return 'cancel'


def calibrate_orientation(tracker, cap, known_distance_mm):
    """Calibración multi-punto estilo eye-tracker: 5 targets (centro + 4 direcciones)
    en vez de un único promedio ciego de 5 segundos. El punto CENTRO define el offset
    (yaw/pitch/roll para 'mirar al frente' = 0); los otros 4 solo validan que el
    sistema responde con suficiente rango en cada dirección, y no ajustan el offset
    (a diferencia de un eye-tracker de gaze-a-pantalla, la orientación de cabeza vía
    solvePnP ya es geométricamente consistente: el error dominante es un sesgo
    aproximadamente constante por el modelo 3D genérico de cara, no una distorsión
    dependiente de la posición que requiera una regresión por punto).

    El mismo punto CENTRO también calibra la distancia: usa la separación de ojos en
    píxeles medida ahí, junto con `known_distance_mm` (la distancia real que el
    usuario reportó al arrancar), para derivar el focal_length_px de esta cámara y
    resolución. Sin esto, get_distance() usaba una constante fija sin relación con la
    resolución real, dando distancias muy erradas apenas la cámara no coincidía con
    la que se usó para inventar esa constante.

    Devuelve (offset, focal_length_px)."""
    window_name = "Calibración"
    print("🧭 Calibración estilo eye-tracker: mire cada marca cuando aparezca en pantalla.")
    print("   Haga click en la ventana de calibración para que las teclas (SPACE/ENTER/R/ESC) respondan.")

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)

    while True:  # permite recalibrar con 'r' en la pantalla de resumen
        points = {}
        cancelled = False
        for label, tx, ty in CALIBRATION_TARGETS:
            sample, cancelled = _capture_calibration_point(tracker, cap, window_name, label, tx, ty)
            points[label] = sample
            if cancelled:
                break

        if cancelled:
            cv2.destroyWindow(window_name)
            print("⚠️ Calibración cancelada. Usando offset cero y focal_length_px por defecto (impreciso).")
            return np.array([0.0, 0.0, 0.0]), FALLBACK_FOCAL_LENGTH_PX

        if points.get("CENTRO") is None:
            print("⚠️ No se detectó cara en el punto central. Reintentando calibración...")
            continue

        offset = np.array(points["CENTRO"][:3])
        eye_distance_px_centro = points["CENTRO"][3]
        corrected = {label: (np.array(v[:3]) - offset if v is not None else None)
                     for label, v in points.items()}

        def _range(a, b, axis):
            if a is None or b is None:
                return False, 0.0
            delta = abs(a[axis] - b[axis])
            return delta > CALIB_MIN_RANGE_DEG, delta

        lr_ok, lr_range = _range(corrected.get("IZQUIERDA"), corrected.get("DERECHA"), 0)
        ud_ok, ud_range = _range(corrected.get("ARRIBA"), corrected.get("ABAJO"), 1)

        decision = _show_calibration_summary(cap, window_name, offset, corrected, lr_ok, lr_range, ud_ok, ud_range)

        if decision == 'accept':
            cv2.destroyWindow(window_name)
            print(f"📏 Offset calibrado: Yaw={offset[0]:.2f}°, Pitch={offset[1]:.2f}°, Roll={offset[2]:.2f}°")
            if eye_distance_px_centro > 0:
                focal_length_px = (eye_distance_px_centro * known_distance_mm) / KNOWN_EYE_DISTANCE_MM
                print(f"📏 Distancia calibrada: {known_distance_mm / 10:.1f}cm reales, "
                      f"separación de ojos {eye_distance_px_centro:.1f}px -> focal_length_px={focal_length_px:.1f}")
            else:
                focal_length_px = FALLBACK_FOCAL_LENGTH_PX
                print("⚠️ Separación de ojos medida = 0px; se usa focal_length_px por defecto (impreciso).")
            return offset, focal_length_px
        if decision == 'cancel':
            cv2.destroyWindow(window_name)
            print("⚠️ Calibración cancelada. Usando offset cero y focal_length_px por defecto (impreciso).")
            return np.array([0.0, 0.0, 0.0]), FALLBACK_FOCAL_LENGTH_PX
        # decision == 'retry': vuelve a recorrer los 5 puntos

def write_session_metadata(path, *, prefix, cap, measured_fps, save_every_n,
                            calibration_offset, trigger_inlet, model_path,
                            known_distance_cm, focal_length_px,
                            trigger_time_correction=0.0):
    """Vuelca a JSON las condiciones de captura de la sesión (resolución/FPS real,
    offset de calibración, si hubo stream de markers y de blendshapes, etc.).
    Sin esto, los .parquet no alcanzan por sí solos para saber en qué condiciones
    se grabó cada sesión ni para comparar sesiones entre sí en el análisis posterior."""
    trigger_stream_info = None
    if trigger_inlet is not None:
        info = trigger_inlet.info()
        trigger_stream_info = {
            "name": info.name(),
            "type": info.type(),
            "channel_count": info.channel_count(),
            "nominal_srate": info.nominal_srate(),
            "source_id": info.source_id(),
            "time_correction": trigger_time_correction,
        }

    metadata = {
        "prefix": prefix,
        "session_start_iso": datetime.datetime.now().isoformat(),
        "local_clock_at_start": local_clock(),
        "camera": {
            "requested_width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "requested_height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "measured_fps": measured_fps,
        },
        "processing": {
            "target_process_fps": TARGET_PROCESS_FPS,
            "save_every_n_frames": save_every_n,
            "effective_fps": (measured_fps / save_every_n) if measured_fps > 0 else None,
            "chunk_size": CHUNK_SIZE,
        },
        "calibration_offset": {
            "yaw": float(calibration_offset[0]),
            "pitch": float(calibration_offset[1]),
            "roll": float(calibration_offset[2]),
        },
        "lsl_outlet": {
            "name": LSL_OUTLET_NAME,
            "type": LSL_OUTLET_TYPE,
            "channels": LSL_OUTLET_CHANNELS,
            "nominal_srate": LSL_OUTLET_SRATE,
            "source_id": LSL_OUTLET_SOURCE_ID,
        },
        "lsl_marker_stream": trigger_stream_info,
        "face_landmarker": {
            "model_path": model_path,
        },
        "distance_calibration": {
            "known_distance_cm": known_distance_cm,
            "focal_length_px": focal_length_px,
            "known_eye_distance_mm": KNOWN_EYE_DISTANCE_MM,
        },
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"✅ Metadata de sesión guardada en '{path}'.")

def main():
    print("🎥 Iniciando sistema de seguimiento de cabeza con LSL")
    print("=" * 60)
    
    # Inicializar cámara
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Error: No se pudo abrir la cámara.")
        return

    # Elegir la resolución/FPS de mayor framerate real que soporte la cámara
    measured_fps = autodetect_camera_settings(cap)
    save_every_n = max(1, round(measured_fps / TARGET_PROCESS_FPS)) if measured_fps > 0 else 2
    print(f"🎞️ Procesando 1 de cada {save_every_n} frames "
          f"(~{(measured_fps / save_every_n) if measured_fps > 0 else 0:.1f} FPS efectivos de análisis)")

    # Inicializar MediaPipe (Tasks API: la legacy mp.solutions.face_mesh fue eliminada
    # por completo) y calibrar. El modelo FaceLandmarker siempre entrega 478 landmarks
    # (incluye iris/labios), equivalente a refine_landmarks=True de la API vieja.
    model_path = ensure_face_landmarker_model()
    if model_path is None:
        print("❌ No se puede continuar sin el modelo FaceLandmarker.")
        cap.release()
        return

    distance_input = input("📏 Para calibrar la distancia: ¿a cuántos cm está su cara "
                           "de la cámara AHORA MISMO? [60]: ").strip()
    try:
        known_distance_cm = float(distance_input) if distance_input else 60.0
    except ValueError:
        print("⚠️ Valor inválido, se usa 60cm por defecto.")
        known_distance_cm = 60.0
    known_distance_mm = known_distance_cm * 10.0

    tracker = FaceLandmarkerTracker(model_path)
    calibration_offset, focal_length_px = calibrate_orientation(tracker, cap, known_distance_mm)
    yaw_offset, pitch_offset, roll_offset = calibration_offset

    # Configurar captura de markers
    trigger_inlet = initialize_trigger_listener()
    trigger_time_correction = get_trigger_time_correction(trigger_inlet)

    # Inicializar LSL outlet
    outlet = initialize_lsl_stream()

    # Trigger puede llegar como str/int/float/None según el stream LSL de markers;
    # se normaliza a string para tener un tipo estable en todos los chunks (ver ChunkedParquetLogger).
    write_session_metadata(
        f"{prefix}_session_metadata.json",
        prefix=prefix, cap=cap, measured_fps=measured_fps, save_every_n=save_every_n,
        calibration_offset=(yaw_offset, pitch_offset, roll_offset),
        trigger_inlet=trigger_inlet, model_path=model_path,
        trigger_time_correction=trigger_time_correction,
        known_distance_cm=known_distance_cm, focal_length_px=focal_length_px,
    )

    trigger_dtype = {"Trigger": pa.string(), "Trigger_Timestamp": pa.float64()}
    data_logger = ChunkedParquetLogger(f"{prefix}_head_tracking_data.parquet", dtype_overrides=trigger_dtype)
    landmarks_logger = ChunkedParquetLogger(f"{prefix}_landmarks_data.parquet", dtype_overrides=trigger_dtype)
    blendshapes_logger = ChunkedParquetLogger(f"{prefix}_blendshapes_data.parquet", dtype_overrides=trigger_dtype)
    prev_yaw = prev_pitch = prev_roll = prev_distance = 0.0
    first_frame = True
    frame_counter = 0

    print("\n🎯 Sistema iniciado correctamente!")
    print("💡 Haga click en la ventana 'Tracking' y presione 'q' o 'ESC' para salir")
    print("   (si escribe 'q' acá en la terminal no va a funcionar: la ventana de video")
    print("   necesita tener el foco). Ctrl+C en esta terminal también cierra todo prolijamente.")
    print("=" * 60)

    cv2.namedWindow("Tracking", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("Tracking", cv2.WND_PROP_TOPMOST, 1)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("❌ Error: No se pudo leer el frame.")
                break

            frame_counter += 1
            # Procesar solo cada save_every_n frames para optimizar rendimiento
            if frame_counter % save_every_n != 0:
                continue

            frame = crop_to_square(frame)
            h, w = frame.shape[:2]
            timestamp = local_clock()
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = tracker.detect(rgb_frame)

            # Capturar marker si hay inlet disponible. Se guarda tanto el valor como el
            # timestamp propio de la señal LSL (corregido a nuestro local_clock()), que
            # es el instante real del evento y no el de este polling por frame.
            trigger_value = None
            trigger_timestamp = None
            if trigger_inlet:
                try:
                    sample, lsl_ts = trigger_inlet.pull_sample(timeout=0.0)
                    if sample:
                        trigger_value = sample[0] if len(sample) > 0 else None
                        trigger_timestamp = lsl_ts + trigger_time_correction
                except Exception as e:
                    print(f"⚠️ Error al leer marker: {e}")

            trigger_str = None if trigger_value is None else str(trigger_value)

            if result.face_landmarks:
                for face_idx, landmarks in enumerate(result.face_landmarks):
                    mp_drawing_utils.draw_landmarks(frame, landmarks, mp_face_contours)

                    # Obtener orientación y aplicar calibración
                    yaw_raw, pitch_raw, roll_raw = get_head_orientation(landmarks, w, h)
                    yaw_raw -= yaw_offset
                    pitch_raw -= pitch_offset
                    roll_raw -= roll_offset

                    distance_raw = get_distance(landmarks, w, h, focal_length_px)

                    # Aplicar suavizado
                    if first_frame:
                        yaw, pitch, roll, distance = yaw_raw, pitch_raw, roll_raw, distance_raw
                        first_frame = False
                    else:
                        yaw = smooth_value(prev_yaw, yaw_raw)
                        pitch = smooth_value(prev_pitch, pitch_raw)
                        roll = smooth_value(prev_roll, roll_raw)
                        distance = smooth_value(prev_distance, distance_raw)

                    prev_yaw, prev_pitch, prev_roll, prev_distance = yaw, pitch, roll, distance

                    # Enviar datos por LSL
                    outlet.push_sample([yaw, pitch, roll, distance])
                    data_logger.add({
                        "Timestamp": timestamp, "Yaw": yaw, "Pitch": pitch,
                        "Roll": roll, "Distance": distance, "Trigger": trigger_str,
                        "Trigger_Timestamp": trigger_timestamp,
                    })

                    # Extraer landmarks de forma más eficiente
                    landmarks_row = {"Timestamp": timestamp, "Trigger": trigger_str,
                                      "Trigger_Timestamp": trigger_timestamp}
                    for i, lm in enumerate(landmarks):
                        landmarks_row[f"L{i}_x"] = lm.x * w
                        landmarks_row[f"L{i}_y"] = lm.y * h
                        landmarks_row[f"L{i}_z"] = lm.z
                    landmarks_logger.add(landmarks_row)

                    # Blendshapes: vienen del mismo FaceLandmarker, alineados por índice de cara
                    if face_idx < len(result.face_blendshapes):
                        row = {"Timestamp": timestamp, "Trigger": trigger_str,
                               "Trigger_Timestamp": trigger_timestamp}
                        for category in result.face_blendshapes[face_idx]:
                            row[category.category_name] = category.score
                        blendshapes_logger.add(row)

                    # Mostrar información en pantalla
                    cv2.putText(frame, f"Yaw: {yaw:.1f}°", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    cv2.putText(frame, f"Pitch: {pitch:.1f}°", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    cv2.putText(frame, f"Roll: {roll:.1f}°", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    cv2.putText(frame, f"Dist: {distance:.0f}mm", (10, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                    
                    # Mostrar información del marker
                    if trigger_inlet:
                        status_text = f"Marker: {trigger_value}" if trigger_value is not None else "Marker: None"
                        cv2.putText(frame, status_text, (10, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    else:
                        cv2.putText(frame, "Marker: Disabled", (10, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (128, 128, 128), 2)

            cv2.putText(frame, "Click aqui + 'q'/ESC para salir", (10, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            cv2.imshow("Tracking", frame)

            if cv2.waitKey(1) & 0xFF in (ord('q'), 27):  # 'q' o ESC
                print("\n👋 Cerrando programa...")
                break

    except KeyboardInterrupt:
        print("\n🛑 Interrupción manual detectada. Cerrando...")

    finally:
        cap.release()
        cv2.destroyAllWindows()

        # Cerrar loggers: vuelca el remanente en buffer y finaliza el archivo parquet
        # (el resto ya se fue escribiendo incrementalmente durante la sesión)
        data_logger.close()
        if data_logger.total_rows:
            print(f"✅ Datos guardados en '{data_logger.path}' ({data_logger.total_rows} registros).")

        landmarks_logger.close()
        if landmarks_logger.total_rows:
            print(f"✅ Landmarks guardados en '{landmarks_logger.path}' ({landmarks_logger.total_rows} registros).")

        blendshapes_logger.close()
        if blendshapes_logger.total_rows:
            print(f"✅ Blendshapes guardados en '{blendshapes_logger.path}' ({blendshapes_logger.total_rows} registros).")

        tracker.close()

        print("🎯 Recursos liberados correctamente.")

if __name__ == "__main__":
    main()