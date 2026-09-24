# Central configuration for fly tracking.
#
# On startup, load_config() reads config.json from the app directory.
# If config.json doesn't exist (first run), it writes one from the
# hardcoded defaults below so the file is always present.
#
# All other modules import the module-level constants (GAUSSIAN_BLUR_SIZE etc.)
# as before. After load_config() runs, those
# names are rebound to whatever config.json contains.
#
# save_config() / save_preset() / load_preset() are called by the GUI.
# get_app_dir() is the single source of truth for path resolution and is
# PyInstaller-safe (uses sys.executable when frozen, __file__ otherwise).

import os
import sys
import json


# finding correct path for pyinstaller to work
def get_app_dir():
    """
    Return the directory that should be used for config.json, output_data/,
    and output_videos/.

    When running from source:  the project root (two levels up from utils/)
    When frozen by PyInstaller: the folder containing the .exe
                                (sys.executable points to the .exe itself)

    Using sys.executable for the frozen case means output folders appear
    next to the .exe rather than inside the temporary _MEIPASS unpack dir,
    which is deleted when the app exits.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # running from source: this file is utils/config.py, so go up two levels
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)

    # IF IT DOES WORK ON MAC, TRY UNCOMMENTING THIS BLOCK
    # if getattr(sys, "frozen", False):
    #     # On Mac .app bundles, go up from Contents/MacOS/ to the .app's parent
    #     exe_dir = os.path.dirname(sys.executable)
    #     if exe_dir.endswith("Contents/MacOS"):
    #         return os.path.dirname(os.path.dirname(os.path.dirname(exe_dir)))
    #     return exe_dir

# hardcoded defaults
# these are written to config.json on first run and act as the fallback
# if any key is missing from older config file
DEFAULTS = {
    # Calibration
    "known_distance_cm": 10,

    # Image processing
    "adaptive_block_size": 11,  # must be odd
    "adaptive_constant": 7,
    "gaussian_blur_size": 13,   # must be odd

    # Contour filtering
    "min_contour_area": 21,
    "max_contour_area": 201,
    "search_radius":    50,

    # Static shadow / persistent-dark-region exclusion (tube slots, rig shadows).
    # See tracker/tracking.py: build_static_exclusion_mask()
    "use_static_mask": True,
    "static_mask_sample_frames": 100,
    "static_mask_overlap_threshold": 0.6,
    "static_mask_occupancy_threshold": 0.7,

    # Deliberately separate from the main detection settings above. The
    # main settings are tuned to be strict (few false positives during
    # real tracking); building a good exclusion mask wants the opposite --
    # loose enough to see the whole shadow as one solid, consistent blob
    # rather than fragments. Tune these using the parameter-tuning tool by
    # pressing 'm'/'b', same as you'd tune the detection settings.
    "static_mask_build_block_size": 15,
    "static_mask_build_constant": 3,
    "static_mask_build_blur_size": 7,
    "static_mask_build_min_area": 30,
    "static_mask_build_max_area": 2000,

    # always ignore the bottom N pixels of whatever frame is being processed
    # This is where a tube's bottom slot/shadow physically sits, so it's fine to be generous here
    # Set to 0 to disable. Becomes much less important if the tube holes
    # get painted white, so keep this tunable
    "static_bottom_exclusion_px": 80,

    # Output naming. Available: {video_name} {basename} {timestamp}
    # for the folder, plus {fly_label} for the filename. Any token left
    # empty (e.g. fly_label in single-fly mode) gets cleaned up so you
    # don't end up with stray "__" in the name. One folder is created per
    # tracking RUN (shared by every fly in that run), not one per fly.
    "output_folder_template":   "{video_name}_{timestamp}",
    "output_filename_template": "{video_name}_{basename}_{fly_label}_{timestamp}",

    # output
    "output_video_basename": "tracked_output",

    # Preset scale: None means "always calibrate manually".
    # Set by saving a preset from the GUI.
    "preset_scale": None,

    # Multi-tube defaults
    "default_n_tubes": 20,
    "tube_half_w":     42,
    "tube_half_h":     370,

    # saved ROI centers as a list of [x, y] pairs (pixel coords on the
    # reference frame). None means no ROI preset anduser clicks each run.
    # Stored in config.json so the last-used ROIs survive restarts even
    # without a named preset
    "tube_rois": None,

    # Active preset name (None = no preset loaded)
    "active_preset": None,
}

# config file location
def config_path():
    return os.path.join(get_app_dir(), "config.json")

def presets_path():
    return os.path.join(get_app_dir(), "presets.json")



# load / save config
def load_config():
    """
    Read config.json and rebind all module-level constants.

    If config.json doesn't exist, write one from DEFAULTS first.
    Unknown keys in config.json are ignored; missing keys fall back to
    DEFAULTS so old config files stay forward-compatible.

    Call this once at startup (gui.py does this before building the UI).
    """
    path = config_path()

    if not os.path.exists(path):
        write_json(path, DEFAULTS)
        print(f"Config: created default config.json at {path}")
        data = DEFAULTS.copy()
    else:
        try:
            with open(path, "r") as f:
                data = json.load(f)
            # fill in any keys that didn't exist in an older config file
            changed = False
            for key, val in DEFAULTS.items():
                if key not in data:
                    data[key] = val
                    changed = True
            if changed:
                write_json(path, data)
        except Exception as e:
            print(f"Config: failed to read config.json ({e}), using defaults")
            data = DEFAULTS.copy()

    apply(data)


def save_config(overrides: dict):
    """
    Merge overrides into config.json and rebind module-level constants.

    args:
        overrides: dict of key/value pairs to update (same keys as DEFAULTS)
    """
    path = config_path()
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        data = DEFAULTS.copy()

    data.update(overrides)
    write_json(path, data)
    apply(data)
    print(f"Config: saved {list(overrides.keys())} to config.json")


def get_config() -> dict:
    """Return the current config.json as a dict (for populating the GUI)"""
    path = config_path()
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return DEFAULTS.copy()

# preset system
def list_presets() -> list:
    """
    Return all saved presets as a list of dicts, sorted by name.

    Each preset dict has at minimum:
        name, scale, known_distance_cm, n_tubes, tube_half_w, tube_half_h
    """
    path = presets_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return sorted(data.get("presets", []), key=lambda p: p.get("name", ""))
    except Exception as e:
        print(f"Presets: failed to read presets.json ({e})")
        return []

def save_preset(preset: dict):
    """
    Save or update a preset by name.

    Required keys in preset dict:
        name (str): display name, used as unique ID
        scale (float|None): cm/pixel, None if not yet calibrated
        known_distance_cm (int:float)
        n_tubes (int)
        tube_half_w (int)
        tube_half_h (int)

    If a preset with the same name exists it is overwritten.
    """
    path = presets_path()
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        data = {"presets": []}

    presets = data.get("presets", [])
    # replace existing entry with the same name, or append
    presets = [p for p in presets if p.get("name") != preset["name"]]
    presets.append(preset)
    data["presets"] = presets
    write_json(path, data)
    print(f"Presets: saved '{preset['name']}'")

def load_preset(name: str) -> dict | None:
    """
    Load a preset by name and apply its values to config.json / module constants.
 
    Returns the preset dict on success, None if not found.
    Overrides the earlier definition so ROIs are also applied.
    """
    presets = list_presets()
    match = next((p for p in presets if p.get("name") == name), None)
    if match is None:
        print(f"Presets: '{name}' not found")
        return None
 
    save_config({
        "preset_scale":       match.get("scale"),
        "known_distance_cm":  match.get("known_distance_cm", KNOWN_DISTANCE_CM),
        "default_n_tubes":    match.get("n_tubes", DEFAULT_N_TUBES),
        "tube_half_w":        match.get("tube_half_w", TUBE_HALF_W),
        "tube_half_h":        match.get("tube_half_h", TUBE_HALF_H),
        "tube_rois":          match.get("tube_rois"),   # None if not yet set
        "active_preset":      name,
    })
    print(f"Presets: loaded '{name}' (scale={match.get('scale')}, "
          f"rois={'yes' if match.get('tube_rois') else 'none'})")
    return match

def delete_preset(name: str):
    """Remove a preset by name from presets.json."""
    path = presets_path()
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return
    data["presets"] = [p for p in data.get("presets", []) if p.get("name") != name]
    write_json(path, data)

    # clear active_preset in config if it was this one
    cfg = get_config()
    if cfg.get("active_preset") == name:
        save_config({"active_preset": None, "preset_scale": None})
    print(f"Presets: deleted '{name}'")

def centers_to_rois(centers: list, half_w: int = None, half_h: int = None) -> list:
    """
    Convert a list of (x, y) center points into (x, y, w, h) ROI tuples.
 
    Uses TUBE_HALF_W / TUBE_HALF_H from the live config unless overrides
    are passed. The GUI calls this right before passing ROIs to track_flies().
 
    args:
        centers: list of (x, y) tuples
        half_w: override for TUBE_HALF_W
        half_h: override for TUBE_HALF_H
    returns:
        list of (x, y, w, h) tuples
    """
    hw = half_w if half_w is not None else TUBE_HALF_W
    hh = half_h if half_h is not None else TUBE_HALF_H
    return [(cx - hw, cy - hh, hw * 2, hh * 2) for cx, cy in centers]


def write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def apply(data: dict):
    """
    Rebind all module-level constants from a config dict.
    Uses globals() so imports elsewhere (from utils.config import SEARCH_RADIUS)
    pick up the updated values after load_config() is called.
    """
    g = globals()
    g["KNOWN_DISTANCE_CM"] = data.get("known_distance_cm", DEFAULTS["known_distance_cm"])
    g["GAUSSIAN_BLUR_SIZE"] = data.get("gaussian_blur_size", DEFAULTS["gaussian_blur_size"])
    g["ADAPTIVE_BLOCK_SIZE"] = data.get("adaptive_block_size", DEFAULTS["adaptive_block_size"])
    g["ADAPTIVE_CONSTANT"] = data.get("adaptive_constant", DEFAULTS["adaptive_constant"])
    g["MIN_CONTOUR_AREA"] = data.get("min_contour_area", DEFAULTS["min_contour_area"])
    g["MAX_CONTOUR_AREA"] = data.get("max_contour_area", DEFAULTS["max_contour_area"])
    g["USE_STATIC_MASK"] = data.get("use_static_mask", DEFAULTS["use_static_mask"])
    g["STATIC_MASK_SAMPLE_FRAMES"] = data.get("static_mask_sample_frames", DEFAULTS["static_mask_sample_frames"])
    g["STATIC_MASK_OVERLAP_THRESHOLD"] = data.get("static_mask_overlap_threshold", DEFAULTS["static_mask_overlap_threshold"])
    g["STATIC_MASK_OCCUPANCY_THRESHOLD"] = data.get("static_mask_occupancy_threshold", DEFAULTS["static_mask_occupancy_threshold"])
    g["STATIC_MASK_BUILD_BLOCK_SIZE"] = data.get("static_mask_build_block_size", DEFAULTS["static_mask_build_block_size"])
    g["STATIC_MASK_BUILD_CONSTANT"] = data.get("static_mask_build_constant", DEFAULTS["static_mask_build_constant"])
    g["STATIC_MASK_BUILD_BLUR_SIZE"] = data.get("static_mask_build_blur_size", DEFAULTS["static_mask_build_blur_size"])
    g["STATIC_MASK_BUILD_MIN_AREA"] = data.get("static_mask_build_min_area", DEFAULTS["static_mask_build_min_area"])
    g["STATIC_MASK_BUILD_MAX_AREA"] = data.get("static_mask_build_max_area", DEFAULTS["static_mask_build_max_area"])
    g["STATIC_BOTTOM_EXCLUSION_PX"] = data.get("static_bottom_exclusion_px", DEFAULTS["static_bottom_exclusion_px"])
    g["OUTPUT_FOLDER_TEMPLATE"] = data.get("output_folder_template", DEFAULTS["output_folder_template"])
    g["OUTPUT_FILENAME_TEMPLATE"] = data.get("output_filename_template", DEFAULTS["output_filename_template"])
    g["SEARCH_RADIUS"] = data.get("search_radius", DEFAULTS["search_radius"])
    g["OUTPUT_VIDEO_BASENAME"] = data.get("output_video_basename", DEFAULTS["output_video_basename"])
    g["PRESET_SCALE"] = data.get("preset_scale", DEFAULTS["preset_scale"])
    g["DEFAULT_N_TUBES"] = data.get("default_n_tubes", DEFAULTS["default_n_tubes"])
    g["TUBE_HALF_W"] = data.get("tube_half_w", DEFAULTS["tube_half_w"])
    g["TUBE_HALF_H"] = data.get("tube_half_h", DEFAULTS["tube_half_h"])
    g["ACTIVE_PRESET"] = data.get("active_preset", DEFAULTS.get("active_preset"))
    g["TUBE_ROIS"] = data.get("tube_rois", DEFAULTS["tube_rois"])


# Module-level constants (initial values = hardcoded defaults)
# load_config() rebinds these at startup.
# All other modules import these names directly and get the correct values
# as long as load_config() has been called before tracking begins.

KNOWN_DISTANCE_CM = DEFAULTS["known_distance_cm"]
GAUSSIAN_BLUR_SIZE = DEFAULTS["gaussian_blur_size"]
ADAPTIVE_BLOCK_SIZE = DEFAULTS["adaptive_block_size"]
ADAPTIVE_CONSTANT = DEFAULTS["adaptive_constant"]
MIN_CONTOUR_AREA = DEFAULTS["min_contour_area"]
MAX_CONTOUR_AREA = DEFAULTS["max_contour_area"]
USE_STATIC_MASK = DEFAULTS["use_static_mask"]
STATIC_MASK_SAMPLE_FRAMES = DEFAULTS["static_mask_sample_frames"]
STATIC_MASK_OVERLAP_THRESHOLD = DEFAULTS["static_mask_overlap_threshold"]
STATIC_MASK_OCCUPANCY_THRESHOLD = DEFAULTS["static_mask_occupancy_threshold"]
STATIC_MASK_BUILD_BLOCK_SIZE = DEFAULTS["static_mask_build_block_size"]
STATIC_MASK_BUILD_CONSTANT = DEFAULTS["static_mask_build_constant"]
STATIC_MASK_BUILD_BLUR_SIZE = DEFAULTS["static_mask_build_blur_size"]
STATIC_MASK_BUILD_MIN_AREA = DEFAULTS["static_mask_build_min_area"]
STATIC_MASK_BUILD_MAX_AREA = DEFAULTS["static_mask_build_max_area"]
STATIC_BOTTOM_EXCLUSION_PX = DEFAULTS["static_bottom_exclusion_px"]
OUTPUT_FOLDER_TEMPLATE = DEFAULTS["output_folder_template"]
OUTPUT_FILENAME_TEMPLATE = DEFAULTS["output_filename_template"]
SEARCH_RADIUS = DEFAULTS["search_radius"]
OUTPUT_VIDEO_BASENAME = DEFAULTS["output_video_basename"]
PRESET_SCALE = DEFAULTS["preset_scale"]
DEFAULT_N_TUBES = DEFAULTS["default_n_tubes"]
TUBE_HALF_W = DEFAULTS["tube_half_w"]
TUBE_HALF_H = DEFAULTS["tube_half_h"]
ACTIVE_PRESET = DEFAULTS.get("active_preset")
TUBE_ROIS = DEFAULTS["tube_rois"]

def save_roi_preset(rois: list):
    """
    Save a list of (x, y, w, h) ROI tuples into the active preset and into
    config.json so they survive restarts.
 
    rois should be the final (x, y, w, h) tuples as passed to track_fly(),
    not raw click centers -- the GUI constructs them from centers + half-sizes
    before calling this.
 
    If there is no active preset, the ROIs are still saved to config.json
    so the last-used layout persists across restarts even without a named preset.
    """
    # persist to config.json for immediate use
    save_config({"tube_rois": [list(r) for r in rois]})
 
    # also embed in the named preset if one is active
    active = get_config().get("active_preset")
    if active:
        presets = list_presets()
        match = next((p for p in presets if p.get("name") == active), None)
        if match:
            match["tube_rois"] = [list(r) for r in rois]
            save_preset(match)
            print(f"Presets: ROIs saved into preset '{active}'")