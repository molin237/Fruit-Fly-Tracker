import os
from tracker.tracking import track_fly
from utils.config import get_app_dir


def track_flies(video_path, scale, rois, output_dir=None,
                frame_callback=None, progress_callback=None,
                cancel_flag=None):
    """
    Track N flies sequentially, one ROI at a time (as opposed to
    the previous version that switched threads per frame, really laggy)

    each fly is processed by running track_fly() on its ROI from start
    to finish before moving to the next

    for 20 flies this means the video is read 20 times. for most
    short experiment videos this is acceptable. If video length becomes
    an issue, trying to reintroduce the parallel processing is an option
    maybe worth researching. 

    each fly gets its own output video named with its id and timestamp
    which avoidsn overwriting and other glitches from parallel processing

    Progress is an overall fraction across all flies:
    progress = (flies_done + current_fly_frame_progress) / total_flies
    This still gives a 0.0-1.0 value for the progress bar i ngui

    args:
        video_path: path to input video
        scale: cm/pixel conversion factor
        rois: list of (x, y, w, h) tuples, one per fly. order determines fly_id
        output_dir: directory for annotated output videos. defaults to output_videos
        frame_callback: called with each annotated frame for GUI preview. 
            passed through to track_fly so the preview updates during each fly
        progress_callback: called each time a new frame is read for progress bar

    returns:
        list of (positions, summary) tuples in fly_id order (index 0 = fly 1)
    """
    if output_dir is None:
        output_dir = os.path.join(get_app_dir(), "output_videos")
    os.makedirs(output_dir, exist_ok=True)

    n = len(rois)
    results = []

    for i, roi in enumerate(rois):

        # check cancel between flies
        if cancel_flag and cancel_flag():
            print(f"Cancelled after fly {i}. {i}/{n} flies completed.")
            break

        fly_id = i + 1
        fly_label = f"fly_{fly_id:02d}"

        print(f"\nTracking fly {fly_id}/{n} (label: {fly_label})")

        # add per-fly progress to the 0.0-1.0 range
        # when fly i is at fraction f through its video, overall progress is:
        #(i + f) / n
        # this feels like a roundabout way to do the progress,
        # may be an intermediate spot to add this, but im adding it here
        # after doing the main multi-tracking logic so it may be out of place
        def make_progress_wrapper(fly_index):
            def wrapper(f):
                if progress_callback:
                    progress_callback((fly_index + f) / n)
            return wrapper

        positions, summary = track_fly(
            video_path,
            scale,
            output_dir=output_dir,
            fly_label=fly_label,
            show_live=False,
            roi=roi,
            frame_callback=frame_callback,
            progress_callback=make_progress_wrapper(i),
        )

        # fly_id to summary so export_multi_csv can use it
        # without having to find it from list position
        summary["fly_id"] = fly_id

        results.append((positions, summary))
        print(f"Fly {fly_id} done: "
              f"{summary['total_distance_cm']:.2f} cm, "
              f"{summary['pct_tracked']:.1f}% tracked")

    print(f"\nAll {n} flies tracked.")
    return results