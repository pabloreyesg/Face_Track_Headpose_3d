from __future__ import annotations

import argparse
import sys
import os


def _ensure_std_streams():
    """A windowed (console=False) PyInstaller build has no console, so
    sys.stdout/sys.stderr are None. The app has print() calls and stderr
    redirection scattered through code shared with the console CLI/worker
    paths; give them a real (discarded) stream instead of crashing."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")


def _sanitize_opencv_qt_environment():
    """Prevent OpenCV wheel Qt paths from hijacking PySide6 on Linux."""
    try:
        import cv2  # may populate QT_QPA_* variables in some opencv-python wheels
    except Exception:
        return
    for key in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_FONTDIR"):
        value = os.environ.get(key, "")
        if "cv2/qt" in value.replace("\\", "/"):
            os.environ.pop(key, None)



def parse_args():
    p = argparse.ArgumentParser(description="HeadTracker GUI / modular acquisition")
    p.add_argument("--config", default=None, help="Optional config.json")
    p.add_argument("--sessions-dir", default="sessions", help="Sessions output directory")
    p.add_argument("--language", choices=["es", "en"], default=None)
    p.add_argument("--cli", action="store_true", help="Run legacy terminal interface")
    return p.parse_args()


def main():
    _ensure_std_streams()

    # Internal re-entry point: when frozen (PyInstaller), there is no separate
    # Python interpreter to run `-m headtracker.tools.calibration_worker`, so
    # the GUI relaunches this same executable with this hidden flag instead.
    # Must be checked before parse_args(), since the worker has its own
    # required arguments that the GUI/CLI parser above doesn't know about.
    if len(sys.argv) > 1 and sys.argv[1] == "--calibration-worker":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from headtracker.tools.calibration_worker import main as worker_main
        raise SystemExit(worker_main())

    args = parse_args()
    if args.cli:
        from headtracker.interfaces.cli import main as cli_main
        # The legacy CLI has its own argparse parser; remove the GUI-only flag.
        sys.argv = [a for a in sys.argv if a != "--cli"]
        cli_main()
        return

    _sanitize_opencv_qt_environment()

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is required for the GUI. Install with: pip install PySide6")
        print("You can still run the terminal version with: python main.py --cli")
        raise SystemExit(2)

    from headtracker.ui.gui import choose_gui_language, HeadTrackerWindow

    app = QApplication(sys.argv)
    app.setApplicationName("HeadTracker")
    language = args.language or choose_gui_language()
    if language is None:
        return
    window = HeadTrackerWindow(
        config_path=args.config,
        sessions_dir=args.sessions_dir,
        language=language,
    )
    window.resize(1120, 760)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
