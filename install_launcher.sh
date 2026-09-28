#!/usr/bin/env bash
# Crea el icono "HeadTracker" en el menu de aplicaciones y en el escritorio,
# apuntando a launch.sh de esta carpeta. Volver a correrlo si se mueve la
# carpeta del repo. Uso: ./install_launcher.sh [--uninstall]
set -e
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
NAME="headtracker.desktop"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons"
DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

refresh_menu() {
    kbuildsycoca6 >/dev/null 2>&1 || kbuildsycoca5 >/dev/null 2>&1 \
        || update-desktop-database "$APPS" >/dev/null 2>&1 || true
}

if [ "$1" = "--uninstall" ]; then
    rm -f "$APPS/$NAME" "$DESKTOP/$NAME" "$ICONS/headtracker.png"
    refresh_menu
    echo "Lanzador eliminado."
    exit 0
fi

chmod +x "$DIR/launch.sh"
mkdir -p "$APPS" "$ICONS"

# Icono: head.ico convertido a PNG (mejor soporte en menus Linux). Si no hay
# herramienta para convertir, se usa un icono generico del sistema.
ICON="camera-web"
CONVERT_PY="$("$DIR/launch.sh" --which-python)"
if [ -n "$CONVERT_PY" ] && "$CONVERT_PY" - "$DIR/head.ico" "$ICONS/headtracker.png" <<'PY' 2>/dev/null
import sys
from PIL import Image
img = Image.open(sys.argv[1])
sizes = getattr(img, "ico", None) and img.ico.sizes() or [img.size]
img.size = max(sizes)
img.save(sys.argv[2])
PY
then
    ICON="$ICONS/headtracker.png"
fi

cat >"$APPS/$NAME" <<DESK
[Desktop Entry]
Type=Application
Name=HeadTracker
Comment=Seguimiento facial y de pose de cabeza con MediaPipe y LSL
Exec="$DIR/launch.sh"
Path=$DIR
Icon=$ICON
Terminal=false
Categories=Science;
DESK
chmod +x "$APPS/$NAME"

if [ -d "$DESKTOP" ]; then
    cp "$APPS/$NAME" "$DESKTOP/$NAME"
    chmod +x "$DESKTOP/$NAME"
    # GNOME pide marcar el icono como confiable; en KDE se confirma al primer doble clic
    gio set "$DESKTOP/$NAME" metadata::trusted true 2>/dev/null || true
fi

refresh_menu
echo "Lanzador instalado en el menu de aplicaciones${DESKTOP:+ y en $DESKTOP}."
