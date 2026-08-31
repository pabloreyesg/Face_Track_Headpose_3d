from __future__ import annotations

_LANGUAGE = "es"

_TRANSLATIONS = {
    "es": {
        "language_prompt": "Seleccione idioma / Select language: [1] Español  [2] English: ",
        "experiment_prefix": "📂 Nombre del experimento/prefijo: ",
        "camera_distance": "📏 Distancia cara-cámara en cm [60]: ",
        "camera_probe_title": "🔍 Detectando modos de cámara (resolución × FPS)...",
        "camera_probe_line": "   • solicitado {rw}x{rh} @ {rfps:g} → real {aw}x{ah} ~{mfps:.1f} FPS",
        "camera_modes": "\n📷 Modos de cámara detectados:",
        "camera_auto": " [A] Automático (recomendado: mayor resolución viable)",
        "camera_choose": "Seleccione modo [A-{n}]: ",
        "camera_invalid": "❌ Opción inválida.",
        "camera_selected": "✅ Cámara seleccionada: {w}x{h} @ ~{fps:.1f} FPS reales",
        "camera_recommended": "RECOMENDADO",
        "camera_no_modes": "⚠️ No fue posible medir modos de cámara; se conserva la configuración actual.",
        "lsl_search": "🔍 Buscando streams LSL... máximo {timeout} segundos.",
        "lsl_countdown": "⏳ Buscando streams LSL... {remaining:02d} s restantes",
        "lsl_found": "✅ Se encontraron {n} stream(s) LSL.",
        "lsl_none": "⚠️ No se encontraron streams LSL durante esta búsqueda.",
        "lsl_retry": " [1] Volver a buscar ({seconds} s)",
        "lsl_continue": " [0] Continuar sin LSL",
        "select_option": "Seleccione una opción: ",
        "invalid_10": "❌ Opción inválida. Ingrese 1 o 0.",
        "streams_available": "\nStreams disponibles:",
        "search_again": " [R] Volver a buscar",
        "select_stream": "Seleccione stream: ",
        "invalid": "❌ Opción inválida.",
        "lsl_selected": "✅ LSL seleccionado: {name} ({type})",
        "no_source_id": "⚠️ El stream no proporciona un source_id estable.",
        "no_source_id_2": "   La adquisición puede continuar, pero la detección/recuperación automática",
        "no_source_id_3": "   de una desconexión será limitada y no se podrá verificar identidad con rigor.",
        "lsl_open_error": "❌ No se pudo abrir el stream seleccionado: {error}",
        "lsl_open_error_2": "   Puede seleccionar otro stream o pulsar R para volver a buscar.",
        "lsl_invalid_range": "❌ Opción inválida. Seleccione 0-{n} o R.",
        "no_lsl_title": "⚠️  CONTINUANDO SIN LSL",
        "no_lsl_1": "⚠️  No se grabarán markers/triggers de sincronización.",
        "no_lsl_2": "⚠️  Los resultados pueden no ser interpretables temporalmente respecto",
        "no_lsl_3": "⚠️  a estímulos, respuestas u otros eventos experimentales.",
        "lsl_active": "🟢 LSL MARKERS: activo; se registrarán markers/triggers con timestamp corregido.",
        "lsl_limited": "⚠️ LSL RECOVERY: limitada por ausencia de source_id estable.",
        "lsl_disabled": "⚠️ LSL MARKERS: desactivado; la sesión continuará sin markers/triggers.",
        "video_disabled_no_lsl": "⚠️ VIDEO DESACTIVADO: se solicitó grabación, pero no hay stream de markers LSL.",
        "video_active": "🔴 VIDEO SYNC ACTIVO: MP4 + video_timestamps.parquet",
        "privacy_mode": "🟢 PRIVACY MODE: ningún frame será persistido en disco.",
        "session": "🎯 Sesión: {path}",
        "quit_help": "Presione q/ESC en la ventana o Ctrl+C para terminar.",
        "session_closed": "✅ Sesión cerrada: {path}",
        "calibration_window": "Calibración",
        "calibration_intro": "🧭 Calibración multipunto: centro, izquierda, derecha, arriba y abajo.",
        "look_at": "Mire hacia: {label} ({remaining}s)",
        "no_face": "No se detecta cara...",
        "force_cancel": "SPACE: forzar   q/ESC: cancelar",
        "calibration_result": "Resultado de calibración:",
        "no_data": "sin datos",
        "quality_ok": "Calidad OK",
        "quality_low": "Calidad marginal: rango bajo",
        "calibration_controls": "ENTER aceptar | R recalibrar | ESC cancelar",
        "center_no_face": "⚠️ No hubo cara en CENTRO; repitiendo calibración.",
        "CENTER": "CENTRO", "LEFT": "IZQUIERDA", "RIGHT": "DERECHA", "UP": "ARRIBA", "DOWN": "ABAJO",
        "model_download": "⬇️ Descargando modelo MediaPipe en {path}...",
        "model_error": "❌ No se pudo descargar el modelo: {error}",
        "lsl_reconnected": "🟢 LSL RECONNECTED: reapareció el mismo source_id.",
        "lsl_lost": "⚠️ LSL LOST: el stream de markers dejó de ser visible. La adquisición continúa.",
        "marker_error": "⚠️ Error recibiendo marker LSL: {error}",
        "time_correction_error": "⚠️ No se pudo calcular time_correction: {error}; usando 0.0",
    },
    "en": {
        "language_prompt": "Seleccione idioma / Select language: [1] Español  [2] English: ",
        "experiment_prefix": "📂 Experiment name/prefix: ",
        "camera_distance": "📏 Face-to-camera distance in cm [60]: ",
        "camera_probe_title": "🔍 Detecting camera modes (resolution × FPS)...",
        "camera_probe_line": "   • requested {rw}x{rh} @ {rfps:g} → actual {aw}x{ah} ~{mfps:.1f} FPS",
        "camera_modes": "\n📷 Detected camera modes:",
        "camera_auto": " [A] Automatic (recommended: highest viable resolution)",
        "camera_choose": "Select mode [A-{n}]: ",
        "camera_invalid": "❌ Invalid option.",
        "camera_selected": "✅ Selected camera mode: {w}x{h} @ ~{fps:.1f} actual FPS",
        "camera_recommended": "RECOMMENDED",
        "camera_no_modes": "⚠️ Camera modes could not be measured; keeping current settings.",
        "lsl_search": "🔍 Searching for LSL streams... maximum {timeout} seconds.",
        "lsl_countdown": "⏳ Searching for LSL streams... {remaining:02d} s remaining",
        "lsl_found": "✅ Found {n} LSL stream(s).",
        "lsl_none": "⚠️ No LSL streams were found during this search.",
        "lsl_retry": " [1] Search again ({seconds} s)",
        "lsl_continue": " [0] Continue without LSL",
        "select_option": "Select an option: ",
        "invalid_10": "❌ Invalid option. Enter 1 or 0.",
        "streams_available": "\nAvailable streams:",
        "search_again": " [R] Search again",
        "select_stream": "Select stream: ",
        "invalid": "❌ Invalid option.",
        "lsl_selected": "✅ Selected LSL: {name} ({type})",
        "no_source_id": "⚠️ The stream does not provide a stable source_id.",
        "no_source_id_2": "   Acquisition may continue, but automatic disconnection detection/recovery",
        "no_source_id_3": "   will be limited and stream identity cannot be verified rigorously.",
        "lsl_open_error": "❌ Could not open the selected stream: {error}",
        "lsl_open_error_2": "   Select another stream or press R to search again.",
        "lsl_invalid_range": "❌ Invalid option. Select 0-{n} or R.",
        "no_lsl_title": "⚠️  CONTINUING WITHOUT LSL",
        "no_lsl_1": "⚠️  Synchronization markers/triggers will not be recorded.",
        "no_lsl_2": "⚠️  Results may not be temporally interpretable relative to",
        "no_lsl_3": "⚠️  stimuli, responses, or other experimental events.",
        "lsl_active": "🟢 LSL MARKERS: active; markers/triggers will be recorded with corrected timestamps.",
        "lsl_limited": "⚠️ LSL RECOVERY: limited because no stable source_id is available.",
        "lsl_disabled": "⚠️ LSL MARKERS: disabled; the session will continue without markers/triggers.",
        "video_disabled_no_lsl": "⚠️ VIDEO DISABLED: recording was requested, but no LSL marker stream is connected.",
        "video_active": "🔴 VIDEO SYNC ACTIVE: MP4 + video_timestamps.parquet",
        "privacy_mode": "🟢 PRIVACY MODE: no frame will be persisted to disk.",
        "session": "🎯 Session: {path}",
        "quit_help": "Press q/ESC in the window or Ctrl+C to stop.",
        "session_closed": "✅ Session closed: {path}",
        "calibration_window": "Calibration",
        "calibration_intro": "🧭 Multi-point calibration: center, left, right, up, and down.",
        "look_at": "Look at: {label} ({remaining}s)",
        "no_face": "No face detected...",
        "force_cancel": "SPACE: force   q/ESC: cancel",
        "calibration_result": "Calibration result:",
        "no_data": "no data",
        "quality_ok": "Quality OK",
        "quality_low": "Marginal quality: low range",
        "calibration_controls": "ENTER accept | R recalibrate | ESC cancel",
        "center_no_face": "⚠️ No face detected at CENTER; repeating calibration.",
        "CENTER": "CENTER", "LEFT": "LEFT", "RIGHT": "RIGHT", "UP": "UP", "DOWN": "DOWN",
        "model_download": "⬇️ Downloading MediaPipe model to {path}...",
        "model_error": "❌ Could not download the model: {error}",
        "lsl_reconnected": "🟢 LSL RECONNECTED: the same source_id reappeared.",
        "lsl_lost": "⚠️ LSL LOST: the marker stream is no longer visible. Acquisition continues.",
        "marker_error": "⚠️ Error receiving LSL marker: {error}",
        "time_correction_error": "⚠️ Could not calculate time_correction: {error}; using 0.0",
    },
}


def set_language(language: str) -> None:
    global _LANGUAGE
    _LANGUAGE = "en" if str(language).lower().startswith("en") else "es"


def get_language() -> str:
    return _LANGUAGE


def t(key: str, **kwargs) -> str:
    text = _TRANSLATIONS.get(_LANGUAGE, _TRANSLATIONS["es"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


def choose_language(preselected: str | None = None) -> str:
    if preselected in ("es", "en"):
        set_language(preselected)
        return preselected
    while True:
        choice = input(_TRANSLATIONS["es"]["language_prompt"]).strip().lower()
        if choice in ("1", "es", "esp", "español", "spanish", ""):
            set_language("es")
            return "es"
        if choice in ("2", "en", "eng", "english", "inglés", "ingles"):
            set_language("en")
            return "en"
        print("❌ Opción inválida / Invalid option.")
