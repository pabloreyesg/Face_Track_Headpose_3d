# HeadTracker — User Guide

## 1. Purpose

HeadTracker is an application for recording variables derived from head movement during experimental tasks. It uses a conventional camera, MediaPipe Face Landmarker and OpenCV to estimate head orientation and distance, and Lab Streaming Layer (LSL) to synchronize acquisition with experimental markers or triggers.

The system is intended for laboratory use. Its priority is to preserve temporally traceable numerical data while minimizing unnecessary storage of identifiable images.

Video is not saved by default. Camera frames are processed in memory and discarded after processing.

## 2. Data recorded

A session can record:

- head yaw, pitch and roll;
- estimated camera-to-face distance;
- raw and filtered pose values;
- MediaPipe facial landmarks;
- MediaPipe facial blendshapes;
- LSL markers/triggers;
- LSL connectivity events;
- runtime metrics and session metadata;
- synchronized video, only when explicitly enabled and an appropriate LSL marker stream is available.

## 3. Requirements

### 3.1 Software

The project uses:

- Python;
- OpenCV;
- MediaPipe;
- NumPy;
- pandas;
- PyArrow;
- pylsl;
- PySide6.

Python dependencies are listed in `requirements.txt`.

FFmpeg is recommended for synchronized-video timing correction. On Ubuntu:

```bash
sudo apt install ffmpeg
```

FFmpeg is not required for head pose, landmarks, blendshapes or marker acquisition.

### 3.2 Hardware

A camera accessible through OpenCV is required. The application can probe multiple resolution/FPS combinations, such as 4K, 2K, Full HD, 120 Hz, 60 Hz and 30 Hz, according to the configuration file.

A camera driver may accept a requested mode without actually delivering the requested frame rate. HeadTracker therefore measures the observed FPS during probing and displays that value to the user.

## 4. Installation

From the project directory:

```bash
python -m venv venv_head
source venv_head/bin/activate
pip install -r requirements.txt
```

Start the graphical interface with:

```bash
python main.py
```

Start the terminal diagnostic interface with:

```bash
python main.py --cli
```

Load a specific configuration with:

```bash
python main.py --config config/config.example.json
```

## 5. Recommended session workflow

### 5.1 Select language

At startup, select Español or English. The language can also be specified from the command line:

```bash
python main.py --language en
```

### 5.2 Define the experiment/session name

Enter a session identifier or prefix. HeadTracker creates a dedicated output directory for the acquisition.

Avoid including personally identifiable information in the session name unless it is required by the study protocol.

### 5.3 Detect and select the camera mode

HeadTracker probes the configured combinations of resolution and FPS and displays detected modes together with measured FPS.

The application recommends the highest viable pixel resolution, but the user can manually select any other detected mode.

This allows the study to prioritize:

- spatial resolution, for example 3840×2160;
- temporal resolution, for example 1920×1080 at 120 FPS;
- an intermediate trade-off.

Automatic selection is a recommendation, not a forced choice.

### 5.4 Enter calibration distance

Before calibration, enter the approximate real distance between the camera and the participant's face. This value is used to estimate the effective focal length in pixels and improve distance estimation.

If the distance is changed after calibration, calibration should be repeated.

### 5.5 Calibration

Calibration displays reference targets for:

- center;
- left;
- right;
- up;
- down.

The system estimates yaw, pitch and roll offsets and verifies that a sufficient range of movement was detected.

Calibration should be performed using the same camera, resolution and physical setup that will be used during acquisition.

### 5.6 Select an LSL stream

HeadTracker searches for LSL streams for up to 40 seconds per attempt.

A countdown is shown while searching. If no stream is found, the user can:

1. search again for another 40 seconds;
2. continue without LSL.

If acquisition continues without LSL, an explicit warning is shown. No markers or triggers will be recorded, and the results may not be temporally interpretable relative to stimuli, responses or other experimental events.

Head-pose acquisition can continue without LSL, but the resulting session should be interpreted according to this limitation.

### 5.7 Optional video

Video is disabled by default.

The on-screen preview does not imply that video is being saved. In normal operation:

```text
Camera → RAM → processing → preview → discard
```

When synchronized video is enabled, HeadTracker additionally produces:

- `video.mp4`;
- `video_timestamps.parquet`;
- `video_timing_report.json`.

By default, video is only enabled when an LSL marker stream is available.

## 6. LSL and markers

### 6.1 Marker acquisition

Markers are acquired independently from video processing. This is important because experimental paradigms can produce irregular trigger streams: valid markers may be separated by seconds or several minutes.

HeadTracker never treats a long interval without markers as evidence that the LSL stream has disconnected.

### 6.2 Clock correction

When available, LSL timestamps are corrected to the local clock domain using `time_correction()`.

Marker values and their timestamps are stored independently from camera frames.

### 6.3 LSL watchdog

The watchdog monitors stream availability using the LSL stream identity, primarily `source_id`.

Main states are:

- `CONNECTED`: the expected source is considered available;
- `LOST`: the source is no longer discoverable;
- `RECOVERING`: the system is attempting to recover the same source;
- `RECONNECTED`: the expected source has reappeared;
- `DISABLED`: the session is running without a marker stream.

The watchdog does not use marker arrival frequency as a connectivity criterion.

To reduce false positives, one failed discovery check does not necessarily declare a disconnection. The required number of consecutive misses is controlled by `watchdog_lost_after_misses`.

### 6.4 Importance of `source_id`

A stable `source_id` provides a more reliable way to identify the same LSL source after a disconnection.

If the stream does not provide a suitable `source_id`, HeadTracker can continue, but stream identity verification and recovery are more limited.

## 7. HeadTracker LSL output

HeadTracker also creates an LSL outlet for head pose. By default it contains four channels:

1. yaw;
2. pitch;
3. roll;
4. distance.

Outlet parameters can be changed in the configuration file.

## 8. Video and temporal synchronization

### 8.1 Temporal authority

When video is recorded, the primary synchronization file is not the MP4 but:

```text
video_timestamps.parquet
```

Each row relates a video frame index to a camera frame and its timestamp.

The MP4 is a visual representation of those frames.

### 8.2 Why the MP4 may require retiming

OpenCV writes the MP4 using a constant nominal FPS. If the camera actually delivers 58 FPS after 60 FPS was requested, the uncorrected file may play slightly too fast.

At the end of the session, HeadTracker calculates the effective frame rate from observed timestamps and can use FFmpeg to adjust the global MP4 duration.

### 8.3 Timing report

`video_timing_report.json` includes, among other fields:

- number of frames written;
- frames dropped by the video queue;
- nominal FPS;
- effective FPS calculated from timestamps;
- observed duration;
- estimated duration of the original MP4;
- playback speed ratio before correction;
- large frame gaps;
- FFmpeg retiming status.

Even after retiming, `video_timestamps.parquet` remains the primary temporal reference for scientific analysis.

## 9. Session output files

A typical session can contain:

```text
session.json
config.json
head_pose.parquet
landmarks.parquet
blendshapes.parquet
markers.parquet
lsl_events.parquet
```

If synchronized video is enabled:

```text
video.mp4
video_timestamps.parquet
video_timing_report.json
```

### 9.1 `session.json`

Contains session metadata including camera information, calibration, LSL information and integrity status.

### 9.2 `config.json`

A copy of the configuration used for the session. Keep it with the data for reproducibility and traceability.

### 9.3 `head_pose.parquet`

Contains head-pose variables. Both raw and filtered values are preserved so filtering can be changed later without repeating acquisition.

It also includes LSL availability/state information for the corresponding data interval.

### 9.4 `landmarks.parquet`

Contains facial landmarks extracted by MediaPipe.

### 9.5 `blendshapes.parquet`

Contains Face Landmarker blendshape scores.

### 9.6 `markers.parquet`

Contains experimental LSL markers and their timestamps.

### 9.7 `lsl_events.parquet`

Contains stream-state changes such as loss and recovery.

## 10. Configuration

The reference configuration is located at:

```text
config/config.example.json
```

### Camera

Main parameters include:

- `index`: OpenCV camera index;
- `target_process_fps`: target processing rate;
- `resolutions`: resolutions to probe;
- `fps_options`: requested FPS values to probe;
- `mode_probe_frames`: frames used to measure each mode;
- `fps_safety_margin`: margin used to determine whether a mode is viable.

### Tracking

- `smoothing_alpha`: smoothing applied to the filtered pose output;
- `model_path`: local MediaPipe model path;
- `model_url`: URL used to download the model if it is missing.

### Calibration

Includes stability thresholds, per-target timeout and geometric values used for distance estimation.

### LSL

Includes:

- head-pose outlet name and type;
- nominal outlet sampling rate;
- outlet `source_id`;
- stream-search duration;
- watchdog interval;
- resolver timeout;
- number of consecutive misses before declaring loss.

### Logging

Allows enabling or disabling storage of:

- head pose;
- landmarks;
- blendshapes;
- markers.

### Video

Main parameters include:

- `enabled`: enables video through configuration;
- `require_marker_stream`: requires a marker stream before video can be enabled;
- `save_frame_timestamps`: stores per-frame timestamps;
- `codec`: codec requested from OpenCV;
- `queue_size`: video-writing queue size.

## 11. CLI interface

The GUI is the recommended interface for normal laboratory operation.

The CLI remains available for diagnostics and testing:

```bash
python main.py --cli
```

Examples:

```bash
python main.py --cli --prefix test01
python main.py --cli --video
python main.py --cli --language en
```

## 12. Troubleshooting

### Camera does not open

Verify that no other application is using the camera and that the current user has permission to access the device.

On Linux, available devices can be inspected with:

```bash
ls /dev/video*
```

### A 4K/120 mode appears but does not deliver 120 FPS

This can be normal. A driver may accept a requested mode but deliver a lower real frame rate. Use the measured FPS displayed by HeadTracker when selecting a mode.

### No LSL streams are found

Check that:

- the sender application is running;
- the computers are on a network that permits LSL discovery;
- firewalls are not blocking communication;
- the outlet was created correctly.

The search can be repeated from HeadTracker without restarting the application.

### The LSL stream was lost during acquisition

Head-pose acquisition continues. Inspect:

- `lsl_events.parquet`;
- `lsl_available` and `lsl_state` in `head_pose.parquet`;
- the integrity summary in `session.json`.

Segments acquired while LSL was unavailable may not be synchronizable with experimental events.

### Video appears too fast or too slow

Inspect `video_timing_report.json`. The scientific temporal reference is `video_timestamps.parquet`.

If FFmpeg is available, HeadTracker can correct the global MP4 duration after acquisition.

### Qt/OpenCV warnings on Linux

The GUI uses PySide6 and calibration uses OpenCV HighGUI in a separate process to reduce Qt conflicts. If Qt plugin or font errors occur, verify that the current project version is being used and that the virtual environment does not contain incompatible custom Qt environment variables.

## 13. Methodological considerations

HeadTracker should not be considered automatically validated for a particular clinical or experimental measure simply because it produces numerical output.

Before formal data collection, validate with the actual study hardware and paradigm:

- accuracy and repeatability of yaw, pitch and roll;
- accuracy of distance estimation;
- sustained camera FPS;
- processing latency;
- LSL marker synchronization;
- behavior during LSL disconnection and reconnection;
- frame loss;
- calibration consistency across sessions.

Acquisition parameters and the session configuration should be retained with the data.

## 14. Privacy and image storage

The default behavior is not to persist video.

This reduces the amount of identifiable visual material stored, but it does not replace the ethical, legal, institutional or data-protection assessment required for each study.

If video is enabled, investigators should handle it according to the approved protocol, applicable consent and institutional/laboratory storage policies.

## 15. Software status

HeadTracker is under active development. The current version should be treated as research software, not as a medical device or validated clinical system.
