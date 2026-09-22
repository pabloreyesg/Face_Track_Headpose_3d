# Face and Head Tracker

Face and HeadTracker is a laboratory application for real-time face - head tracking using MediaPipe, OpenCV and Lab Streaming Layer (LSL).

HeadTracker es una aplicación de laboratorio para seguimiento de la cabeza en tiempo real mediante MediaPipe, OpenCV y Lab Streaming Layer (LSL).

The application is designed for experimental acquisition rather than video recording. Raw camera frames are processed in memory and are not saved by default. Optional video recording is only enabled when it can be associated with an LSL marker stream and is accompanied by per-frame timestamps.

La aplicación está diseñada para adquisición experimental y no como sistema de grabación de video. Los frames de cámara se procesan en memoria y no se guardan por defecto. La grabación de video es opcional y solo se habilita cuando puede asociarse con un stream de marcadores LSL; cada frame grabado conserva además su timestamp.

## Documentation / Documentación

- [Guía de usuario en español](docs/es/GUIA_USUARIO.md)
- [User guide in English](docs/en/USER_GUIDE.md)

## Main features / Funciones principales

- Real-time head pose: yaw, pitch, roll and estimated camera-to-face distance.
- MediaPipe Face Landmarker: facial landmarks and blendshapes.
- LSL input for experimental markers/triggers.
- LSL output for head pose.
- LSL watchdog based on stream identity (`source_id`), not on marker frequency.
- Incremental Parquet logging.
- Raw and filtered head-pose values are both preserved.
- Camera mode detection with measured FPS and manual mode selection.
- Spanish and English interface.
- Video disabled by default.
- Optional synchronized video with per-frame timestamps and timing report.

## Quick start / Inicio rápido

Python 3.12 is recommended for the current project environment.

```bash
python -m venv venv_head
source venv_head/bin/activate
pip install -r requirements.txt
python main.py
```

On systems where synchronized video retiming is required, install FFmpeg:

```bash
sudo apt install ffmpeg
```

The terminal diagnostic interface remains available:

```bash
python main.py --cli
```

A custom configuration can be supplied with:

```bash
python main.py --config config/config.example.json
```

## Privacy-oriented default behavior / Comportamiento predeterminado orientado a privacidad

By default, camera images are not written to disk. The preview may be visible while frames are processed, but the frames are discarded after processing.

Por defecto, las imágenes de cámara no se escriben en disco. El preview puede mostrarse durante la adquisición, pero los frames se descartan después del procesamiento.

If video is enabled, `video_timestamps.parquet` is the authoritative temporal reference. The MP4 file is a visual representation and may be globally retimed after acquisition to match the observed session duration.

Si se habilita video, `video_timestamps.parquet` es la referencia temporal autoritativa. El archivo MP4 es una representación visual y puede ser reajustado al finalizar para que su duración coincida con la duración observada de la sesión.

## Project structure / Estructura del proyecto

```text
headtracker_refactor/
├── main.py
├── requirements.txt
├── README.md
├── config/
│   └── config.example.json
├── docs/
│   ├── es/
│   │   └── GUIA_USUARIO.md
│   └── en/
│       └── USER_GUIDE.md
├── legacy/
│   └── head_tracker_original.py
└── headtracker/
    ├── core/
    ├── acquisition/
    ├── io/
    ├── ui/
    ├── interfaces/
    └── tools/
```

## Current status

This is laboratory/research software under active development. Before collecting critical experimental data, validate camera timing, LSL markers, calibration and output files with the exact hardware and experimental software that will be used in the study.
