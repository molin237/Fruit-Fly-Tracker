# FlyTracker.spec
#
# PyInstaller spec file for the Fruit Fly Tracker application.
#
# Build command (run from the project root):
#   pyinstaller FlyTracker.spec
#
# Output: dist/FlyTracker/FlyTracker.exe  (Windows one-folder build)
#
# Notes:
#   - One-folder mode (not --onefile) is intentional. onefile unpacks to
#     a temp directory on every launch which is slow and makes output folders
#     harder to find. One-folder gives the sponsor a clean FlyTracker/ dir.
#   - tkinterdnd2 needs its DLL/dylib collected explicitly (see below).
#   - OpenCV (cv2) ships its own DLLs; collect_dynamic_libs handles them.
#   - config.json and presets.json are NOT bundled, they are created by
#     the app at runtime next to the exe (via get_app_dir()).

# ---------------------------------------------------------------------------
# numpy 2.x must be explicitly collected or _core submodules are missed
# ---------------------------------------------------------------------------
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_all

numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all("numpy")
cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all("cv2")

block_cipher = None

# ---------------------------------------------------------------------------
# tkinterdnd2 needs its platform DLL collected alongside the package data
# ---------------------------------------------------------------------------
tkdnd_datas  = collect_data_files("tkinterdnd2")
# collect_dynamic_libs picks up tkdnd2.dll (Windows) / libtkdnd.dylib (Mac)
tkdnd_binaries = collect_dynamic_libs("tkinterdnd2")

# ---------------------------------------------------------------------------
# customtkinter ships image assets that must travel with the package
# ---------------------------------------------------------------------------
ctk_datas = collect_data_files("customtkinter")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[
        *tkdnd_binaries,
        *numpy_binaries,
        *cv2_binaries,
    ],
    datas=[
        *tkdnd_datas,
        *ctk_datas,
        *numpy_datas,
        *cv2_datas,
    ],
    hiddenimports=[
        *numpy_hiddenimports,
        *cv2_hiddenimports,
        # explicit numpy internals that PyInstaller misses with numpy 2.x
        "numpy._core",
        "numpy._core._exceptions",
        "numpy._core._multiarray_umath",
        "numpy._core.multiarray",
        "numpy._core.umath",
        "numpy.core",
        "numpy.core._exceptions",
        # tkinter
        "tkinter",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.simpledialog",
        "tkinterdnd2",
        # PIL / Pillow image formats used by the preview
        "PIL._tkinter_finder",
        "PIL.Image",
        "PIL.ImageTk",
        # OpenCV, the python binding imports the native lib at runtime
        "cv2",
        # our own packages (PyInstaller sometimes misses relative imports)
        "app.gui",
        "tracker.tracking",
        "tracker.multi_tracking",
        "tracker.calibration",
        "utils.config",
        "utils.export",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # dev / test tools not needed in the shipped exe
        "parameter_tuning",
        "unittest",
        "pytest",
        "matplotlib",   # not used; excluding keeps the bundle smaller
        "scipy",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # one-folder mode: binaries go in COLLECT
    name="FlyTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                       # compress binaries if UPX is installed
    console=False,                  # no terminal window for the sponsor
    # icon="assets/icon.ico",       # uncomment and add an .ico if we want an icon
    windows=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FlyTracker",              # dist/FlyTracker/ folder name
)

app = BUNDLE(
    coll,
    name="FlyTracker.app",
    bundle_identifier=None,
    # icon="assets/icon.icns",  # uncomment if for Mac icon
)