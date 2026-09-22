# -*- mode: python ; coding: utf-8 -*-
# Build with: pyinstaller HeadTracker.spec
# Produces a single self-contained dist/HeadTracker.exe (Windows) built by
# the workflow in .github/workflows/build-windows-exe.yml.

from PyInstaller.utils.hooks import collect_all

# Bundle the MediaPipe face landmarker model so the exe works fully offline
# (headtracker.acquisition.tracking.ensure_model falls back to this path
# when it isn't found next to the exe and there's no network).
datas = [("assets/models/face_landmarker.task", ".")]
binaries = []
hiddenimports = []

# These packages ship native binaries / data files that PyInstaller's
# default import analysis misses, so pull everything they need explicitly.
for pkg in ("mediapipe", "cv2", "pyarrow", "pylsl"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HeadTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="head.ico",
)
