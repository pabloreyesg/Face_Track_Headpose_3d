# === Verificación de dependencias ===
import importlib
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
import cv2
import time
import numpy as np
import pandas as pd
import mediapipe as mp
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_streams

# === Configuración inicial ===
prefix = input("📂 Nombre del experimento o prefijo de archivo: ").strip() or "session"
save_every_n = 2  # ~15 FPS para reducir carga

mp_face_mesh = mp.solutions.face_mesh
mp_drawing = mp.solutions.drawing_utils

def crop_to_square(frame):
    h, w = frame.shape[:2]
    min_dim = min(h, w)
    top = (h - min_dim) // 2
    left = (w - min_dim) // 2
    return frame[top:top + min_dim, left:left + min_dim]

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

def get_distance(landmarks, width, height):
    left_eye = np.array([landmarks[33].x * width, landmarks[33].y * height])
    right_eye = np.array([landmarks[263].x * width, landmarks[263].y * height])
    eye_distance_px = np.linalg.norm(left_eye - right_eye)

    if eye_distance_px == 0:
        return 0.0

    known_eye_distance_mm = 63.0
    focal_length_mm = 850
    distance_mm = (known_eye_distance_mm * focal_length_mm) / eye_distance_px
    return distance_mm

def smooth_value(prev, current, alpha=0.9):
    return alpha * prev + (1 - alpha) * current

def initialize_lsl_stream():
    info = StreamInfo('HeadTracking', 'HeadPose', 4, 30, 'float32', 'myuid34234')
    outlet = StreamOutlet(info)
    return outlet

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

def calibrate_orientation(face_mesh, cap, duration=5):
    """Calibra la orientación de referencia mirando al frente"""
    print(f"🧭 Calibración: mire al frente durante {duration} segundos...")
    values = []
    start_time = time.time()
    
    while time.time() - start_time < duration:
        ret, frame = cap.read()
        if not ret:
            continue
            
        frame = crop_to_square(frame)
        h, w = frame.shape[:2]
        results = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        
        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                yaw, pitch, roll = get_head_orientation(face_landmarks.landmark, w, h)
                values.append([yaw, pitch, roll])
        
        # Mostrar contador visual
        remaining = int(duration - (time.time() - start_time))
        cv2.putText(frame, f"Calibrando: mire al frente... {remaining}s", (30, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imshow("Calibración", frame)
        
        if cv2.waitKey(1) & 0xFF in (ord('q'), 27):
            break
    
    cv2.destroyWindow("Calibración")
    
    if values:
        avg_offset = np.mean(values, axis=0)
        print(f"📏 Offset calibrado: Yaw={avg_offset[0]:.2f}°, Pitch={avg_offset[1]:.2f}°, Roll={avg_offset[2]:.2f}°")
        return avg_offset
    else:
        print("⚠️ Calibración fallida. Usando offset cero.")
        return np.array([0.0, 0.0, 0.0])

def main():
    print("🎥 Iniciando sistema de seguimiento de cabeza con LSL")
    print("=" * 60)
    
    # Inicializar cámara
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Error: No se pudo abrir la cámara.")
        return

    # Inicializar MediaPipe y calibrar
    face_mesh = mp_face_mesh.FaceMesh(static_image_mode=False, max_num_faces=1)
    yaw_offset, pitch_offset, roll_offset = calibrate_orientation(face_mesh, cap, duration=5)
    
    # Configurar captura de markers
    trigger_inlet = initialize_trigger_listener()
    
    # Inicializar LSL outlet
    outlet = initialize_lsl_stream()

    data_log = []
    landmarks_log = []
    prev_yaw = prev_pitch = prev_roll = prev_distance = 0.0
    first_frame = True
    frame_counter = 0

    print("\n🎯 Sistema iniciado correctamente!")
    print("💡 Presione 'q' o 'ESC' para salir")
    print("=" * 60)

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
            results = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

            # Capturar marker si hay inlet disponible
            trigger_value = None
            if trigger_inlet:
                try:
                    sample, _ = trigger_inlet.pull_sample(timeout=0.0)
                    if sample:
                        trigger_value = sample[0] if len(sample) > 0 else None
                except Exception as e:
                    print(f"⚠️ Error al leer marker: {e}")

            if results.multi_face_landmarks:
                for face_landmarks in results.multi_face_landmarks:
                    mp_drawing.draw_landmarks(frame, face_landmarks, mp_face_mesh.FACEMESH_CONTOURS)

                    # Obtener orientación y aplicar calibración
                    yaw_raw, pitch_raw, roll_raw = get_head_orientation(face_landmarks.landmark, w, h)
                    yaw_raw -= yaw_offset
                    pitch_raw -= pitch_offset
                    roll_raw -= roll_offset
                    
                    distance_raw = get_distance(face_landmarks.landmark, w, h)

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
                    timestamp = time.time()

                    # Enviar datos por LSL
                    outlet.push_sample([yaw, pitch, roll, distance])
                    data_log.append([timestamp, yaw, pitch, roll, distance, trigger_value])

                    # Extraer landmarks de forma más eficiente
                    landmarks_flat = [timestamp, trigger_value] + [
                        coord for lm in face_landmarks.landmark 
                        for coord in (lm.x * w, lm.y * h, lm.z)
                    ]
                    landmarks_log.append(landmarks_flat)

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

            cv2.imshow("Tracking", frame)

            if cv2.waitKey(1) & 0xFF in (ord('q'), 27):  # 'q' o ESC
                print("\n👋 Cerrando programa...")
                break

    except KeyboardInterrupt:
        print("\n🛑 Interrupción manual detectada. Cerrando...")

    finally:
        cap.release()
        cv2.destroyAllWindows()

        # Guardar datos en formato Parquet (más eficiente)
        if data_log:
            df_data = pd.DataFrame(data_log, columns=["Timestamp", "Yaw", "Pitch", "Roll", "Distance", "Trigger"])
            parquet_file = f"{prefix}_head_tracking_data.parquet"
            df_data.to_parquet(parquet_file, index=False)
            print(f"✅ Datos guardados en '{parquet_file}' ({len(data_log)} registros).")

        if landmarks_log:
            columns = ["Timestamp", "Trigger"] + [f"L{i}_{axis}" for i in range(468) for axis in ("x", "y", "z")]
            df_landmarks = pd.DataFrame(landmarks_log, columns=columns)
            landmarks_file = f"{prefix}_landmarks_data.parquet"
            df_landmarks.to_parquet(landmarks_file, index=False)
            print(f"✅ Landmarks guardados en '{landmarks_file}' ({len(landmarks_log)} registros).")

        print("🎯 Recursos liberados correctamente.")

if __name__ == "__main__":
    main()