import os
import csv
import matplotlib
matplotlib.use("Agg") # Uses Anti-Grain Geometry backend, doesn't show graph when finished processing
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
from utils.config import get_app_dir

def get_output_dir():
    """
    Return or create path to the output_data folder

    Uses get_app_dir() so this works from source and as an exe from PyInstaller
    """
    output_dir = os.path.join(get_app_dir(), "output_plot")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def generate_plot_filename(fly_label=None, multi=False):
    """
    Build a timestamped filename so exports never overwrite each other

    Example outputs:
        fly_tracking_2026-04-11_14-32-05.png
        fly_tracking_fly_03_2026-04-11_14-32-05.png (if fly_label is provided)

    args:
        fly_label: optional string identifier for eventual multi-tube runs
    returns:
        filename string (not full path)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if multi:
        return f"fly_tracking_multi_{timestamp}.png"
    if fly_label:
        return f"fly_tracking_{fly_label}_{timestamp}.png"
    return f"fly_tracking_{timestamp}.png"


def export_trace_plot(positions, fly_label=None, output_dir=None):
    """
    Write tracking results to graphical plot
    Displays a graphical representation of a single fly's position
    within the ROI as it travels up the tube.

    args:
        positions: list of (frame_num, cx, cy, distance_cm, velocity_cm_s) tuples
                       returned by track_fly(), however we are only interested in
                       cx and cy
        fly_label: optional label string for multi-tube exports (e.g. "fly_03")
        output_dir: override the default output_data/ folder (useful for testing)
    
    returns:
        full path to the saved PNG file, or None if export failed
    """
    if not positions:
        print("Export skipped: no tracking data to write.")
        return None

    if output_dir is None:
        output_dir = get_output_dir()

    filename = generate_plot_filename(fly_label)
    filepath = os.path.join(output_dir, filename)

    try:
        tempx = []
        tempy = []

        # Make temporary copy from positions tuple
        for frame_num, cx, cy, distance_cm, velocity_cm_s in positions:
            tempx.append(cx)
            tempy.append(cy)

        tempx = np.array(tempx)
        tempy = np.array(tempy)

        plt.plot(tempx, tempy, label=f"{fly_label}")
        plt.xlabel("X Coordinate")
        plt.ylabel("Y Coordinate")
        plt.title(f"Fruit Fly Path Trace")

        # Reverse the y-axis to show fly moving up the tube
        plt.gca().invert_yaxis()

        plt.legend(
            title="Experimental Runs",
            loc="best",
            fontsize=10,
            frameon=True
        )
        plt.savefig(filepath, dpi=300)
        plt.close()

        print(f"Plot saved to: {filepath}")
        return filepath

    except Exception as e:
        print(f"Plot export failed: {e}")
        return None
    
def export_multi_trace_plot(results, output_dir=None):
    """
    Write multi-fly tracking results to one CSV (user req)
 
    export_csv has a summary block + per-frame block for one fly,
    but this produces two flat tables that span all flies:
 
    1. Summary has one row per fly
    2. Per-frame table has one row per tracked frame per fly,rows are grouped by fly_id then ordered by frame
 
    having fly_id as a column (rather than separate files) makes it easy
    to filter and compare flies in pandas, Excel, or R for future use
 
    args:
        results: list of (positions, summary) tuples returned by track_flies(), in fly_id order (index 0 = fly 1)
        output_dir: override the default output_data/ folder (for testing)
    returns:
        full path to the saved CSV, or None if export failed
    """
    if not results:
        print("Multi export skipped: no results to write.")
        return None
 
    if output_dir is None:
        output_dir = get_output_dir()
 
    filename = generate_plot_filename(multi=True)
    filepath = os.path.join(output_dir, filename)
 
    try:
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
 
            # each fly summary
            writer.writerow(["# SUMMARY (one row per fly)"])
            writer.writerow([
                "fly_id",
                "total_distance_cm", "total_distance_mm",
                "avg_velocity_cm_s", "active_time_s",
                "total_frames", "tracked_frames", "pct_tracked",
            ])
 
            for i, (positions, summary) in enumerate(results):
                fly_id = i + 1
                writer.writerow([
                    fly_id,
                    summary["total_distance_cm"],
                    round(summary["total_distance_cm"] * 10, 4),
                    summary["avg_velocity_cm_s"],
                    summary["active_time_s"],
                    summary["total_frames"],
                    summary["tracked_frames"],
                    summary["pct_tracked"],
                ])
 
            writer.writerow([])
 
            # per-frame data ouiput
            writer.writerow(["# PER-FRAME DATA (one row per tracked frame per fly)"])
            writer.writerow([
                "fly_id", "frame", "timestamp_s",
                "x_px", "y_px", "distance_cm", "velocity_cm_s",
            ])
 
            for i, (positions, summary) in enumerate(results):
                fly_id = i + 1
                fps = (summary["tracked_frames"] / summary["active_time_s"]
                       if summary["active_time_s"] > 0 else 30.0)
 
                for frame_num, cx, cy, distance_cm, velocity_cm_s in positions:
                    timestamp_s = round(frame_num / fps, 4)
                    writer.writerow([
                        fly_id,
                        frame_num,
                        timestamp_s,
                        cx,
                        cy,
                        round(distance_cm, 6),
                        round(velocity_cm_s, 4),
                    ])
 
        print(f"Multi CSV saved to: {filepath}")
        return filepath
 
    except Exception as e:
        print(f"Multi CSV export failed: {e}")
        return None