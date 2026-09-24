import os
import cv2
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinterdnd2 import DND_FILES, TkinterDnD
import customtkinter as ctk
from PIL import Image, ImageTk
import queue
 
from tracker.tracking import track_fly, build_run_output_dir
from tracker.multi_tracking import track_flies
from utils.export import export_csv, export_multi_csv
from utils.config import (
    load_config,
    save_config,
    get_config,
    get_app_dir,
    list_presets,
    save_preset,
    load_preset,
    delete_preset,
    save_roi_preset,
    KNOWN_DISTANCE_CM,
    DEFAULT_N_TUBES,
    TUBE_HALF_W,
    TUBE_HALF_H,
    PRESET_SCALE,
    ACTIVE_PRESET,
)
import utils.config as cfg  # imported as module so we always see current values

# help text for '?' in headers
# putting here so that its easy to update if necessary later
HELP_TEXT = {
    "track": (
        "How to track",
        "1. Drop or select a video file.\n\n"
        "2. Calibration: click two points on the preview that are a known "
        "distance apart (e.g. the top and bottom of a tube). "
        "The app computes the cm/pixel scale from those clicks.\n\n"
        "3. ROI (region of interest) selection: "
        "click the center of each tube (multi-fly), "
        "or drag a rectangle around the tube (single-fly).\n\n"
        "4. Click Confirm to start tracking. Results and a CSV are saved "
        "automatically to output_data/ and output_videos/ next to the app.\n\n"
        "Tip: Load a preset first (Presets tab) to skip steps 2-3 entirely."
    ),
    "presets": (
        "About presets",
        "A preset stores the calibration scale, tube dimensions, and ROI "
        "positions for a specific camera + rig combination.\n\n"
        "Workflow to set up a new preset:\n"
        "  1. Click '+ New Preset' and give it a name.\n"
        "  2. Load a video on the Track tab and calibrate (click 2 points).\n"
        "  3. Return here, click Edit on the preset, then 'Use current "
        "Track tab scale' -> Save.\n"
        "  4. Go to the ROI Setup tab to save tube positions.\n\n"
        "Once a preset has a scale and ROIs, loading it before opening a "
        "video will skip all manual steps automatically.\n\n"
        "PIN: a future update will let you save the calibration scale "
        "directly from the Track tab without going through Edit."
    ),
    "roi_setup": (
        "ROI Setup",
        "This tab lets you click tube centers once and save them into a "
        "preset so you never have to click them again.\n\n"
        "Steps:\n"
        "  1. Load a video on the Track tab first.\n"
        "  2. Select the preset to save into and set the tube count.\n"
        "  3. Click 'Start clicking': the app switches to the Track tab "
        "so you can click each tube center on the preview.\n"
        "  4. After all centers are placed, return here and click "
        "'Save ROIs to Preset'.\n\n"
        "Saved ROIs are restored automatically the next time you load "
        "a video with that preset active. You can always Reset and "
        "re-click if the camera position has changed."
    ),
    "parameters": (
        "Detection parameters",
        "These values control how the tracker finds the fly each frame.\n\n"
        "Blur size: smooths the image before thresholding. Increase if "
        "there is a lot of background noise. Must be odd.\n\n"
        "Block size: size of the local area used to compute the adaptive "
        "threshold. Should roughly match the fly's size in pixels. Must be odd.\n\n"
        "Threshold constant: subtracted from the local mean. Higher = "
        "stricter (only very dark blobs detected). Lower = more sensitive.\n\n"
        "Min contour area: contours smaller than this (px²) are ignored "
        "as noise. Increase if small specks are being tracked.\n\n"
        "Search radius: maximum pixel distance the fly can move between "
        "frames before the tracker falls back to the largest visible contour.\n\n"
        "Known distance: the real-world length (cm) of the object you "
        "click during calibration (e.g. the tube).\n\n"
        "Use the Parameter Tuning tool (parameter_tuning.py) to preview "
        "threshold results on your video before committing values here."
    ),
}

def help_btn(parent, tab_key):
    """
    Return a small '?' CTkButton that opens the help dialog for tab_key.
    Reopenable any number of times, just a messagebox.
    """
    title, text = HELP_TEXT[tab_key]
    return ctk.CTkButton(
        parent,
        text="?",
        width=28,
        height=28,
        corner_radius=14,
        font=ctk.CTkFont(size=13, weight="bold"),
        fg_color=("gray75", "gray35"),
        hover_color=("gray65", "gray45"),
        text_color=("gray20", "gray90"),
        command=lambda: messagebox.showinfo(title, text),
    )

root = None
label = None
select_btn = None
preview_canvas = None
results_panel = None
progress_bar = None
progress_label = None
calibration_reset_btn = None
cancel_btn = None
cancel_requested = False
confirm_btn = None # shown after centers are clicked before tracking starts
reset_roi_btn = None # lets user reclick centers without reloading video
n_tubes_var = None
progress_update_pending = False # flag used to avoid a bunch of root.after() calls
                                # set to true when UI update already scheduled

# sidebar tab buttons
tab_buttons = {}
tab_frames = {}
active_tab = None
 
# preset tab widgets that need refreshing
preset_list_frame = None
active_preset_label = None
 
# parameters tab widgets
param_vars = {}   # key:tk.StringVar
 
# ROI setup tab
roi_setup_state = {
    "path": None,
    "centers": [],
    "rois": [],
    "preset_name": None,
}

preview_queue = queue.Queue(maxsize=300)
preview_fps = 30
preview_delay_ms = 33

current_display = {
    "frame_bgr": None,
    "scale": 1.0,
    "offset_x": 0,
    "offset_y": 0,
    "display_w": 0,
    "display_h": 0,
}

locked_display = {
    "scale": 1.0,
    "offset_x": 0,
    "offset_y": 0,
    "display_w": 0,
    "display_h": 0,
}

app_state = {
    "path": None,
    "scale": None,
    "roi": None,
    "tube_centers": [],
    "tube_rois": [],
}

calibration_points = []
roi_start = None
mode = None # can be calibrate, ROI, tube_centers, roi_setup, None
selection_frame = None
selection_locked = False

image_item_id = None
calibration_dot_ids = []
calibration_line_id = None #
roi_rect_id = None
tube_overlay_ids = [] # ids for tube center
bottom_excl_overlay_ids = [] # ids for the live bottom-exclusion band preview

def get_video_fps(path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    if not fps or fps <= 1:
        fps = 30
    return fps

def load_first_frame(path):
    cap = cv2.VideoCapture(path)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    return frame

# canvas overlay functionsd
def clear_calibration_overlay():
    global calibration_dot_ids, calibration_line_id

    for dot_id in calibration_dot_ids:
        preview_canvas.delete(dot_id)
    calibration_dot_ids = []

    if calibration_line_id is not None:
        preview_canvas.delete(calibration_line_id)
        calibration_line_id = None


def clear_roi_overlay():
    global roi_rect_id

    if roi_rect_id is not None:
        preview_canvas.delete(roi_rect_id)
        roi_rect_id = None

def clear_tube_overlay():
    global tube_overlay_ids
    for item_id in tube_overlay_ids:
        preview_canvas.delete(item_id)
    tube_overlay_ids = []

def clear_bottom_exclusion_overlay():
    global bottom_excl_overlay_ids
    for item_id in bottom_excl_overlay_ids:
        preview_canvas.delete(item_id)
    bottom_excl_overlay_ids = []

def redraw_bottom_exclusion_overlay():
    """
    Draw a translucent red band at the bottom of each current tube ROI (or
    the single-fly ROI), showing exactly where static_bottom_exclusion_px
    will cut off detection. Purely visual so you see the effect of the slider immediately. 
    Redrawn on every slider change

    Only covers the multi-fly ROI path (app_state["tube_rois"]), since that's
    the preset-driven workflow this exclusion band was built for. Single-fly
    mode starts tracking immediately on ROI release with no preview window,
    so it isn't connected here
    """
    global bottom_excl_overlay_ids
    clear_bottom_exclusion_overlay()

    px = cfg.STATIC_BOTTOM_EXCLUSION_PX
    if px <= 0:
        return

    rois = app_state.get("tube_rois") or []
    for (rx, ry, rw, rh) in rois:
        band_top_img_y = ry + max(0, rh - px)
        band_bottom_img_y = ry + rh
        cx1, cy1 = image_to_canvas_coords(rx, band_top_img_y)
        cx2, cy2 = image_to_canvas_coords(rx + rw, band_bottom_img_y)
        rect_id = preview_canvas.create_rectangle(
            cx1, cy1, cx2, cy2,
            fill="red", outline="red", stipple="gray50",
        )
        bottom_excl_overlay_ids.append(rect_id)

def redraw_overlay():
    global calibration_dot_ids, calibration_line_id

    clear_calibration_overlay()

    for pt in calibration_points:
        x, y = image_to_canvas_coords(pt[0], pt[1])
        dot_id = preview_canvas.create_oval(
            x - 4, y - 4, x + 4, y + 4,
            fill="lime", outline="lime"
        )
        calibration_dot_ids.append(dot_id)

    if len(calibration_points) == 2:
        x1, y1 = image_to_canvas_coords(*calibration_points[0])
        x2, y2 = image_to_canvas_coords(*calibration_points[1])
        calibration_line_id = preview_canvas.create_line(
            x1, y1, x2, y2,
            fill="lime", width=2
        )

def redraw_tube_overlay():
    """
    redraw tube center dots and ROI boxes
 
    called after every new center click 
    each box is drawn from the stored tube_rois and a dot marks the click
    """
    global tube_overlay_ids
    clear_tube_overlay()
 
    for i, (ix, iy) in enumerate(app_state["tube_centers"]):
        cx, cy = image_to_canvas_coords(ix, iy)
 
        # center dot
        dot_id = preview_canvas.create_oval(
            cx - 4, cy - 4, cx + 4, cy + 4,
            fill="cyan", outline="cyan"
        )
        tube_overlay_ids.append(dot_id)
 
        # fly number label
        num_id = preview_canvas.create_text(
            cx, cy - 10,
            text=str(i + 1),
            fill="cyan",
            font=("Helvetica", 9, "bold"),
        )
        tube_overlay_ids.append(num_id)
 
    for rx, ry, rw, rh in app_state["tube_rois"]:
        cx1, cy1 = image_to_canvas_coords(rx, ry)
        cx2, cy2 = image_to_canvas_coords(rx + rw, ry + rh)
        rect_id = preview_canvas.create_rectangle(
            cx1, cy1, cx2, cy2,
            outline="cyan", width=1,
        )
        tube_overlay_ids.append(rect_id)

    redraw_bottom_exclusion_overlay()

def redraw_roi_setup_overlay():
    """Draw cyan dots + boxes for the ROI Setup tab's click session."""
    global tube_overlay_ids
    clear_tube_overlay()
    centers = roi_setup_state["centers"]
    rois    = roi_setup_state["rois"]
    for i, (ix, iy) in enumerate(centers):
        cx, cy = image_to_canvas_coords(ix, iy)
        tube_overlay_ids.append(
            preview_canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                                        fill="orange", outline="orange"))
        tube_overlay_ids.append(
            preview_canvas.create_text(cx, cy - 10, text=str(i + 1),
                                        fill="orange", font=("Helvetica", 9, "bold")))
    for rx, ry, rw, rh in rois:
        cx1, cy1 = image_to_canvas_coords(rx, ry)
        cx2, cy2 = image_to_canvas_coords(rx + rw, ry + rh)
        tube_overlay_ids.append(
            preview_canvas.create_rectangle(cx1, cy1, cx2, cy2,
                                             outline="orange", width=1))

# convert coordinates
def lock_selection_display():
    global selection_locked

    selection_locked = True
    locked_display["scale"] = current_display["scale"]
    locked_display["offset_x"] = current_display["offset_x"]
    locked_display["offset_y"] = current_display["offset_y"]
    locked_display["display_w"] = current_display["display_w"]
    locked_display["display_h"] = current_display["display_h"]


def unlock_selection_display():
    global selection_locked
    selection_locked = False


def show_frame_on_canvas(frame):
    global image_item_id, selection_frame

    selection_frame = frame.copy()
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    canvas_w = preview_canvas.winfo_width()
    canvas_h = preview_canvas.winfo_height()

    if canvas_w < 10 or canvas_h < 10:
        canvas_w, canvas_h = 900, 700

    h, w = frame_rgb.shape[:2]

    if selection_locked:
        scale = locked_display["scale"]
        new_w = locked_display["display_w"]
        new_h = locked_display["display_h"]
        offset_x = locked_display["offset_x"]
        offset_y = locked_display["offset_y"]
    else:
        scale = min(canvas_w / w, canvas_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        offset_x = (canvas_w - new_w) // 2
        offset_y = (canvas_h - new_h) // 2

    resized = cv2.resize(frame_rgb, (new_w, new_h))

    img = Image.fromarray(resized)
    imgtk = ImageTk.PhotoImage(image=img)

    preview_canvas.imgtk = imgtk

    if image_item_id is None:
        image_item_id = preview_canvas.create_image(offset_x, offset_y, anchor="nw", image=imgtk)
    else:
        preview_canvas.itemconfig(image_item_id, image=imgtk)
        preview_canvas.coords(image_item_id, offset_x, offset_y)

    current_display["frame_bgr"] = frame.copy()
    current_display["scale"] = scale
    current_display["offset_x"] = offset_x
    current_display["offset_y"] = offset_y
    current_display["display_w"] = new_w
    current_display["display_h"] = new_h

    redraw_overlay()


def canvas_to_image_coords(cx, cy):
    scale = current_display["scale"]
    ox = current_display["offset_x"]
    oy = current_display["offset_y"]
    disp_w = current_display["display_w"]
    disp_h = current_display["display_h"]
    frame = current_display["frame_bgr"]

    if frame is None:
        return None

    x = cx - ox
    y = cy - oy

    if x < 0 or y < 0 or x > disp_w or y > disp_h:
        return None

    img_x = int(x / scale)
    img_y = int(y / scale)

    h, w = frame.shape[:2]
    img_x = max(0, min(img_x, w - 1))
    img_y = max(0, min(img_y, h - 1))

    return img_x, img_y


def image_to_canvas_coords(ix, iy):
    scale = current_display["scale"]
    ox = current_display["offset_x"]
    oy = current_display["offset_y"]
    return int(ix * scale + ox), int(iy * scale + oy)

def center_to_roi(cx, cy):
    """
    convert tube center (image coords) to an ROI
 
    forces box to stay within the frame boundaries so tubes near
    the edges dont go out of bounds
    """
    frame = current_display["frame_bgr"]
    if frame is None:
        return None
    fh, fw = frame.shape[:2]
 
    x = max(0, cx - TUBE_HALF_W)
    y = max(0, cy - TUBE_HALF_H)
    x2 = min(fw, cx + TUBE_HALF_W)
    y2 = min(fh, cy + TUBE_HALF_H)
 
    return (x, y, x2 - x, y2 - y)

#functions to edit tkinter canvas
def reset_calibration():
    """
    clear calibration points and overlay so the user can re-click
    hidden again after calibration completes successfully
    """
    global mode
    calibration_points.clear()
    clear_calibration_overlay()
    mode = "calibrate"
    calibration_reset_btn.pack_forget()
    label.configure(text="Click 2 points in preview for calibration")

def on_canvas_click(event):
    global calibration_points, mode, roi_start

    coords = canvas_to_image_coords(event.x, event.y)
    if coords is None:
        return

    # ROI Setup tab
    if mode == "roi_setup":
        n = roi_setup_state.get("n_tubes", cfg.DEFAULT_N_TUBES)
        if len(roi_setup_state["centers"]) < n:
            cx, cy = coords
            roi = center_to_roi(cx, cy)
            if roi is None:
                return
            roi_setup_state["centers"].append((cx, cy))
            roi_setup_state["rois"].append(roi)
            redraw_roi_setup_overlay()
            clicked = len(roi_setup_state["centers"])
            label.configure(text=f"ROI Setup: click tube centers ({clicked}/{n})")
            if clicked >= n:
                mode = None
                label.configure(text=f"All {n} centers placed.\nClick 'Save ROIs' to store.")
                show_roi_setup_save_btn()
        return
 
    # Track tab
    if mode == "calibrate":
        if len(calibration_points) < 2:
            calibration_points.append(coords)
            redraw_overlay()
            if len(calibration_points) == 1:
                calibration_reset_btn.pack(fill="x", padx=10, pady=(0, 4))
            if len(calibration_points) == 2:
                x1, y1 = calibration_points[0]
                x2, y2 = calibration_points[1]
                pixel_distance = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                if pixel_distance <= 0:
                    label.configure(text="Invalid points. Try again.")
                    calibration_points.clear()
                    clear_calibration_overlay()
                    calibration_reset_btn.pack_forget()
                    return
                scale_cm_per_pixel = cfg.KNOWN_DISTANCE_CM / pixel_distance
                app_state["scale"] = scale_cm_per_pixel
                calibration_reset_btn.pack_forget()
                calibration_points.clear()
                clear_calibration_overlay()
                n = n_tubes_var.get()
                if n > 1:
                    mode = "tube_centers"
                    label.configure(
                        text=f"Calibration done\nScale: {scale_cm_per_pixel:.6f} cm/px\n"
                             f"Now click the center of each tube (0/{n})")
                else:
                    mode = "roi"
                    label.configure(
                        text=f"Calibration done\nScale: {scale_cm_per_pixel:.6f} cm/px\n"
                             f"Now drag to select ROI")
 
    elif mode == "roi":
        roi_start = coords
        clear_roi_overlay()
 
    elif mode == "tube_centers":
        n = n_tubes_var.get()
        if len(app_state["tube_centers"]) < n:
            cx, cy = coords
            roi = center_to_roi(cx, cy)
            if roi is None:
                return
            app_state["tube_centers"].append((cx, cy))
            app_state["tube_rois"].append(roi)
            redraw_tube_overlay()
            clicked = len(app_state["tube_centers"])
            if clicked < n:
                label.configure(text=f"Click tube centers ({clicked}/{n})\nTube {clicked} placed")
            else:
                mode = None
                label.configure(text=f"All {n} tubes placed.\nConfirm to start tracking\nor Reset to re-click.")
                confirm_btn.grid()
                reset_roi_btn.grid()


def on_canvas_drag(event):
    global roi_rect_id, roi_start
    if mode != "roi" or roi_start is None:
        return
    coords = canvas_to_image_coords(event.x, event.y)
    if coords is None:
        return
    x1, y1 = roi_start
    x2, y2 = coords
    cx1, cy1 = image_to_canvas_coords(x1, y1)
    cx2, cy2 = image_to_canvas_coords(x2, y2)
    clear_roi_overlay()
    roi_rect_id = preview_canvas.create_rectangle(cx1, cy1, cx2, cy2, outline="yellow", width=2)


def on_canvas_release(event):
    global roi_start, mode
    if mode != "roi" or roi_start is None:
        return

    coords = canvas_to_image_coords(event.x, event.y)
    if coords is None:
        roi_start = None
        return

    x1, y1 = roi_start
    x2, y2 = coords

    rx = min(x1, x2)
    ry = min(y1, y2)
    rw = abs(x2 - x1)
    rh = abs(y2 - y1)

    if rw > 0 and rh > 0:
        app_state["roi"] = (rx, ry, rw, rh)
        label.configure(text=f"ROI selected: x={rx}, y={ry}, w={rw}, h={rh}\nStarting tracking...")
        mode = None
        clear_roi_overlay()
        start_tracking()

    roi_start = None


def on_canvas_resize(event):
    if selection_locked:
        return
    
def reset_tube_selection():
    """
    clear tube centers so the user can re-click
    called by Reset button after all centers are placed
    """
    global mode
    app_state["tube_centers"].clear()
    app_state["tube_rois"].clear()
    clear_tube_overlay()
    clear_bottom_exclusion_overlay()
    confirm_btn.grid_remove()
    reset_roi_btn.grid_remove()
 
    n = n_tubes_var.get()
    mode = "tube_centers"
    label.configure(text=f"Click the center of each tube (0/{n})")

# queue for video preview
def safe_show_frame(frame):
    try:
        preview_queue.put_nowait(frame.copy())
    except queue.Full:
        try:
            preview_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            preview_queue.put_nowait(frame.copy())
        except queue.Full:
            pass


def update_preview():
    try:
        frame = preview_queue.get_nowait()
        show_frame_on_canvas(frame)
    except queue.Empty:
        pass

    root.after(preview_delay_ms, update_preview)

# progress/results
def set_progress(value, status_text=None):
    """
    Updates progress bar and percentage on main thread
 
    uses a pending flag so the tracking thread can call this once per
    per frame without calling root.after() a bunch. the flag is cleared
    after each update runs, allowing the next
 
    args:
        value: float between [0.0, 1.0]
        status_text: string to show instead of flat %
    """
    # threading is really annoying here but i think this works
    # basically only runs when called+thread is unlocked
    global progress_update_pending
 
    if progress_update_pending:
        return
    progress_update_pending = True

    # defaults to value * 100%
    display_text = status_text if status_text else f"{int(value * 100)}%"
 
    def do_update():
        global progress_update_pending
        progress_bar.set(value)
        progress_label.configure(text=display_text)
        progress_update_pending = False
 
    root.after(0, do_update)


def update_results_panel(summary_or_results, csv_path, multi=False):
    """
    Output to the results panel in the bottom half of the left panel
 
    single-fly mode: shows one set of stats
    multi-fly mode: shows all stats across all flies
    (total distance summed, avg velocity averaged, etc.) plus
    a note of how many flies were tracked
 
 
    called via root.after() from the tracking thread so it runs on the
    main thread and is safe to touch tkinter widgets

    args:
    summary_or_results: single summary dict or list of (positions, summary) tuples for multiply flies
    csv_path: path to the saved CSV file
    multi: True if this was a multi-fly run
    """
    for widget in results_panel.winfo_children():
        widget.destroy()
 
    ctk.CTkLabel(
        results_panel,
        text="Results",
        font=ctk.CTkFont(size=14, weight="bold"),
        anchor="w",
    ).pack(fill="x", padx=10, pady=(10, 6))
 
    if multi:
        # add all flies forpanel display
        summaries = [s for _, s in summary_or_results]
        total_dist = sum(s["total_distance_cm"] for s in summaries)
        avg_vel = sum(s["avg_velocity_cm_s"] for s in summaries) / len(summaries)
        avg_pct = sum(s["pct_tracked"] for s in summaries) / len(summaries)
        rows = [
            ("Flies tracked", str(len(summaries))),
            ("Total distance", f"{total_dist:.2f} cm (all flies)"),
            ("Avg velocity",   f"{avg_vel:.2f} cm/s"),
            ("Avg % tracked",  f"{avg_pct:.1f}%"),
        ]
    else:
        summary = summary_or_results

        # each row is a (display name : value string) pair
        rows = [
            ("Distance", f"{summary['total_distance_cm']:.2f} cm"),
            ("Avg velocity", f"{summary['avg_velocity_cm_s']:.2f} cm/s"),
            ("Active time", f"{summary['active_time_s']:.1f} s"),
            ("% tracked", f"{summary['pct_tracked']:.1f}%"),
        ]
 
    for stat_name, stat_value in rows:
        # each row is its own small frame so name and value are side by side
        row_frame = ctk.CTkFrame(results_panel, fg_color="transparent")
        row_frame.pack(fill="x", padx=10, pady=2)
 
        ctk.CTkLabel(
            row_frame,
            text=stat_name,
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray60"),
            anchor="w",
            width=90,
        ).pack(side="left")
 
        ctk.CTkLabel(
            row_frame,
            text=stat_value,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
    # CSV filename is long so im putting it in its own layout
    # using text wrapping (name on one line, filename below)
    csv_frame = ctk.CTkFrame(results_panel, fg_color="transparent")
    csv_frame.pack(fill="x", padx=10, pady=(6, 2))

    ctk.CTkLabel(
        csv_frame,
        text="CSV",
        font=ctk.CTkFont(size=12),
        text_color=("gray50", "gray60"),
        anchor="w",
    ).pack(fill="x")
 
    ctk.CTkLabel(
        csv_frame,
        text=os.path.basename(csv_path) if csv_path else "export failed",
        font=ctk.CTkFont(size=11, weight="bold"),
        anchor="w",
        wraplength=200,  # arbitrarily wraping at 200px, within 250px left panel
        justify="left",
    ).pack(fill="x")

# separate threads/functions for tracking

def request_cancel():
    global cancel_requested
    cancel_requested = True
    cancel_btn.pack_forget()
    label.configure(text="Cancelling after current fly...")

def run_tracking(path, scale, roi):
    """
    Single fly tracking thread
    """
    try:
        # find output_videos folder, one subfolder per run
        project_root = get_app_dir()
        base_output_dir = os.path.join(project_root, "output_videos")
        output_dir = build_run_output_dir(base_output_dir, path)

        positions, summary = track_fly(
            path,
            scale,
            output_dir=output_dir,
            show_live=False,
            roi=roi,
            frame_callback=safe_show_frame,
            progress_callback=set_progress,
        )

        # export CSV and return path
        # fly label = None for now since we are doing 1 fly
        # whem multi fly tracking starts we just label fly_label="fly_0x" etc.

        csv_path = export_csv(positions, summary, fly_label=None)
        
        # when tracking is complete
        root.after(0, lambda: set_progress(1.0))
        root.after(0, lambda: cancel_btn.pack_forget())
        root.after(0, lambda: label.configure(text="Tracking complete!\nSaved to output_videos\nand output_data"))
        root.after(0, lambda: update_results_panel(summary, csv_path))
        root.after(0, lambda: select_btn.configure(state="normal"))

    except Exception as e:
        root.after(0, lambda: cancel_btn.pack_forget())
        root.after(0, lambda: label.configure(text=f"Tracking failed:\n{e}"))
        root.after(0, lambda: select_btn.configure(state="normal"))

def run_multi_tracking(path, scale, rois):
    """
    Multi fly tracking thread
    """
    try:
        # one shared subfolder for every fly in this run, computed once
        # here rather than inside track_flies()'s per-fly loop, so all N
        # tube videos land in the same folder instead of each fly getting
        # its own timestamped folder
        base_output_dir = os.path.join(get_app_dir(), "output_videos")
        output_dir = build_run_output_dir(base_output_dir, path)
 
        n = len(rois)

        # show progress in label
        # overall value is already from track_flies
        # linked to the fly number
        def multi_progress(overall_value):
            current_fly = int(overall_value * n) + 1
            current_fly = min(current_fly, n)
            pct = int((overall_value * n % 1) * 100)
            set_progress(overall_value, status_text=f"Fly {current_fly}/{n}: {pct}%")

        results = track_flies(
            path, scale, rois,
            output_dir=output_dir,
            frame_callback=safe_show_frame,
            progress_callback=multi_progress,
            cancel_flag=lambda: cancel_requested,
        )
 
        csv_path = export_multi_csv(results)
        n_completed = len(results) 
        root.after(0, lambda: set_progress(1.0, status_text="Done"))
        root.after(0, lambda: cancel_btn.pack_forget())
        root.after(0, lambda: label.configure(text=f"Tracking complete.\n{n_completed}/{n} flies tracked.\nSaved to output_videos"))
        root.after(0, lambda: update_results_panel(results, csv_path, multi=True))
        root.after(0, lambda: select_btn.configure(state="normal"))
 
    except Exception as e:
        root.after(0, lambda: cancel_btn.pack_forget())
        root.after(0, lambda: label.configure(text=f"Tracking failed:\n{e}"))
        root.after(0, lambda: select_btn.configure(state="normal"))

def start_tracking():
    """
    Branch into single or multi tracking based on tube count.
    Hides confirm/reset buttons, shows progress bar, disables select.
    """
    global mode, cancel_requested

    cancel_requested = False
    unlock_selection_display()
    confirm_btn.grid_remove()
    reset_roi_btn.grid_remove()

    # reset and show progress bar
    progress_bar.set(0)
    progress_label.configure(text="0%")
    progress_bar.grid()
    progress_label.grid()
    cancel_btn.pack(fill="x", padx=10, pady=(0, 4))

    select_btn.configure(state="disabled")

    # check how many tubes and decide to run multi or single
    n = n_tubes_var.get()
    clear_tube_overlay()
    clear_bottom_exclusion_overlay()

    if n > 1:
        rois = app_state["tube_rois"]
        thread = threading.Thread(
            target=run_multi_tracking,
            args=(app_state["path"], app_state["scale"], rois),
            daemon=True,
        )
    else:
        thread = threading.Thread(
            target=run_tracking,
            args=(app_state["path"], app_state["scale"], app_state["roi"]),
            daemon=True,
        )
 
    thread.start()

def process_video(path):
    """
        Load a video and decide what the user needs to do next
    
        If a preset with a saved scale is active, skip calibration entirely.
        If the preset also has saved tube centers, skip ROI clicking too and
        go straight to Confirm button
    """
    global mode, roi_start, selection_frame
    global preview_fps, preview_delay_ms

    # update app state
    app_state["path"] = path
    app_state["scale"] = None
    app_state["roi"] = None
    app_state["tube_centers"].clear()
    app_state["tube_rois"].clear()

    preview_fps = get_video_fps(path)
    preview_delay_ms = max(1, int(1000 / preview_fps))

    calibration_points.clear()
    roi_start = None
    selection_frame = None

    # reset overlays
    clear_calibration_overlay()
    clear_roi_overlay()
    clear_tube_overlay()
    clear_bottom_exclusion_overlay()
    unlock_selection_display()
    confirm_btn.grid_remove()
    reset_roi_btn.grid_remove()

    frame = load_first_frame(path)
    if frame is None:
        label.configure(text="Could not load video.")
        return

    show_frame_on_canvas(frame)
    lock_selection_display()

    mode = "calibrate"
    label.configure(text="Click 2 points in preview for calibration")

    while not preview_queue.empty():
        try:
            preview_queue.get_nowait()
        except queue.Empty:
            break

    # check for presets
    # if they exist, skip prompting user
    preset_scale = cfg.PRESET_SCALE
    active_name = cfg.ACTIVE_PRESET
    preset_rois = None

    if active_name:
        presets = list_presets()
        match   = next((p for p in presets if p.get("name") == active_name), None)
        if match:
            preset_rois = match.get("tube_rois")  # list of [x,y] or None
 
    n = n_tubes_var.get()
 
    if preset_scale is not None:
        # calibration is known, skip
        app_state["scale"] = preset_scale
 
        if preset_rois and len(preset_rois) >= n and n > 1:
            # ROIs are also known, go straight to Confirm
            for roi in preset_rois[:n]:
                rx, ry, rw, rh = roi
                cx, cy = rx + rw // 2, ry + rh // 2
                app_state["tube_centers"].append((cx, cy))
                app_state["tube_rois"].append(tuple(roi))
            redraw_tube_overlay()
            mode = None
            label.configure(
                text=f"Preset '{active_name}' loaded.\n"
                     f"Scale: {preset_scale:.6f} cm/px\n"
                     f"ROIs auto-filled from preset.\n"
                     f"Confirm or Reset to re-click.")
            confirm_btn.grid()
            reset_roi_btn.grid()
        elif n > 1:
            # scale known but no saved centers, ask user to click centers
            mode = "tube_centers"
            label.configure(
                text=f"Preset '{active_name}' loaded.\n"
                     f"Scale: {preset_scale:.6f} cm/px\n"
                     f"Click the center of each tube (0/{n})")
        else:
            # single fly, scale known, ask for ROI drag
            mode = "roi"
            label.configure(
                text=f"Preset '{active_name}' loaded.\n"
                     f"Scale: {preset_scale:.6f} cm/px\n"
                     f"Drag to select ROI")
    else:
        # no preset scale, full calibration flow
        mode = "calibrate"
        label.configure(text="Click 2 points in preview for calibration")


def select_file():
    filetypes = [("Video files", "*.mp4 *.mov *.avi")] # adding avi as part of requirements
    path = filedialog.askopenfilename(filetypes=filetypes)
    if path:
        process_video(path)


def parse_dnd_files(data):
    data = data.strip()
    if not data:
        return []

    paths = []

    if data.startswith("{") and data.endswith("}"):
        parts = data.split("} {")
        for p in parts:
            p = p.strip("{}")
            if p:
                paths.append(p)
    else:
        paths.extend(data.split())

    return [os.path.normpath(p) for p in paths]


def drop_file(event):
    paths = parse_dnd_files(event.data)

    if not paths:
        label.configure(text="No file detected.")
        return

    path = paths[0]
    ext = os.path.splitext(path)[1].lower()

    if ext not in [".mp4", ".mov", ".avi"]:
        label.configure(text="Please drop an MP4 or MOV file.")
        return

    process_video(path)

# building new tabs on sidebar
def switch_tab(name):
    global active_tab
    active_tab = name
    for tab_name, btn in tab_buttons.items():
        if tab_name == name:
            btn.configure(fg_color=("gray75", "gray30"), font=ctk.CTkFont(size=12, weight="bold"))
        else:
            btn.configure(fg_color="transparent", font=ctk.CTkFont(size=12))
    for tab_name, frame in tab_frames.items():
        if tab_name == name:
            frame.pack(side="right", expand=True, fill="both")
        else:
            frame.pack_forget()
 
 
def make_tab_btn(sidebar, name, icon, label_text, command):
    btn = ctk.CTkButton(
        sidebar,
        text=f"  {icon}  {label_text}",
        anchor="w",
        fg_color="transparent",
        text_color=("gray10", "gray90"),
        hover_color=("gray80", "gray35"),
        font=ctk.CTkFont(size=13),
        command=command,
        height=36,
        corner_radius=6,
    )
    btn.pack(fill="x", padx=6, pady=2)
    tab_buttons[name] = btn
    return btn

# TRACK TAB
def build_track_tab(parent):
    global label, select_btn, results_panel, progress_bar, progress_label
    global cancel_btn, calibration_reset_btn, confirm_btn, reset_roi_btn, n_tubes_var
 
    frame = ctk.CTkFrame(parent, fg_color="transparent")
 
    # split: left control panel + right canvas
    left = ctk.CTkFrame(frame, width=260)
    left.pack(side="left", fill="y", padx=(10, 0), pady=10)
    left.pack_propagate(False)
 
    # drag & drop label
    label = ctk.CTkLabel(
        left, text="Drag & Drop a file here",
        height=120, corner_radius=10,
        fg_color=("gray85", "gray25"),
        font=ctk.CTkFont(size=15, weight="bold"),
        justify="center",
    )
    label.pack(pady=(12, 6), padx=10, fill="x")
    label.drop_target_register(DND_FILES)
    label.dnd_bind("<<Drop>>", drop_file)
 
    # track tab header row with ? button
    track_header = ctk.CTkFrame(left, fg_color="transparent")
    track_header.pack(fill="x", padx=10, pady=(0, 4))
    ctk.CTkLabel(track_header, text="Track", font=ctk.CTkFont(size=13, weight="bold"),
                 anchor="w").pack(side="left")
    help_btn(track_header, "track").pack(side="right")
    
    # tube count
    tube_frame = ctk.CTkFrame(left, fg_color="transparent")
    tube_frame.pack(fill="x", padx=10, pady=(0, 6))
    ctk.CTkLabel(tube_frame, text="Tubes:", font=ctk.CTkFont(size=12),
                 anchor="w", width=50).pack(side="left")
    n_tubes_var = tk.IntVar(value=cfg.DEFAULT_N_TUBES)
    tk.Spinbox(tube_frame, from_=1, to=20, textvariable=n_tubes_var,
               width=4, font=("Helvetica", 12)).pack(side="left", padx=(4, 0))
    ctk.CTkLabel(tube_frame, text="(1 = single fly)",
                 font=ctk.CTkFont(size=10),
                 text_color=("gray50", "gray60"), anchor="w").pack(side="left", padx=(6, 0))
 
    # progress bar
    prog_frame = ctk.CTkFrame(left, fg_color="transparent")
    prog_frame.pack(fill="x", padx=10, pady=(0, 4))
    prog_frame.columnconfigure(0, weight=1)
    progress_bar = ctk.CTkProgressBar(prog_frame, height=14)
    progress_bar.set(0)
    progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    progress_label = ctk.CTkLabel(prog_frame, text="0%",
                                   font=ctk.CTkFont(size=11), width=36, anchor="e")
    progress_label.grid(row=0, column=1)
    progress_bar.grid_remove()
    progress_label.grid_remove()
 
    # confirm/reset buttons
    btn_frame = ctk.CTkFrame(left, fg_color="transparent")
    btn_frame.pack(fill="x", padx=10, pady=(0, 4))
    btn_frame.columnconfigure(0, weight=1)
    btn_frame.columnconfigure(1, weight=1)
    confirm_btn = ctk.CTkButton(btn_frame, text="Confirm", command=start_tracking,
                                 fg_color="green", hover_color="darkgreen")
    confirm_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
    reset_roi_btn = ctk.CTkButton(btn_frame, text="Reset", command=reset_tube_selection,
                                   fg_color=("gray60", "gray40"))
    reset_roi_btn.grid(row=0, column=1, sticky="ew")
    confirm_btn.grid_remove()
    reset_roi_btn.grid_remove()
 
    calibration_reset_btn = ctk.CTkButton(left, text="Reset Calibration",
                                           command=reset_calibration,
                                           fg_color=("gray60", "gray40"))
    calibration_reset_btn.pack_forget()
 
    cancel_btn = ctk.CTkButton(left, text="Cancel Tracking", command=request_cancel,
                                fg_color=("gray60", "gray40"))
    cancel_btn.pack_forget()
 
    select_btn = ctk.CTkButton(left, text="Select File", command=select_file)
    select_btn.pack(pady=6, padx=10, fill="x")
 
    ctk.CTkFrame(left, height=2, fg_color=("gray70", "gray35")).pack(
        fill="x", padx=10, pady=(4, 8))
 
    results_panel = ctk.CTkScrollableFrame(left, fg_color=("gray90", "gray20"))
    results_panel.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 10))
    ctk.CTkLabel(results_panel, text="Results will appear\nhere after tracking.",
                 font=ctk.CTkFont(size=12), text_color=("gray50", "gray60"),
                 justify="center").pack(expand=True, pady=40)
 
    tab_frames["track"] = frame
    return frame

# PRESETS TAB
def build_presets_tab(parent):
    global preset_list_frame, active_preset_label
 
    frame = ctk.CTkFrame(parent, fg_color="transparent")
 
    header = ctk.CTkFrame(frame, fg_color="transparent")
    header.pack(fill="x", padx=16, pady=(14, 4))
    ctk.CTkLabel(header, text="Camera / Rig Presets",
                 font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
    help_btn(header, "presets").pack(side="left", padx=(8, 0))

    active_preset_label = ctk.CTkLabel(
        header, text=active_preset_text(),
        font=ctk.CTkFont(size=12), text_color=("gray50", "gray60"))
    active_preset_label.pack(side="right")
 
    ctk.CTkLabel(frame,
                 text="Presets save the calibration scale, known distance, tube size, and ROI centers.\n"
                      "Load a preset before opening a video to skip manual calibration.",
                 font=ctk.CTkFont(size=12), text_color=("gray50", "gray60"),
                 justify="left", anchor="w").pack(fill="x", padx=16, pady=(0, 10))
 
    preset_list_frame = ctk.CTkScrollableFrame(frame, fg_color="transparent")
    preset_list_frame.pack(fill="both", expand=True, padx=16)
 
    refresh_preset_list()
 
    btn_row = ctk.CTkFrame(frame, fg_color="transparent")
    btn_row.pack(fill="x", padx=16, pady=12)
    ctk.CTkButton(btn_row, text="+ New Preset", command=new_preset_dialog).pack(side="left")
    ctk.CTkButton(btn_row, text="Clear Active", command=clear_active_preset,
                  fg_color=("gray60", "gray40")).pack(side="left", padx=(8, 0))
 
    tab_frames["presets"] = frame
    return frame

def active_preset_text():
    name = get_config().get("active_preset")
    return f"Active: {name}" if name else "No preset loaded"
 
 
def refresh_preset_list():
    if preset_list_frame is None:
        return
    for w in preset_list_frame.winfo_children():
        w.destroy()
    if roi_preset_menu is not None:
        names = preset_name_list()
        roi_preset_menu.configure(values=names)
        # keep current selection if it still exists, else default to active preset
        current = roi_preset_menu.get()
        if current not in names:
            roi_preset_menu.set(get_config().get("active_preset") or (names[0] if names else ""))
    presets = list_presets()
    if not presets:
        ctk.CTkLabel(preset_list_frame, text="No presets saved yet.",
                     font=ctk.CTkFont(size=12), text_color=("gray50", "gray60")).pack(pady=20)
        return
    for p in presets:
        preset_card(p)
 
 
def preset_card(preset):
    name       = preset.get("name", "Unnamed")
    scale      = preset.get("scale")
    n_tubes    = preset.get("n_tubes", "?")
    known_dist = preset.get("known_distance_cm", "?")
    has_rois   = bool(preset.get("tube_rois"))
    is_active  = (cfg.ACTIVE_PRESET == name)
 
    card = ctk.CTkFrame(preset_list_frame,
                         border_width=2 if is_active else 1,
                         border_color=("blue", "dodgerblue") if is_active else ("gray70", "gray40"))
    card.pack(fill="x", pady=5)
 
    ctk.CTkLabel(card, text=name,
                 font=ctk.CTkFont(size=14, weight="bold"), anchor="w").pack(
        fill="x", padx=12, pady=(10, 2))
 
    scale_text = f"{scale:.6f} cm/px" if scale else "Not calibrated"
    roi_text   = f"{len(preset.get('tube_rois', []))} ROIs saved" if has_rois else "No ROIs saved"
    ctk.CTkLabel(card,
                 text=f"Scale: {scale_text}   |   {n_tubes} tubes   |   known dist: {known_dist} cm\n{roi_text}",
                 font=ctk.CTkFont(size=11), text_color=("gray50", "gray60"),
                 anchor="w", justify="left").pack(fill="x", padx=12, pady=(0, 6))
 
    btn_row = ctk.CTkFrame(card, fg_color="transparent")
    btn_row.pack(fill="x", padx=12, pady=(0, 10))
 
    if is_active:
        ctk.CTkLabel(btn_row, text="Active",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=("blue", "dodgerblue")).pack(side="left")
    else:
        ctk.CTkButton(btn_row, text="Load", width=70,
                      command=lambda n=name: load_preset_action(n)).pack(side="left")
 
    ctk.CTkButton(btn_row, text="Edit", width=70,
                  fg_color=("gray60", "gray40"),
                  command=lambda n=name: edit_preset_dialog(n)).pack(side="left", padx=(6, 0))
    ctk.CTkButton(btn_row, text="Delete", width=70,
                  fg_color=("gray60", "gray40"),
                  command=lambda n=name: delete_preset_action(n)).pack(side="left", padx=(6, 0))
 
 
def load_preset_action(name):
    load_preset(name)
    if active_preset_label:
        active_preset_label.configure(text=active_preset_text())
    refresh_preset_list()
    n_tubes_var.set(cfg.DEFAULT_N_TUBES)
 
 
def clear_active_preset():
    save_config({"active_preset": None, "preset_scale": None})
    if active_preset_label:
        active_preset_label.configure(text=active_preset_text())
    refresh_preset_list()
 
 
def delete_preset_action(name):
    if messagebox.askyesno("Delete Preset", f"Delete preset '{name}'?"):
        delete_preset(name)
        refresh_preset_list()
        if active_preset_label:
            active_preset_label.configure(text=active_preset_text())
 
 
def new_preset_dialog():
    name = simpledialog.askstring("New Preset", "Preset name (e.g. iPhone 14 · Rig A):")
    if not name or not name.strip():
        return
    name = name.strip()
    save_preset({
        "name":              name,
        "scale":             None,
        "known_distance_cm": cfg.KNOWN_DISTANCE_CM,
        "n_tubes":           cfg.DEFAULT_N_TUBES,
        "tube_half_w":       cfg.TUBE_HALF_W,
        "tube_half_h":       cfg.TUBE_HALF_H,
        "tube_rois":      None,
    })
    refresh_preset_list()
    messagebox.showinfo("Preset Created",
                        f"'{name}' created.\n\n"
                        "To save a calibration scale:\n"
                        "  1. Load a video on the Track tab\n"
                        "  2. Click two calibration points\n"
                        "  3. Return here and click Edit -> Save Scale\n\n"
                        "To save ROI centers, use the ROI Setup tab.")
 
 
def edit_preset_dialog(name):
    presets = list_presets()
    preset  = next((p for p in presets if p.get("name") == name), None)
    if not preset:
        return
 
    win = ctk.CTkToplevel(root)
    win.title(f"Edit Preset: {name}")
    win.geometry("380x340")
    win.grab_set()
 
    fields = {}
    def row(label_text, key, default):
        r = ctk.CTkFrame(win, fg_color="transparent")
        r.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(r, text=label_text, width=160, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(preset.get(key, default) or ""))
        ctk.CTkEntry(r, textvariable=var).pack(side="left", fill="x", expand=True)
        fields[key] = var
 
    ctk.CTkLabel(win, text=f"Editing: {name}",
                 font=ctk.CTkFont(size=14, weight="bold")).pack(padx=16, pady=(14, 6))
 
    row("Scale (cm/px)",         "scale",              "")
    row("Known distance (cm)",   "known_distance_cm",  cfg.KNOWN_DISTANCE_CM)
    row("Number of tubes",       "n_tubes",            cfg.DEFAULT_N_TUBES)
    row("Tube half-width (px)",  "tube_half_w",        cfg.TUBE_HALF_W)
    row("Tube half-height (px)", "tube_half_h",        cfg.TUBE_HALF_H)
 
    # "Use current scale" convenience button
    def use_current_scale():
        s = app_state.get("scale")
        if s:
            fields["scale"].set(f"{s:.8f}")
        else:
            messagebox.showinfo("No Scale", "Calibrate on the Track tab first.")
 
    ctk.CTkButton(win, text="Use current Track tab scale",
                  command=use_current_scale).pack(padx=16, pady=(4, 0))
 
    def save():
        try:
            scale_raw = fields["scale"].get().strip()
            scale_val = float(scale_raw) if scale_raw else None
            updated = {
                "name": name,
                "scale": scale_val,
                "known_distance_cm": float(fields["known_distance_cm"].get()),
                "n_tubes": int(fields["n_tubes"].get()),
                "tube_half_w": int(fields["tube_half_w"].get()),
                "tube_half_h": int(fields["tube_half_h"].get()),
                "tube_rois": preset.get("tube_rois"),
            }
            save_preset(updated)
            # if this is the active preset, refresh the live config too
            if cfg.ACTIVE_PRESET == name:
                load_preset(name)
            refresh_preset_list()
            win.destroy()
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
 
    ctk.CTkButton(win, text="Save", command=save).pack(pady=12)

# ROI SETUP TAB
roi_save_btn = None
roi_preset_menu = None # OptionMenu in ROI setup tab is refreshed with refresh_preset_list
 
 
def build_roi_setup_tab(parent):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
 
    roi_header = ctk.CTkFrame(frame, fg_color="transparent")
    roi_header.pack(fill="x", padx=16, pady=(14, 2))
    ctk.CTkLabel(roi_header, text="ROI Setup",
                 font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
    help_btn(roi_header, "roi_setup").pack(side="left", padx=(8, 0))

    ctk.CTkLabel(frame,
                 text="Click tube centers on the preview to save ROI positions into a preset.\n"
                      "These centers are reused every run, no re-clicking needed.",
                 font=ctk.CTkFont(size=12), text_color=("gray50", "gray60"),
                 justify="left", anchor="w").pack(fill="x", padx=16, pady=(0, 10))
    
    ctrl = ctk.CTkFrame(frame, fg_color="transparent")
    ctrl.pack(fill="x", padx=16, pady=(0, 8))
 
    # preset selector
    ctk.CTkLabel(ctrl, text="Save into preset:", font=ctk.CTkFont(size=12)).pack(
        side="left")
    preset_var = tk.StringVar(value=cfg.ACTIVE_PRESET or "")
    preset_menu = ctk.CTkOptionMenu(ctrl, variable=preset_var,
                                     values=preset_name_list(),
                                     width=180)
    preset_menu.pack(side="left", padx=(8, 0))
 
    # tube count
    ctk.CTkLabel(ctrl, text="  Tubes:", font=ctk.CTkFont(size=12)).pack(side="left")
    roi_n_var = tk.IntVar(value=cfg.DEFAULT_N_TUBES)
    tk.Spinbox(ctrl, from_=1, to=20, textvariable=roi_n_var,
               width=4, font=("Helvetica", 12)).pack(side="left", padx=(4, 0))
 
    def start_roi_setup():
        global mode
        pname = preset_var.get().strip()
        if not pname:
            messagebox.showwarning("No Preset", "Select a preset to save ROIs into.")
            return
        path = app_state.get("path")
        if not path:
            messagebox.showwarning("No Video", "Load a video on the Track tab first.")
            return
        n = roi_n_var.get()
        roi_setup_state["centers"].clear()
        roi_setup_state["rois"].clear()
        roi_setup_state["preset_name"] = pname
        roi_setup_state["n_tubes"]     = n
        clear_tube_overlay()
        if roi_save_btn:
            roi_save_btn.pack_forget()
        mode = "roi_setup"
        label.configure(text=f"ROI Setup: click tube centers (0/{n})")
        switch_tab("track")  # bring canvas into view
 
    ctk.CTkButton(ctrl, text="Start clicking",
                  command=start_roi_setup).pack(side="left", padx=(12, 0))
 
    # save button shown by show_roi_setup_save_btn() after all centers placed
    global roi_save_btn, roi_preset_menu
    roi_preset_menu = preset_menu
 
    def save_rois():
        pname = roi_setup_state.get("preset_name")
        centers = roi_setup_state.get("centers", [])

        if not pname or not centers:
            return

        # ensure this preset is active before saving
        load_preset(pname)

        # build ROIs from centers
        rois = []

        half_w = get_config().get("tube_half_w", cfg.TUBE_HALF_W)
        half_h = get_config().get("tube_half_h", cfg.TUBE_HALF_H)
        frame = current_display["frame_bgr"]

        if frame is not None:
            frame_h, frame_w = frame.shape[:2]
            for cx, cy in centers:
                x  = max(0, cx - half_w)
                y  = max(0, cy - half_h)
                x2 = min(frame_w, cx + half_w)
                y2 = min(frame_h, cy + half_h)
                rois.append((x, y, x2 - x, y2 - y))
        else:
            for cx, cy in centers:
                rois.append((cx - half_w, cy - half_h, half_w * 2, half_h * 2))


        save_roi_preset(rois)
        refresh_preset_list()

        messagebox.showinfo(
            "Saved",
            f"{len(rois)} ROIs saved into '{pname}'."
        )

        roi_setup_state["centers"].clear()
        roi_setup_state["rois"].clear()

        clear_tube_overlay()

        if roi_save_btn:
            roi_save_btn.pack_forget()
 
    roi_save_btn = ctk.CTkButton(frame, text="Save ROIs to Preset",
                                   command=save_rois,
                                   fg_color="green", hover_color="darkgreen")
 
    tab_frames["roi_setup"] = frame
    return frame
 
 
def show_roi_setup_save_btn():
    if roi_save_btn:
        roi_save_btn.pack(padx=16, pady=(0, 8), anchor="w")
 
 
def preset_name_list():
    return [p.get("name", "") for p in list_presets()] or ["(no presets)"]

# PARAMETERS TAB
def build_parameters_tab(parent):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
 
    param_header = ctk.CTkFrame(frame, fg_color="transparent")
    param_header.pack(fill="x", padx=16, pady=(14, 2))
    ctk.CTkLabel(param_header, text="Detection Parameters",
                 font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
    help_btn(param_header, "parameters").pack(side="left", padx=(8, 0))

    ctk.CTkLabel(frame,
                 text="Adjust these if tracking quality is poor.\n"
                      "Changes take effect on the next tracking run.\n"
                      "Save to persist between sessions.",
                 font=ctk.CTkFont(size=12), text_color=("gray50", "gray60"),
                 justify="left", anchor="w").pack(fill="x", padx=16, pady=(0, 10))
 
    params = [
        ("Blur size (odd)",        "gaussian_blur_size",  "GaussianBlur kernel. Higher = more smoothing."),
        ("Block size (odd)",       "adaptive_block_size", "Adaptive threshold neighborhood size."),
        ("Threshold constant",     "adaptive_constant",   "Subtracted from local mean. Higher = stricter."),
        ("Min contour area (px²)", "min_contour_area",    "Ignore contours smaller than this."),
        ("Max contour area (px²)", "max_contour_area",    "Ignore contours larger than this (merged flies, shadows)."),
        ("Search radius (px)",     "search_radius",       "Max jump between frames before fallback."),
        ("Known distance (cm)",    "known_distance_cm",   "Length of calibration reference object."),
        ("Output folder naming",   "output_folder_template",   "Tokens: {video_name} {basename} {timestamp}"),
        ("Output file naming",     "output_filename_template", "Tokens: {video_name} {basename} {fly_label} {timestamp}"),
    ]
 
    cfg_data = get_config()
 
    scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
    scroll.pack(fill="both", expand=True, padx=16)
 
    for display_name, key, hint in params:
        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(fill="x", pady=6)
        left_col = ctk.CTkFrame(row, fg_color="transparent")
        left_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left_col, text=display_name,
                     font=ctk.CTkFont(size=13), anchor="w").pack(anchor="w")
        ctk.CTkLabel(left_col, text=hint,
                     font=ctk.CTkFont(size=11),
                     text_color=("gray50", "gray60"), anchor="w").pack(anchor="w")
        var = tk.StringVar(value=str(cfg_data.get(key, "")))
        param_vars[key] = var
        entry_width = 220 if key.endswith("_template") else 80
        ctk.CTkEntry(row, textvariable=var, width=entry_width).pack(side="right", padx=(12, 0))
 
    btn_row = ctk.CTkFrame(frame, fg_color="transparent")
    btn_row.pack(fill="x", padx=16, pady=12)
    ctk.CTkButton(btn_row, text="Save parameters", command=save_parameters).pack(side="left")
    ctk.CTkButton(btn_row, text="Reset to defaults", command=reset_parameters,
                  fg_color=("gray60", "gray40")).pack(side="left", padx=(8, 0))
 
    tab_frames["parameters"] = frame
    return frame
 
 
def save_parameters():
    overrides = {}
    int_keys  = {"gaussian_blur_size", "adaptive_block_size", "adaptive_constant",
                 "min_contour_area", "max_contour_area", "search_radius"}
    float_keys = {"known_distance_cm"}
    try:
        for key, var in param_vars.items():
            val = var.get().strip()
            if key in int_keys:
                v = int(val)
                if key in {"gaussian_blur_size", "adaptive_block_size"} and v % 2 == 0:
                    messagebox.showerror("Invalid", f"{key} must be odd.")
                    return
                overrides[key] = v
            elif key in float_keys:
                overrides[key] = float(val)
            else:
                # plain string setting (e.g. naming templates) -- saved
                # as-is, no numeric parsing
                overrides[key] = val
        save_config(overrides)
        messagebox.showinfo("Saved", "Parameters saved to config.json.")
    except ValueError as e:
        messagebox.showerror("Invalid input", str(e))
 
 
def reset_parameters():
    from utils.config import DEFAULTS
    for key, var in param_vars.items():
        if key in DEFAULTS:
            var.set(str(DEFAULTS[key]))

# quick-access shadow mask / bottom exclusion controls (shown under the
# preview canvas, visible regardless of active tab)
def build_quick_mask_controls(parent):
    """
    Small always-visible strip: a switch for the static shadow/background
    mask, and a slider for the fixed bottom-of-frame exclusion (where a
    tube's bottom slot/shadow physically sits). Both save to config.json
    immediately on change, no separate Save button -- this is meant to be
    a quick toggle/adjust, not a full settings form (that's what the
    Parameters tab is for).
    """
    cfg_data = get_config()

    mask_var = tk.BooleanVar(value=bool(cfg_data.get("use_static_mask", True)))

    def on_mask_toggle():
        save_config({"use_static_mask": bool(mask_var.get())})

    ctk.CTkSwitch(
        parent, text="Shadow mask", variable=mask_var,
        onvalue=True, offvalue=False,
        command=on_mask_toggle,
        font=ctk.CTkFont(size=12),
    ).pack(side="left", padx=(12, 24), pady=10)

    bottom_excl_label = ctk.CTkLabel(
        parent, text="Bottom exclusion:", font=ctk.CTkFont(size=12),
    )
    bottom_excl_label.pack(side="left", padx=(0, 6))

    bottom_excl_value_label = ctk.CTkLabel(
        parent, text=f"{int(cfg_data.get('static_bottom_exclusion_px', 80))}px",
        font=ctk.CTkFont(size=12), width=44, anchor="w",
    )

    def on_bottom_excl_change(value):
        v = int(float(value))
        bottom_excl_value_label.configure(text=f"{v}px")
        save_config({"static_bottom_exclusion_px": v})
        redraw_bottom_exclusion_overlay()

    bottom_excl_slider = ctk.CTkSlider(
        parent, from_=0, to=400, number_of_steps=400,
        command=on_bottom_excl_change, width=180,
    )
    bottom_excl_slider.set(int(cfg_data.get("static_bottom_exclusion_px", 80)))
    bottom_excl_slider.pack(side="left", padx=(0, 8), pady=10)

    bottom_excl_value_label.pack(side="left", padx=(0, 12))


# main build ui
def build_ui():
    """
    Construct and launch the main GUI window.
    Previously, this was not in a function so it would 
    run the moment gui.py would be called.

    left panel is split into two sections:
        - top: drag & drop label, progress bar, select file, status text
        - bottom: results panel, updates after tracking completes
    """
    global root
 
    load_config()
 
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
 
    root = TkinterDnD.Tk()
    root.geometry("1500x860")
    root.title("Fruit Fly Tracker")
 
    # sidebar
    sidebar = ctk.CTkFrame(root, width=190, corner_radius=0,
                            fg_color=("gray92", "gray18"))
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)
 
    ctk.CTkLabel(sidebar, text="Fly Tracker",
                 font=ctk.CTkFont(size=15, weight="bold")).pack(
        pady=(18, 4), padx=10)
    ctk.CTkFrame(sidebar, height=1, fg_color=("gray75", "gray35")).pack(
        fill="x", padx=10, pady=(0, 8))
 
    ctk.CTkLabel(sidebar, text="MAIN", font=ctk.CTkFont(size=10),
                 text_color=("gray55", "gray55")).pack(anchor="w", padx=14, pady=(4, 0))
 
    # tab content area
    content_area = ctk.CTkFrame(root, fg_color="transparent")
    content_area.pack(side="left", expand=True, fill="both")
 
    # right panel: canvas always visible on the right
    right_frame = ctk.CTkFrame(root)
    right_frame.pack(side="right", expand=True, fill="both", padx=10, pady=10)
 
    # quick-access strip for the static shadow-mask toggle and slider
    # next to the preview where the tube bottoms are actually visible
    # Packed with side="bottom" BEFORE the canvas below so it reserves its
    # own fixed strip; the canvas then fills whatever space remains above it.
    quick_strip = ctk.CTkFrame(right_frame, fg_color=("gray88", "gray22"))
    quick_strip.pack(side="bottom", fill="x", pady=(8, 0))
    build_quick_mask_controls(quick_strip)
 
    global preview_canvas
    preview_canvas = tk.Canvas(right_frame, bg="black", highlightthickness=0)
    preview_canvas.pack(expand=True, fill="both")
    preview_canvas.bind("<Button-1>",        on_canvas_click)
    preview_canvas.bind("<B1-Motion>",       on_canvas_drag)
    preview_canvas.bind("<ButtonRelease-1>", on_canvas_release)
    preview_canvas.bind("<Configure>",       on_canvas_resize)
 
    # build tab frames (order matters for pack)
    build_track_tab(content_area)
    build_presets_tab(content_area)
    build_roi_setup_tab(content_area)
    build_parameters_tab(content_area)
 
    # sidebar buttons (after frames exist)
    make_tab_btn(sidebar, "track", "▶",  "Track",      lambda: switch_tab("track"))
    make_tab_btn(sidebar, "presets", "*", "Presets",    lambda: switch_tab("presets")) # i'd like to find unicode to put in place of * here
 
    ctk.CTkLabel(sidebar, text="ADVANCED", font=ctk.CTkFont(size=10),
                 text_color=("gray55", "gray55")).pack(anchor="w", padx=14, pady=(10, 0))
    make_tab_btn(sidebar, "roi_setup", "*", "ROI Setup",  lambda: switch_tab("roi_setup"))
    make_tab_btn(sidebar, "parameters", "*", "Parameters", lambda: switch_tab("parameters"))
 
    switch_tab("track")  # default tab

    root.after(preview_delay_ms, update_preview)
    root.mainloop()