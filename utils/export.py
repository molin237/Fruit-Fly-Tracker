import os
import csv
from datetime import datetime
from utils.config import get_app_dir


def get_output_dir():
    """
    Return or create path to the output_data folder

    Uses get_app_dir() so this works from source and as an exe from PyInstaller
    """
    output_dir = os.path.join(get_app_dir(), "output_data")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def generate_csv_filename(fly_label=None, multi=False):
    """
    Build a timestamped filename so exports never overwrite each other

    Example outputs:
        fly_tracking_2026-04-11_14-32-05.csv
        fly_tracking_fly_03_2026-04-11_14-32-05.csv (if fly_label is provided)

    args:
        fly_label: optional string identifier for eventual multi-tube runs
    returns:
        filename string (not full path)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if multi:
        return f"fly_tracking_multi_{timestamp}.csv"
    if fly_label:
        return f"fly_tracking_{fly_label}_{timestamp}.csv"
    return f"fly_tracking_{timestamp}.csv"


def export_csv(positions, summary, fly_label=None, output_dir=None):
    """
    Write tracking results to CSV

    The CSV has two sections:
    A header block with summary statistics (total distance, avg velocity, etc.)
    Written as key:value stores so they're easy to read in Excel or pandas

    A Data table with columns:
    frame, timestamp_s, x_px, y_px, distance_cm, velocity_cm_s

    Having both in one file means a researcher can open it and immediately
    see the summary without needing to compute it themselves.

    args:
        positions: list of (frame_num, cx, cy, distance_cm, velocity_cm_s) tuples
                   returned by track_fly()
        summary:   dict returned by track_fly() with keys:
                       total_distance_cm, avg_velocity_cm_s, active_time_s,
                       total_frames, tracked_frames, pct_tracked
        fly_label: optional label string for multi-tube exports (e.g. "fly_03")
        output_dir: override the default output_data/ folder (useful for testing)
    
    returns:
        full path to the saved CSV file, or None if export failed
    """
    if not positions:
        print("Export skipped: no tracking data to write.")
        return None

    if output_dir is None:
        output_dir = get_output_dir()

    filename = generate_csv_filename(fly_label)
    filepath = os.path.join(output_dir, filename)

    try:
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            
            # Summary statistics
            # the blank row after the summary visually separates it from
            # the per-frame data if opened in Excel
            writer.writerow(["# SUMMARY"])
            writer.writerow(["total_distance_cm",  summary["total_distance_cm"]])
            writer.writerow(["total_distance_mm",  round(summary["total_distance_cm"] * 10, 4)])
            writer.writerow(["avg_velocity_cm_s",  summary["avg_velocity_cm_s"]])
            writer.writerow(["active_time_s",       summary["active_time_s"]])
            writer.writerow(["total_frames",        summary["total_frames"]])
            writer.writerow(["tracked_frames",      summary["tracked_frames"]])
            writer.writerow(["pct_tracked",         summary["pct_tracked"]])
            if fly_label:
                writer.writerow(["fly_label", fly_label])
            writer.writerow([])  # blank separator row

            # per-frame data
            # timestamp_s is derived from frame number and FPS so each row
            # has an absolute time reference within the video.
            #
            # note: fps is calculated from active_time_s / tracked_frames
            # to avoid passing fps through as an extra argument. if tracked_frames
            # is 0 we already returned early above, so division is safe.
            fps = summary["tracked_frames"] / summary["active_time_s"] if summary["active_time_s"] > 0 else 30.0

            writer.writerow(["# PER-FRAME DATA"])
            writer.writerow(["frame", "timestamp_s", "x_px", "y_px", "distance_cm", "velocity_cm_s"])

            for frame_num, cx, cy, distance_cm, velocity_cm_s in positions:
                timestamp_s = round(frame_num / fps, 4)
                writer.writerow([
                    frame_num,
                    timestamp_s,
                    cx,
                    cy,
                    round(distance_cm, 6),
                    round(velocity_cm_s, 4),
                ])

        print(f"CSV saved to: {filepath}")
        return filepath

    except Exception as e:
        print(f"CSV export failed: {e}")
        return None
    
def export_multi_csv(results, output_dir=None):
    """
    Write multi-fly tracking results to opne CSV (user req)
 
    export_csv has a summary block + per-frame block for one fly,
    b ut this produces two flat tables that span all flies:
 
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
 
    filename = generate_csv_filename(multi=True)
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