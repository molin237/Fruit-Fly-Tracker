import os
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
    Draw tracking results onto a graphical plot
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
        # Make temporary copy from positions tuple
        plot_x = []
        plot_y = []
        for frame_num, cx, cy, distance_cm, velocity_cm_s in positions:
            plot_x.append(cx)
            plot_y.append(cy)
        plot_x = np.array(plot_x)
        plot_y = np.array(plot_y)

        plt.figure(figsize=(5, 7))
        plt.plot(plot_x, plot_y, label=f"{fly_label}")
        plt.xlabel("X Coordinate (px)")
        plt.ylabel("Y Coordinate (px)")
        plt.title("Fruit Fly Path Trace")

        plt.legend(
            title="Experimental Runs",
            loc="upper left",
            fontsize=10,
            frameon=True,
            bbox_to_anchor=(1, 1)
        )
        plt.tight_layout()
        plt.savefig(filepath, dpi=300)
        plt.close()

        print(f"Plot saved to: {filepath}")
        return filepath

    except Exception as e:
        print(f"Plot export failed: {e}")
        return None
    
def export_multi_trace_plot(results, output_dir=None):
    """
    Draw multi-fly tracking results onto a graphical plot
    Displays a graphical representation of multiple flies' position
    within each ROI as it travels up the tube.
 
    Furthermore, performs a normalization so that all fruit fly paths originate
    at the point x=0
 
    args:
        results: list of (positions, summary) tuples returned by track_flies(), in fly_id order (index 0 = fly 1)
        output_dir: override the default output_data/ folder (for testing)
    returns:
        full path to the saved PNG, or None if export failed
    """
    if not results:
        print("Multi export skipped: no results to write.")
        return None
 
    if output_dir is None:
        output_dir = get_output_dir()
 
    filename = generate_plot_filename(multi=True)
    filepath = os.path.join(output_dir, filename)
 
    try:
        for i, (positions, summary) in enumerate(results):
            fly_id = i + 1

            # Make temporary copy from positions tuple
            plot_x = []
            plot_y = []
            for frame_num, cx, cy, distance_cm, velocity_cm_s in positions:
                plot_x.append(cx)
                plot_y.append(cy)
            plot_x = np.array(plot_x)
            plot_y = np.array(plot_y)

            plt.plot(plot_x, plot_y, label=f"Fly {fly_id}")

        plt.xlabel("X Coordinate (px)")
        plt.ylabel("Y Coordinate (px)")
        plt.title("Fruit Fly Multi Path Trace")

        plt.legend(
            title="Experimental Runs",
            loc="best",
            fontsize=10,
            frameon=True
        )
        plt.savefig(filepath, dpi=300)
        plt.close()
 
        print(f"Multi trace plot saved to: {filepath}")
        return filepath
 
    except Exception as e:
        print(f"Multi trace plot export failed: {e}")
        return None