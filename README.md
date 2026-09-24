# Fruit Fly Tracker

A computer vision application for tracking fruit fly movement in video recordings. Built for a research sponsor as part of a university capstone project.

Analyzes video footage to compute per-frame position, total distance traveled, and velocity of fruit flies. Outputs an annotated video with tracking overlays and a CSV summary of metrics.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Developer Notes](#developer-notes)
- [Credits](#credits)

---

## Features

- Drag-and-drop or file browser video input (`.mp4`, `.mov`, `.avi`)
- Live tracking preview rendered inside the GUI as the video processes
- Annotated output video saved to `output_videos/`
- CSV export with per-frame position, distance, and velocity data saved to `output_data/`
- In-app calibration: click two points of known distance to set the cm/pixel scale
- Multi-fly tracking: click tube centers to set ROIs for up to 20 flies in one run
- Preset system: save camera and rig configurations (scale, tube dimensions, ROI positions) so calibration steps can be skipped on repeat runs
- In-app parameter tuning tab for adjusting detection settings without editing code
- Standalone parameter tuning tool for real-time visual feedback on detection settings

---

## Project Structure

```
fly-tracker/
|
+-- main.py                     # entry point, run this to launch the app
|
+-- app/
|   +-- gui.py                  # GUI layout, tab system, calibration, ROI, preview
|
+-- tracker/
|   +-- calibration.py          # calibrate_scale() and select_roi()
|   +-- tracking.py             # track_fly() core detection and metrics
|   +-- multi_tracking.py       # track_flies() sequential multi-ROI tracking
|
+-- utils/
|   +-- config.py               # all configuration, preset load/save, get_app_dir()
|   +-- export.py               # CSV export for single and multi-fly results
|
+-- tools/
|   +-- parameter_tuning.py     # standalone tool for tuning detection parameters
|
+-- input_videos/               # place input videos here (gitignored)
+-- output_videos/              # tracked output videos saved here (gitignored)
+-- output_data/                # CSV exports saved here (gitignored)
+-- config.json                 # created automatically on first run (gitignored)
+-- presets.json                # created when you save a preset (gitignored)
|
+-- requirements.txt
+-- README.md
```

---

## Requirements

- Python 3.10 or higher
- See `requirements.txt` for all dependencies

Tested on macOS and Windows. Linux should work but has not been formally tested.

**macOS note:** `tkinterdnd2` may require additional setup on Apple Silicon. If drag-and-drop does not work, see the [tkinterdnd2 docs](https://github.com/pmgagne/tkinterdnd2).

**Windows note:** If you see a blank window on launch, try running with `python main.py` from the project root instead of clicking the file directly.

---

## Installation

**1. Clone the repository**
```bash
git clone https://github.com/bryreyes/capstone-project
cd capstone-project
```

**2. Create and activate a virtual environment (recommended)**
```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

---

## Usage

### Running the app

From the project root:
```bash
python main.py
```

### Workflow

**Basic (no preset)**

1. Drop or select a video file on the Track tab
2. Click two points on the preview that are a known distance apart (default: 10 cm). This sets the cm/pixel scale
3. Click the center of each tube (multi-fly), or drag a box around the fly area (single-fly, set Tubes to 1)
4. Click Confirm. Tracking runs and the preview updates in real time
5. Results appear in the left panel when done. The CSV and annotated video are saved automatically

**With a preset (skip calibration on repeat runs)**

1. Go to the Presets tab and load an existing preset, or click New Preset to create one
2. Go to the Track tab and load a video. If the preset has a saved scale and ROIs, you go straight to the Confirm button
3. Click Confirm

See the in-app ? buttons on each tab for step-by-step guidance.

### Setting up a preset for the first time

1. Presets tab: click New Preset, give it a name (e.g. "iPhone 14 Rig A")
2. Track tab: load a video and complete the calibration click
3. Presets tab: Edit the preset and save the current scale
4. ROI Setup tab: select the preset, set the tube count, click "Start clicking", place each tube center on the preview, then click "Save ROIs to Preset"

After this, loading that preset before opening a video will restore the scale and ROIs automatically.

### Parameter tuning tool

If detection is not working well for a new setup, use the standalone tool to get visual feedback before running the full tracker:

```bash
python tools/parameter_tuning.py
```

Update `VIDEO_FILE` at the bottom of the file to point at your video. Use the sliders to adjust block size, blur, constant, and minimum area in real time. Press `s` to print the current values to the terminal, then enter them in the app's Parameters tab.

You can also adjust parameters directly from the Parameters tab in the app without restarting.

---

## Developer Notes

### Architecture

The codebase is split into three layers with no circular dependencies:

- `tracker/` has no knowledge of the GUI. It can be imported and called from any script, command line tool, or batch processor
- `app/gui.py` imports from `tracker/` and `utils/` and handles all user interaction. It uses a `queue` + `root.after()` pattern to safely update the tkinter UI from a background tracking thread. Keeping this thread structure intact is important, especially for macOS compatibility
- `utils/config.py` is the single source of truth for all configuration. It loads and saves `config.json` at runtime, exposes `get_app_dir()` for PyInstaller-safe path resolution, and manages the preset system
- `main.py` loads config and launches the GUI. It should stay that way

### PyInstaller / packaging

The project includes `FlyTracker.spec` for building a distributable executable. Build from the project root:

```bash
pyinstaller FlyTracker.spec --clean
```

Output goes to `dist/FlyTracker/`. The `--clean` flag is recommended to avoid stale cached analysis.

`get_app_dir()` in `utils/config.py` handles path resolution for both source and frozen builds. All output folders and config files are written next to the executable, not inside the PyInstaller temp directory.

On macOS, the build produces a `.app` bundle. If `config.json` ends up inside the bundle instead of next to it, the `get_app_dir()` frozen branch may need to account for the `Contents/MacOS/` path inside the bundle. See the comments in `utils/config.py`.

Do not commit `build/`, `dist/`, `config.json`, or `presets.json` to the repository (config.json sometimes ok, if needing to update threshold values). These are all in `.gitignore`. Distribute the compiled build as a release asset on GitHub or shared directly with users, not as committed files.

### Adding features

| Feature | Where to add it |
|---|---|
| Additional export formats | `utils/export.py` |
| New tracking algorithm | `tracker/tracking.py`, new function alongside `track_fly()` |
| Batch process a folder | New script importing directly from `tracker/` |
| Additional GUI tabs | `app/gui.py`, follow the existing tab builder pattern |
| New preset fields | Add to `DEFAULTS` in `utils/config.py`, update `apply()` and `load_preset()` |

### Known limitations

- Tracking is contour-based and sensitive to lighting. Results vary depending on the physical recording setup. Use the Parameters tab or `tools/parameter_tuning.py` to tune for your environment
- The ROI bottom-edge bug: ROIs placed very close to the bottom of the frame can cause the tracker to crash or skip frames on Windows. This is a known open issue. It does not appear to affect macOS
- Data on the video gets cut off when individual tubes are selected as thin ROIs. Less important limitation since all data is collected but should be fixed eventually.
- `parameter_tuning.py` is a developer tool and is not included in the packaged executable

### Running from source

Always run from the project root:
```bash
# correct
python main.py

# will break imports
cd app
python ../main.py
```

---

## Credits
**Developed by**
- Bryson Reyes
- Meliton Rojas
- Connor Tully
- Grace Le

**Course**
CS Capstone - Instructor Alan Saporta

**Academic Year**
Spring 2026

**Research Sponsor**
Dr. James Kezos, Fly Lab, CSUSM