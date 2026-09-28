# Third-party licenses

HeadTracker is distributed under the GNU General Public License v3.0 or later
(see [LICENSE](LICENSE)). It depends on, and the Windows executable bundles,
the following third-party components, each distributed under its own license.

| Component | License | Source |
|---|---|---|
| OpenCV (`opencv-python`) | Apache-2.0 | https://github.com/opencv/opencv-python |
| FFmpeg (bundled by `opencv-python`) | LGPL-2.1-or-later | https://ffmpeg.org |
| MediaPipe | Apache-2.0 | https://github.com/google-ai-edge/mediapipe |
| MediaPipe Face Landmarker model (`face_landmarker.task`) | Apache-2.0 | https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy |
| pandas | BSD-3-Clause | https://github.com/pandas-dev/pandas |
| Apache Arrow (`pyarrow`) | Apache-2.0 | https://github.com/apache/arrow |
| pylsl / liblsl | MIT | https://github.com/labstreaminglayer/pylsl |
| PySide6 / Qt for Python | LGPL-3.0 | https://code.qt.io/cgit/pyside/pyside-setup.git |
| Qt 6 | LGPL-3.0 | https://download.qt.io/official_releases/qt/ |
| PyInstaller bootloader | GPL-2.0-or-later with bootloader exception | https://github.com/pyinstaller/pyinstaller |

## Notes

- The Apache-2.0 components include their own `NOTICE` files, available in
  their source repositories linked above.
- Qt/PySide6 and FFmpeg are used unmodified. Their source code is available
  from the links above. HeadTracker's complete source code, including the
  build configuration (`HeadTracker.spec`, `.github/workflows/`), is available
  at https://github.com/pabloreyesg/Face_Track_Headpose_3d, so the executable
  can be rebuilt against modified versions of these libraries.
- Full license texts: Apache-2.0 (https://www.apache.org/licenses/LICENSE-2.0),
  BSD-3-Clause (https://opensource.org/license/bsd-3-clause),
  MIT (https://opensource.org/license/mit),
  LGPL-2.1 (https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html),
  LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0.html),
  GPL-3.0 (https://www.gnu.org/licenses/gpl-3.0.html).
