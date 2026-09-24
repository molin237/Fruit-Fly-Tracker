import numpy as np
import cv2
import os
from pathlib import Path
from datetime import datetime


from utils.config import get_app_dir
import utils.config as cfg  # imported as module (not `from X import Y`) so we
                             # always see current values. see note below

# NOTE on config access: this file used to do `from utils.config import
# MIN_CONTOUR_AREA` etc. That copies the value in at the moment this file
# is first imported (which happens early, when gui.py's own imports run
# before gui.py calls load_config()). Once copied, those names never update again even after
# load_config() runs or the user changes a setting via the GUI later. All
# config reads in this file go through cfg.SOMETHING instead, which looks
# up the current value on the config module itself every time, matching
# the pattern gui.py already uses for the same reason. Default ARGUMENT
# VALUES in function signatures are a separate issue even with this
# pattern (they're evaluated once, at def time, no matter what expression
# is on the right-hand side), so those still resolve via a None vslue
# inside the function body instead of `param=cfg.SOMETHING` in the
# signature. see search_radius/use_static_mask/bottom_exclusion_px below.

# Fixed-width black panel appended to the right of the annotated output
# video, wide enough to fit the metrics text without clipping. Multi-fly
# runs crop each output to a single tube's width 
# (e.g. ~84px with default ROI settings)
# Since the metrics text is always roughly the same length
# a fixed panel width works rather than needing per-frame sizing.
TEXT_PANEL_WIDTH_PX = 260


def _clean_filename_parts(name):
    """
    Collapse repeated separators left behind when a template token is
    empty (e.g. fly_label in single-fly mode produces "..._tracked__2026"),
    and strip leading/trailing separators.
    """
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_ ")


def build_run_output_dir(base_output_dir, video_path):
    """
    Build (and create) ONE output subfolder for an entire tracking RUN,
    using OUTPUT_FOLDER_TEMPLATE (config). Call this once per run -- e.g.
    once in the GUI before starting single- or multi-fly tracking -- and
    pass the result in as output_dir to track_fly()/track_flies(). Every
    fly in a multi-fly run then lands in the same folder, since they all
    share the output_dir they were given, rather than each fly computing
    its own timestamp and ending up in a different folder.

    args:
        base_output_dir: the parent folder (e.g. output_videos/)
        video_path: path to the input video, used for the {video_name} token
    returns:
        full path to the created run folder
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    video_name = Path(os.path.basename(video_path)).stem if video_path else "video"

    try:
        folder_name = cfg.OUTPUT_FOLDER_TEMPLATE.format(
            video_name=video_name, basename=cfg.OUTPUT_VIDEO_BASENAME, timestamp=timestamp,
        )
    except (KeyError, IndexError) as e:
        # bad/unknown token in a user-edited template -- fall back to the
        # safe default rather than crashing a run over a typo in Settings
        print(f"Warning: invalid output_folder_template ({e}), using default")
        folder_name = f"{video_name}_{timestamp}"

    folder_name = _clean_filename_parts(folder_name)
    run_dir = os.path.join(base_output_dir, folder_name)
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def build_output_path(output_dir, fly_label=None, input_video=None):
    """
    Build a per-fly output video filename inside output_dir (which should
    already be a run-specific folder from build_run_output_dir(), not the
    bare output_videos/ base). Filename comes from OUTPUT_FILENAME_TEMPLATE
    (config), tokens: {video_name} {basename} {fly_label} {timestamp}.

    Examples with the default template:
        IMG_5323_tracked_output_fly_01_2026-04-11_14-32-05.mp4
        IMG_5323_tracked_output_2026-04-11_14-32-05.mp4   (single-fly, no label)

    args:
        output_dir: directory to save the video in (a run folder)
        fly_label:  optional label for multi-fly runs ("fly_01")
        input_video: video filename stem, for the {video_name} token
    returns:
        full path string
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    video_name = input_video or "video"
    fly_label_str = fly_label or ""

    try:
        filename = cfg.OUTPUT_FILENAME_TEMPLATE.format(
            video_name=video_name,
            basename=cfg.OUTPUT_VIDEO_BASENAME,
            fly_label=fly_label_str,
            timestamp=timestamp,
        )
    except (KeyError, IndexError) as e:
        print(f"Warning: invalid output_filename_template ({e}), using default")
        filename = f"{video_name}_{cfg.OUTPUT_VIDEO_BASENAME}_{fly_label_str}_{timestamp}"

    filename = _clean_filename_parts(filename) + ".mp4"
    return os.path.join(output_dir, filename)


def build_static_exclusion_mask(video_path, roi=None, sample_frames=None,
                                 block_size=None, constant=None, blur_size=None,
                                 min_area=None, max_area=None,
                                 occupancy_threshold=None):
    """
    Sample frames spread across the video, run each one through the SAME
    detection pipeline used for real tracking (blur -> adaptive threshold ->
    morphology -> contour + area filtering), and keep a running count of how
    often each pixel ends up inside an accepted contour. Any pixel flagged
    in a very high fraction of sampled frames gets marked as excluded.

    This replaced an earlier brightness/median-based version. That approach
    turned out to be a poor fit for small, localized shadows (like tube-slot
    shadows): a single global brightness cutoff (Otsu) doesn't reliably
    isolate a small dark patch against a much bigger bright background, and
    a cleanup step meant to remove speckle ended up erasing the shadow
    region itself since it was small/thin. This version sidesteps both
    problems by working in the same "was this flagged as a blob" space as
    the actual bug, rather than raw pixel brightness -- so it isn't thrown
    off by a shadow that flickers frame to frame or fractures into 2+
    separate contours that still cover roughly the same area, both of which
    a shape- or brightness-based approach struggles with.

    This is intentionally NOT a continuously-adaptive background model
    (like cv2.BackgroundSubtractorMOG2). Those keep updating what counts as
    "background" frame to frame, so a fly that stays still for more than a
    couple seconds gradually gets absorbed into the background and stops
    being detected. This mask is computed once, up front, from a fixed
    sample, and never changes after that.

    Caveat: if a fly sits in the exact same spot for nearly the whole
    video, this can't tell it apart from a real shadow. Real tradeoff, not
    a bug, worth knowing about if a specific video's numbers look off.

    args:
        video_path: path to input video
        roi: optional (x, y, w, h), same crop used by the main tracking loop
        sample_frames: how many frames to sample. Defaults to config.
        block_size, constant, blur_size: adaptive-threshold params to use
            while sampling. Default to a SEPARATE, deliberately looser
            profile (config's static_mask_build_* keys) rather than the
            main detection settings -- detection wants to be strict (few
            false positives), but building a good mask wants the opposite:
            loose enough to see the whole shadow as one solid, consistent
            blob instead of small fragments that shift frame to frame and
            never reliably accumulate occupancy. The parameter-tuning tool
            passes its current slider values instead, so you can interactively
            find a good mask-building profile the same way you tune detection.
        min_area, max_area: contour area filter to use while sampling.
            Same default-to-config behavior as above.
        occupancy_threshold: fraction of sampled frames (0.0-1.0) a pixel
            must be flagged in to be marked excluded. Defaults to config.

    returns:
        uint8 mask, same size as the (ROI-cropped) frame, 255 = excluded
        region, 0 = normal. Returns None if there weren't enough readable
        frames to build a reliable mask (static-mask filter is then simply
        skipped for this video).
    """
    # Resolve defaults here, at call time, rather than in the function
    # signature. Using module constants directly as default argument
    # values would freeze them at import time if config.py's apply()
    # rebinds these later (e.g. the GUI saving new Parameters-tab values
    # mid-session). a signature default would keep using the
    # stale value it had at import. Reading them inside the function body
    # picks up whatever the current value is at call time.
    if sample_frames is None:
        sample_frames = cfg.STATIC_MASK_SAMPLE_FRAMES
    if block_size is None:
        block_size = cfg.STATIC_MASK_BUILD_BLOCK_SIZE
    if constant is None:
        constant = cfg.STATIC_MASK_BUILD_CONSTANT
    if blur_size is None:
        blur_size = cfg.STATIC_MASK_BUILD_BLUR_SIZE
    if min_area is None:
        min_area = cfg.STATIC_MASK_BUILD_MIN_AREA
    if max_area is None:
        max_area = cfg.STATIC_MASK_BUILD_MAX_AREA
    if occupancy_threshold is None:
        occupancy_threshold = cfg.STATIC_MASK_OCCUPANCY_THRESHOLD

    # block size and blur size must be odd for cv2; guard against a caller
    # (e.g. a live slider mid-drag) passing an even value
    block_size = max(3, block_size + 1 if block_size % 2 == 0 else block_size)
    blur_size = max(1, blur_size + 1 if blur_size % 2 == 0 else blur_size)

    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total <= 0:
        cap.release()
        return None

    n_samples = min(sample_frames, total)
    step = max(1, total // n_samples)

    occupancy = None
    n_read = 0
    frame_idx = 0

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    while n_read < n_samples and frame_idx < total:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        if roi:
            x, y, w, h = roi
            frame = frame[y:y + h, x:x + w]

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY_INV, block_size, constant,
        )
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if occupancy is None:
            occupancy = np.zeros(gray.shape, dtype=np.uint16)

        # draw this frame's accepted contours into a scratch mask, then add
        # it in, rather than incrementing per-contour, so overlapping
        # contours in one frame don't double-count a pixel
        frame_hits = np.zeros(gray.shape, dtype=np.uint8)
        for c in contours:
            area = cv2.contourArea(c)
            if area <= min_area or area > max_area:
                continue
            cv2.drawContours(frame_hits, [c], -1, 1, -1)

        occupancy += frame_hits
        n_read += 1
        frame_idx += step

    cap.release()

    # too few samples to trust the occupancy count. Skip the filter rather
    # than risk masking out real fly positions based on noise
    if occupancy is None or n_read < 5:
        return None

    occupancy_fraction = occupancy.astype(np.float32) / n_read
    mask = np.where(occupancy_fraction >= occupancy_threshold, 255, 0).astype(np.uint8)

    # light closing (not opening) to smooth mask edges and bridge tiny
    # gaps between adjacent excluded pixels, without shrinking or erasing
    # small real regions the way an opening did in the previous version
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    return mask


def contour_overlap_fraction(contour, static_mask):
    """
    fraction of a contour's filled area that falls inside the static
    exclusion mask. 1.0 = contour is entirely within the excluded region
    (almost certainly the shadow/slot, not a fly).
    """
    contour_mask = np.zeros_like(static_mask)
    cv2.drawContours(contour_mask, [contour], -1, 255, -1)

    contour_area_px = cv2.countNonZero(contour_mask)
    if contour_area_px == 0:
        return 0.0

    overlap_px = cv2.countNonZero(cv2.bitwise_and(contour_mask, static_mask))
    return overlap_px / contour_area_px


def track_fly(video_path, scale, output_dir=None, fly_label=None,
              show_live=True, roi=None, search_radius=None,
              frame_callback=None, progress_callback=None,
              use_static_mask=None, bottom_exclusion_px=None):
    """
    Track a single fruit fly across video frames using adaptive thresholding and contour detection.

    Detects the fly each frame by thresholding a grayscaled + blurred version of the frame,
    finding contours, and selecting the best candidate based on area and proximity to the
    previous known position. Computes per-frame distance and velocity using the provided
    pixel-to-cm scale and the video's fps.

    reference material:
    https://www.geeksforgeeks.org/computer-vision/getting-started-with-object-tracking-using-opencv/
    https://pyimagesearch.com/2015/05/25/basic-motion-detection-and-tracking-with-python-and-opencv/
    https://docs.opencv.org/4.x/d4/d73/tutorial_py_contours_begin.html
    https://docs.opencv.org/4.x/da/d0c/tutorial_bounding_rects_circles.html

    args:
        video_path: path to input video file (can also be 0 for live webcam feed)
        scale: cm per pixel conversion factor (from calibrate_scale)
        output_path: path to save the annotated output video
        show_live: whether to display tracking in real-time with an opencv window
        roi: optional region of interest as (x, y, width, height)
        search_radius: max pixel distance from previous position to search for next contour
        frame_callback: optional function called with each annotated frame (used by the GUI
                        to render the live preview without a separate opencv window)
        progress_callback: optional function called each time a new frame isread
                           used by GUI for progress bar
        use_static_mask: whether to sample the video up front and exclude
                         persistently-dark regions (shadows, tube slots)
                         from detection. Defaults to the config setting.
        bottom_exclusion_px: always ignore the bottom N pixels of the
                         (ROI-cropped, if applicable) frame, no thresholding
                         involved. Simple deterministic backstop for a tube's
                         bottom slot/shadow. Defaults to the config setting;
                         pass 0 to disable.
    returns:
        tuple of:
            positions: list of (frame_num, cx, cy, distance_cm, velocity_cm_s) tuples,
                       one entry per frame where the fly was successfully detected
            summary:   dict with keys:
                           total_distance_cm, avg_velocity_cm_s, active_time_s,
                           total_frames, tracked_frames, pct_tracked
    """

    cap = cv2.VideoCapture(video_path)

    if search_radius is None:
        search_radius = cfg.SEARCH_RADIUS
    if use_static_mask is None:
        use_static_mask = cfg.USE_STATIC_MASK
    if bottom_exclusion_px is None:
        bottom_exclusion_px = cfg.STATIC_BOTTOM_EXCLUSION_PX

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        print("Warning: FPS metadata missing/invalid. Defaulting to 30 FPS for velocity.")
        fps = 30.0
    fps = int(round(fps))

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if roi:
        x, y, w, h = roi
        width, height = w, h
        print(f"using provided ROI of {w}x{h} starting at ({x}, {y})")

    print(f"video loaded: {width}x{height}, {fps}fps, {total_frames} frames")
    print(f"scale: {scale:.6f} cm/pixel")
    print(f"\nspace=pause, n=next frame, r=reset, q=quit")

    # build output path
    if output_dir is None:
        output_dir = os.path.join(get_app_dir(), "output_videos")
    os.makedirs(output_dir, exist_ok=True)
    video_name = Path(os.path.basename(video_path)).stem
    output_path = build_output_path(output_dir, fly_label, video_name)

    # video writer saves the annotated output
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (width + TEXT_PANEL_WIDTH_PX, height))

    # sample the video up front to find persistently-dark regions (shadows,
    # tube slots, etc.) that would otherwise get picked up as a fly
    static_mask = None
    if use_static_mask:
        static_mask = build_static_exclusion_mask(video_path, roi=roi)
        if static_mask is not None:
            excluded_px = int(np.count_nonzero(static_mask))
            total_px = static_mask.size
            print(f"Static exclusion mask: {excluded_px}/{total_px} px "
                  f"({100 * excluded_px / total_px:.1f}%) flagged as persistent "
                  f"shadow/background and will be ignored during detection")
        else:
            print("Static exclusion mask: not enough frames to build one reliably, skipping")

    # tracking state
    frame_count = 0
    positions = []
    prev_position = None
    total_distance = 0.0
    time_per_frame = 1.0 / fps

    paused = False
    current_frame = None
    next_frame = False

    if show_live:
        cv2.namedWindow("Fly Tracking with Metrics", cv2.WINDOW_NORMAL)

    while True:
        # track whether we actually advanced to a new frame this loop iteration.
        # this prevents double-counting distance/positions when paused.
        frame_advanced = False

        if not paused or next_frame:
            ret, current_frame = cap.read()

            if not ret:
                print("end of video or cannot read frame")
                break

            frame_count += 1
            frame_advanced = True

            # when user hits 'n', re-pause after advancing one frame
            if next_frame:
                next_frame = False
                paused = True

        if current_frame is None:
            break

        frame = current_frame.copy()

        # crop to ROI if provided
        if roi:
            x, y, w, h = roi
            frame = frame[y:y + h, x:x + w]

        # convert to grayscale and blur before thresholding.
        # not resizing video yet because this won't be the setup in the future.
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (cfg.GAUSSIAN_BLUR_SIZE, cfg.GAUSSIAN_BLUR_SIZE), 0)

        # adaptive threshold to detect dark fly on light background.
        # BLOCK SIZE must be odd.
        thresh = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY_INV,  # INV because fly is dark on a light background
            cfg.ADAPTIVE_BLOCK_SIZE,   # block size: local area in px used to calculate threshold per pixel
            cfg.ADAPTIVE_CONSTANT,    # constant subtracted from the mean
        )

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
        # thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)

        # simple, deterministic backstop: always blank out the bottom N
        # pixels, where a tube's bottom slot/shadow physically sits. Done
        # last (after morphology) so nothing can regrow into the excluded
        # band. No thresholding/sampling involved, so it can't be thrown
        # off by lighting or parameter changes the way the mask can.
        if bottom_exclusion_px > 0:
            cutoff = max(0, thresh.shape[0] - bottom_exclusion_px)
            thresh[cutoff:, :] = 0

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        current_position = None
        frame_distance = 0.0
        velocity = 0.0
        selected_contour = None

        if contours:
            # size filter only here. Mask filtering is applied further
            # down, and only as a fallback -- see note below
            area_valid_contours = [
                c for c in contours
                if cfg.MIN_CONTOUR_AREA < cv2.contourArea(c) <= cfg.MAX_CONTOUR_AREA
            ]

            def mask_filtered(candidates):
                """
                Remove contours mostly sitting inside the static exclusion
                mask. Only called when there's no continuity evidence (no
                previous position, or nothing near it) -- an actively
                tracked fly should never get disqualified just because
                it's standing somewhere that's historically been a shadow.
                That's exactly the ambiguity continuity is there to
                resolve, so continuity gets first say, not the mask.
                """
                if static_mask is None:
                    return candidates
                kept = [
                    c for c in candidates
                    if contour_overlap_fraction(c, static_mask) < cfg.STATIC_MASK_OVERLAP_THRESHOLD
                ]
                # if the mask would reject every candidate this frame,
                # fall back to the unfiltered set rather than losing the
                # frame entirely -- an overly aggressive mask should degrade
                # to "no mask" for a frame, not to "no detection"
                return kept if kept else candidates

            if area_valid_contours:
                if prev_position is not None:
                    # prefer contours within search_radius of the previous position.
                    # adds continuity avoids jumping to noise on the other side of the frame.
                    nearby_contours = []
                    for contour in area_valid_contours:
                        M = cv2.moments(contour)
                        if M["m00"] != 0:
                            temp_cx = int(M["m10"] / M["m00"])
                            temp_cy = int(M["m01"] / M["m00"])
                        else:
                            # fall back to bounding box center if moments fail
                            tx, ty, tw, th = cv2.boundingRect(contour)
                            temp_cx = tx + tw // 2
                            temp_cy = ty + th // 2

                        distance_from_prev = np.sqrt(
                            (temp_cx - prev_position[0]) ** 2 +
                            (temp_cy - prev_position[1]) ** 2
                        )
                        if distance_from_prev <= search_radius:
                            nearby_contours.append((contour, distance_from_prev))

                    if nearby_contours:
                        # continuity wins outright: trust the nearest in-radius
                        # match even if it overlaps the static mask
                        selected_contour = min(nearby_contours, key=lambda x: x[1])[0]
                    else:
                        # no continuity match: this is the ambiguous case the
                        # mask exists for (e.g. track was lost and we're
                        # about to guess from scratch)
                        selected_contour = max(mask_filtered(area_valid_contours), key=cv2.contourArea)
                else:
                    # first detection ever, zero continuity info available
                    selected_contour = max(mask_filtered(area_valid_contours), key=cv2.contourArea)

            if selected_contour is not None:
                bx, by, bw, bh = cv2.boundingRect(selected_contour)

                cx = bx + bw // 2
                cy = by + bh // 2
                current_position = (cx, cy)

                if prev_position is not None:
                    pixel_distance = np.sqrt(
                        (cx - prev_position[0]) ** 2 +
                        (cy - prev_position[1]) ** 2
                    )
                    frame_distance = pixel_distance * scale
                    velocity = frame_distance / time_per_frame

                # only update totals once per new frame prevents double counting when paused
                if frame_advanced:
                    if prev_position is not None:
                        total_distance += frame_distance
                    positions.append((frame_count, cx, cy, frame_distance, velocity))
                    prev_position = current_position

                cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 255, 0), 1)
                cv2.circle(frame, (cx, cy), 3, (0, 0, 255), -1)

                label_x = bx
                label_y = max(0, by - 10)  # keep label on-screen if box is near the top
                cv2.putText(frame, "Fly", (label_x, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # compose the tracking frame + a dedicated black panel for metrics
        # text, rather than drawing text over the tracking frame itself.
        # Detection/annotation above all happened on `frame` at its
        # original (possibly narrow, per-tube) width
        canvas = np.zeros((frame.shape[0], frame.shape[1] + TEXT_PANEL_WIDTH_PX, 3), dtype=np.uint8)
        canvas[:, :frame.shape[1]] = frame

        text_x = frame.shape[1] + 10
        y_offset = 30
        metrics = [
            f"Frame: {frame_count}/{total_frames}",
            f"Total Distance: {total_distance:.2f} cm",
            f"Velocity: {velocity:.2f} cm/s",
        ]
        for text in metrics:
            cv2.putText(canvas, text, (text_x, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            y_offset += 30

        if not paused:
            out.write(canvas)

        if frame_callback:
            frame_callback(canvas)

        # honestly not sure if this is hte best way to do it but
        # basically shows progress as a fraction 0.0-1.0 when a frame is read
        if progress_callback and frame_advanced and total_frames > 0:
            progress_callback(frame_count / total_frames)

        if show_live:
            cv2.imshow("Fly Tracking with Metrics", canvas)

            key = cv2.waitKey(30) & 0xFF
            if key == ord("q"):
                print("Tracking stopped by user")
                break
            elif key == ord(" "):
                paused = not paused
                print("PAUSED" if paused else "PLAYING")
            elif key == ord("n") and paused:
                next_frame = True
            elif key == ord("r"):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                frame_count = 0
                total_distance = 0.0
                prev_position = None
                positions = []
                paused = False
                print("Reset to start")

    # summary stats
    # tracked_frames = number of frames where fly was detected
    # active_time_s = how many seconds that represents at video FPS
    # pct_tracked = percentage of total frames successfully tracked

    tracked_frames = len(positions)
    active_time_s = tracked_frames / fps
    denominator = total_frames if total_frames > 0 else frame_count
    pct_tracked = (tracked_frames / denominator * 100) if denominator > 0 else 0.0

    avg_velocity = 0.0

    if positions:
        moving_frames = [p[4] for p in positions if p[4] > 0]
        avg_velocity = float(np.mean(moving_frames)) if moving_frames else 0.0
    
    summary = {
        "total_distance_cm": round(total_distance, 4),
        "avg_velocity_cm_s": round(avg_velocity, 4),
        "active_time_s":     round(active_time_s, 4),
        "total_frames":      total_frames,
        "tracked_frames":    tracked_frames,
        "pct_tracked":       round(pct_tracked, 2),
    }

    # clean up and output results 
    cap.release()
    out.release()
    cv2.destroyAllWindows()

    print(f"\nTRACKING COMPLETE")
    print(f"Processed {frame_count} frames")
    print(f"Total distance traveled: {total_distance:.2f} cm ({total_distance * 10:.2f} mm)")
    print(f"Active time: {active_time_s:.2f}s")
    print(f"Average velocity: {avg_velocity:.2f} cm/s")
    print(f"Output saved to: {output_path}")

    return positions, summary