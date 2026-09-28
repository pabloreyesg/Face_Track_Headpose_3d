#!/usr/bin/env bash
# Lanza HeadTracker sin activar el entorno ni entrar a la carpeta.
# Busca el Python del proyecto en este orden:
#   1. variable HEADTRACKER_PYTHON (ruta explicita a un python)
#   2. venv_head/, .venv/ o venv/ dentro del repo
#   3. entorno conda "face" en las instalaciones usuales
# Se ejecuta desde la carpeta del repo porque sessions/ y face_landmarker.task
# son rutas relativas. La salida queda en last_run.log (no hay terminal visible).
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

find_python() {
    if [ -n "$HEADTRACKER_PYTHON" ] && [ -x "$HEADTRACKER_PYTHON" ]; then
        echo "$HEADTRACKER_PYTHON"; return
    fi
    for venv in venv_head .venv venv; do
        if [ -x "$DIR/$venv/bin/python" ]; then
            echo "$DIR/$venv/bin/python"; return
        fi
    done
    for base in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3" "$HOME/mambaforge" /opt/conda; do
        if [ -x "$base/envs/face/bin/python" ]; then
            echo "$base/envs/face/bin/python"; return
        fi
    done
}

PY="$(find_python)"
# Usado por install_launcher.sh para convertir el icono con el mismo entorno
if [ "$1" = "--which-python" ]; then echo "$PY"; exit 0; fi

LOG="$DIR/last_run.log"
cd "$DIR"

if [ -z "$PY" ]; then
    MSG="No se encontro el entorno Python de HeadTracker (ver README, Quick start)."
    echo "$MSG" >"$LOG"
    if command -v kdialog >/dev/null; then
        kdialog --error "$MSG"
    elif command -v zenity >/dev/null; then
        zenity --error --text="$MSG"
    fi
    exit 1
fi

echo "python: $PY" >"$LOG"
exec "$PY" main.py "$@" >>"$LOG" 2>&1
