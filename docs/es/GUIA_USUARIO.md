# HeadTracker — Guía de usuario

## 1. Propósito

HeadTracker es una aplicación para registrar variables derivadas del movimiento de la cabeza durante tareas experimentales. Utiliza una cámara convencional, MediaPipe Face Landmarker y OpenCV para estimar orientación y distancia de la cabeza, y Lab Streaming Layer (LSL) para sincronizar la adquisición con marcadores o triggers experimentales.

El sistema está pensado para laboratorio. Su prioridad es conservar datos numéricos temporalmente trazables y minimizar el almacenamiento innecesario de imágenes identificables.

Por defecto, el video no se guarda. Los frames de cámara se procesan en memoria y se descartan después del procesamiento.

## 2. Datos que registra

Durante una sesión pueden registrarse:

- yaw, pitch y roll de la cabeza;
- distancia estimada entre la cámara y la cara;
- valores de pose crudos y filtrados;
- landmarks faciales de MediaPipe;
- blendshapes faciales de MediaPipe;
- markers/triggers recibidos mediante LSL;
- eventos de conectividad LSL;
- métricas de ejecución y metadatos de la sesión;
- video sincronizado, únicamente si se habilita explícitamente y existe un stream LSL adecuado.

## 3. Requisitos

### 3.1 Software

El proyecto utiliza:

- Python;
- OpenCV;
- MediaPipe;
- NumPy;
- pandas;
- PyArrow;
- pylsl;
- PySide6.

Las dependencias Python se encuentran en `requirements.txt`.

Para el reajuste temporal del video se recomienda FFmpeg. En Ubuntu:

```bash
sudo apt install ffmpeg
```

FFmpeg no es necesario para adquirir pose, landmarks, blendshapes o markers.

### 3.2 Hardware

Se requiere una cámara compatible con OpenCV. El programa puede probar distintas combinaciones de resolución y FPS, por ejemplo 4K, 2K, Full HD, 120 Hz, 60 Hz y 30 Hz, de acuerdo con lo definido en la configuración.

El valor que solicita el software al driver no necesariamente coincide con el FPS realmente entregado por la cámara. HeadTracker mide el FPS observado durante el sondeo y muestra ese valor al usuario.

## 4. Instalación

Desde la carpeta del proyecto:

```bash
python -m venv venv_head
source venv_head/bin/activate
pip install -r requirements.txt
```

Para iniciar la interfaz gráfica:

```bash
python main.py
```

Para usar la interfaz de terminal de diagnóstico:

```bash
python main.py --cli
```

Para cargar un archivo de configuración específico:

```bash
python main.py --config config/config.example.json
```

## 5. Flujo recomendado de una sesión

### 5.1 Seleccionar idioma

Al iniciar la interfaz se puede elegir Español o English. También puede indicarse desde la terminal:

```bash
python main.py --language es
```

### 5.2 Definir el nombre del experimento

Introduzca un identificador o prefijo de sesión. El programa crea una carpeta de salida específica para esa adquisición.

Evite incluir información personal identificable en el nombre de la sesión cuando no sea necesaria.

### 5.3 Detectar y seleccionar el modo de cámara

HeadTracker prueba las combinaciones configuradas de resolución y FPS y muestra los modos detectados junto con el FPS medido.

El programa recomienda automáticamente la mayor resolución viable, pero el usuario puede seleccionar manualmente otro modo.

Esto permite priorizar, según el estudio:

- resolución espacial, por ejemplo 3840×2160;
- resolución temporal, por ejemplo 1920×1080 a 120 FPS;
- un compromiso intermedio entre ambas.

La selección automática es una recomendación, no una imposición.

### 5.4 Introducir la distancia de calibración

Antes de calibrar, indique la distancia aproximada real entre la cámara y la cara. Esta medida se utiliza para estimar la longitud focal efectiva en píxeles y mejorar la estimación de distancia.

Si la distancia se modifica después de calibrar, debe repetirse la calibración.

### 5.5 Calibración

La calibración presenta puntos de referencia para:

- centro;
- izquierda;
- derecha;
- arriba;
- abajo.

El sistema calcula un offset para yaw, pitch y roll y comprueba que exista un rango de movimiento suficiente.

La calibración debe realizarse con la misma cámara, resolución y posición que se utilizarán durante la adquisición.

### 5.6 Seleccionar el stream LSL

HeadTracker busca streams LSL durante un máximo de 40 segundos por intento.

Mientras busca, muestra una cuenta regresiva. Si no encuentra streams, permite:

1. buscar nuevamente durante otros 40 segundos;
2. continuar sin LSL.

Si se continúa sin LSL, el programa muestra una advertencia explícita. No se registrarán markers o triggers, por lo que los resultados pueden no ser interpretables temporalmente respecto a estímulos, respuestas u otros eventos experimentales.

La adquisición de pose puede continuar sin LSL, pero esa sesión debe interpretarse de acuerdo con esta limitación.

### 5.7 Video opcional

El video está desactivado por defecto.

El preview en pantalla no significa que el video esté siendo guardado. En modo normal:

```text
Cámara → RAM → procesamiento → preview → descarte
```

Cuando se habilita video sincronizado, se generan además:

- `video.mp4`;
- `video_timestamps.parquet`;
- `video_timing_report.json`.

Por defecto, el video solo se habilita si existe un stream de markers LSL.

## 6. LSL y markers

### 6.1 Recepción de markers

Los markers se reciben de forma independiente del procesamiento de video. Esto es importante porque un paradigma puede producir triggers de forma irregular: pueden pasar segundos o varios minutos entre eventos válidos.

HeadTracker nunca interpreta la ausencia de un trigger durante un intervalo como prueba de que el stream se desconectó.

### 6.2 Corrección temporal

Cuando es posible, el timestamp recibido mediante LSL se corrige al dominio del reloj local mediante `time_correction()`.

El valor del marker y su timestamp se guardan por separado del frame de cámara.

### 6.3 Watchdog LSL

El watchdog supervisa la disponibilidad del stream utilizando su identidad LSL, principalmente `source_id`.

Los estados principales son:

- `CONNECTED`: la fuente se considera disponible;
- `LOST`: la fuente dejó de ser detectable;
- `RECOVERING`: el sistema intenta recuperar la misma fuente;
- `RECONNECTED`: reapareció la fuente esperada;
- `DISABLED`: la sesión se ejecuta sin un stream de markers.

El watchdog no utiliza la frecuencia de llegada de markers para decidir si el stream está conectado.

Para reducir falsos positivos, una única comprobación fallida no necesariamente declara una caída. El número de fallos consecutivos requerido se configura mediante `watchdog_lost_after_misses`.

### 6.4 Importancia de `source_id`

Un `source_id` estable permite identificar de forma más fiable la misma fuente después de una desconexión.

Si el stream no proporciona un `source_id` adecuado, HeadTracker puede continuar, pero la capacidad de verificar identidad y recuperación queda limitada.

## 7. Salida LSL de HeadTracker

HeadTracker también crea un outlet LSL de pose de cabeza. Por defecto contiene cuatro canales:

1. yaw;
2. pitch;
3. roll;
4. distancia.

Los parámetros del outlet pueden modificarse en la configuración.

## 8. Video y sincronización temporal

### 8.1 Autoridad temporal

Cuando se graba video, el archivo más importante para sincronización no es el MP4 sino:

```text
video_timestamps.parquet
```

Cada fila relaciona un índice de frame de video con el frame de cámara y su timestamp.

El MP4 es una representación visual de esos frames.

### 8.2 Por qué el MP4 puede requerir corrección

OpenCV escribe el MP4 con un FPS nominal constante. Si la cámara entrega, por ejemplo, 58 FPS aunque se hayan solicitado 60 FPS, el archivo sin corregir puede reproducirse ligeramente acelerado.

Al finalizar la sesión, HeadTracker calcula el FPS efectivo a partir de los timestamps observados y puede utilizar FFmpeg para reajustar globalmente la duración del MP4.

### 8.3 Informe de timing

`video_timing_report.json` incluye, entre otros:

- número de frames escritos;
- frames descartados por la cola de video;
- FPS nominal;
- FPS efectivo calculado a partir de timestamps;
- duración observada;
- duración estimada del MP4 original;
- razón de velocidad antes de la corrección;
- gaps grandes entre frames;
- estado del reajuste con FFmpeg.

Incluso después del reajuste, `video_timestamps.parquet` sigue siendo la referencia temporal principal para análisis científicos.

## 9. Archivos generados por sesión

Una sesión típica puede contener:

```text
session.json
config.json
head_pose.parquet
landmarks.parquet
blendshapes.parquet
markers.parquet
lsl_events.parquet
```

Si se habilita video sincronizado:

```text
video.mp4
video_timestamps.parquet
video_timing_report.json
```

### 9.1 `session.json`

Contiene metadatos de la sesión, incluyendo información de cámara, calibración, LSL y estado de integridad.

### 9.2 `config.json`

Es una copia de la configuración utilizada para esa sesión. Debe conservarse junto con los resultados para asegurar trazabilidad y reproducibilidad.

### 9.3 `head_pose.parquet`

Contiene las variables de pose. Se conservan valores crudos y filtrados para que el filtrado pueda revisarse posteriormente sin repetir la adquisición.

También incluye información sobre disponibilidad y estado de LSL durante el frame correspondiente.

### 9.4 `landmarks.parquet`

Contiene los landmarks faciales extraídos por MediaPipe.

### 9.5 `blendshapes.parquet`

Contiene los scores de blendshapes producidos por Face Landmarker.

### 9.6 `markers.parquet`

Contiene los markers experimentales recibidos mediante LSL con sus timestamps.

### 9.7 `lsl_events.parquet`

Contiene cambios de estado del stream, como pérdida y recuperación.

## 10. Configuración

El archivo de ejemplo se encuentra en:

```text
config/config.example.json
```

### Cámara

Los parámetros principales incluyen:

- `index`: índice de cámara OpenCV;
- `target_process_fps`: FPS objetivo de procesamiento;
- `resolutions`: resoluciones a probar;
- `fps_options`: FPS solicitados a probar;
- `mode_probe_frames`: frames utilizados para medir cada modo;
- `fps_safety_margin`: margen para considerar un modo viable.

### Tracking

- `smoothing_alpha`: suavizado aplicado a la pose para la salida filtrada;
- `model_path`: ruta local del modelo MediaPipe;
- `model_url`: URL utilizada para descargar el modelo si no existe localmente.

### Calibración

Incluye parámetros de estabilidad, tiempo máximo por punto y valores geométricos utilizados para estimar distancia.

### LSL

Incluye:

- nombre y tipo del outlet de pose;
- frecuencia nominal del outlet;
- `source_id` del outlet;
- duración de búsqueda de streams;
- intervalo del watchdog;
- timeout de resolución;
- número de fallos consecutivos antes de declarar pérdida.

### Logging

Permite habilitar o deshabilitar la escritura de:

- pose;
- landmarks;
- blendshapes;
- markers.

### Video

Los parámetros principales incluyen:

- `enabled`: video activado por configuración;
- `require_marker_stream`: exige un stream de markers para permitir video;
- `save_frame_timestamps`: conserva timestamps por frame;
- `codec`: codec solicitado a OpenCV;
- `queue_size`: tamaño de la cola de escritura de video.

## 11. Interfaz CLI

La GUI es la interfaz recomendada para uso habitual en laboratorio.

La CLI se conserva para diagnóstico y pruebas:

```bash
python main.py --cli
```

Algunas opciones de la CLI son:

```bash
python main.py --cli --prefix prueba01
python main.py --cli --video
python main.py --cli --language es
```

## 12. Solución de problemas

### La cámara no abre

Compruebe que ninguna otra aplicación esté usando la cámara y que el usuario tenga permisos para acceder al dispositivo.

En Linux puede ser útil comprobar los dispositivos disponibles:

```bash
ls /dev/video*
```

### Un modo 4K/120 aparece pero no entrega 120 FPS

Esto puede ser normal. El driver puede aceptar una solicitud pero entregar otro FPS real. Utilice el valor medido mostrado por HeadTracker para decidir qué modo seleccionar.

### No aparecen streams LSL

Compruebe que:

- el programa emisor esté ejecutándose;
- ambos equipos estén en una red que permita descubrimiento LSL;
- el firewall no esté bloqueando la comunicación;
- el stream se haya creado correctamente.

Puede repetir la búsqueda desde HeadTracker sin reiniciar la aplicación.

### El stream se perdió durante la sesión

La adquisición de pose continúa. Revise:

- `lsl_events.parquet`;
- las columnas `lsl_available` y `lsl_state` de `head_pose.parquet`;
- el resumen de integridad en `session.json`.

Los segmentos adquiridos durante la pérdida de LSL pueden no ser sincronizables con los eventos experimentales.

### El video parece acelerado o lento

Revise `video_timing_report.json`. La referencia temporal científica es `video_timestamps.parquet`.

Si FFmpeg está instalado, HeadTracker puede reajustar la duración global del MP4 al finalizar.

### Avisos Qt/OpenCV en Linux

La GUI utiliza PySide6 y la calibración utiliza OpenCV HighGUI en un proceso separado para evitar conflictos entre las implementaciones Qt. Si aparecen errores relacionados con plugins Qt o fuentes, verifique que se esté utilizando la versión actual del proyecto y que el entorno virtual no tenga variables Qt personalizadas incompatibles.

## 13. Consideraciones metodológicas

HeadTracker no debe considerarse validado automáticamente para una medida clínica o experimental específica por el hecho de producir datos numéricos.

Antes de un estudio formal se recomienda validar, con el hardware y paradigma reales:

- precisión y repetibilidad de yaw, pitch y roll;
- precisión de la estimación de distancia;
- FPS sostenido;
- latencia de procesamiento;
- sincronización de markers LSL;
- comportamiento ante desconexión y reconexión de LSL;
- pérdida de frames;
- consistencia de la calibración entre sesiones.

Los parámetros de adquisición y la configuración utilizada deben conservarse junto con los datos.

## 14. Privacidad y almacenamiento de imágenes

El comportamiento predeterminado es no persistir video.

Esto reduce la cantidad de material visual identificable almacenado, pero no sustituye la evaluación ética, jurídica, institucional o de protección de datos correspondiente a cada estudio.

Si se habilita video, el investigador debe tratarlo de acuerdo con el protocolo aprobado, el consentimiento aplicable y las políticas de almacenamiento del laboratorio o institución.

## 15. Estado del software

HeadTracker se encuentra en desarrollo activo. La versión actual debe considerarse software de investigación y no un dispositivo médico ni un sistema clínico validado.
