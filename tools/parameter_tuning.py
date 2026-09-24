from unittest import result

import os
import sys

# When this file is run directly as `python tools/parameter_tuning.py`,
# Python puts this file's own folder (tools/) on sys.path, not the project
# root. tracker/ lives next to tools/, not inside it, so without this the
# import below fails with ModuleNotFoundError even when run from the
# project root as the README instructs.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from tracker.tracking import build_static_exclusion_mask, contour_overlap_fraction

def tune_parameters(video_path):
    """
    Adjust threshold values and see results
    Press SPACE to pause/unpause, 'q' to quit, 's' to save current parameters.
    """
    # open video file
    cap = cv2.VideoCapture(video_path)
    
    # just save first frame
    ret, frame = cap.read()
    if not ret:
        print("Error reading frame")
        return
    
    # ROI variables for mouse slsection
    roi = None
    drawing = False
    ix, iy = -1, -1

    # static exclusion mask state (shadows / tube slots / other fixed dark regions).
    # built lazily on first 'm' press since sampling the video takes a moment,
    # then cached and reused so toggling on/off doesn't rebuild every time
    static_mask = None
    mask_enabled = False

    def draw_roi(event, x, y, flags, param):
        """Mouse callback for drawing region of interest"""
        nonlocal roi, drawing, ix, iy

        if event == cv2.EVENT_LBUTTONDOWN:
            drawing = True
            ix, iy = x, y

        elif event == cv2.EVENT_MOUSEMOVE:
            if drawing:
                roi = (min(ix, x), min(iy, y), abs(x - ix), abs(y - iy))
        
        elif event == cv2.EVENT_LBUTTONUP:
            drawing = False
            roi = (min(ix, x), min(iy, y), abs(x - ix), abs(y - iy))
            print(f"ROI set: x={roi[0]}, y={roi[1]}, width={roi[2]}, height={roi[3]}")


    # new window
    cv2.namedWindow('Original', cv2.WINDOW_NORMAL)
    cv2.namedWindow('Threshold Result', cv2.WINDOW_NORMAL)
    cv2.namedWindow('Parameter Tuning', cv2.WINDOW_NORMAL)
    cv2.namedWindow('Static Mask (shadows/background)', cv2.WINDOW_NORMAL)
    
    # allow moiuse callback for region selectoin
    cv2.setMouseCallback('Parameter Tuning', draw_roi)

    # Default values
    default_block = 15
    default_constant = 3
    default_blur = 7
    default_min_area = 30
    default_max_area = 2000
    default_mask_overlap = 60  # percent
    default_bottom_exclusion = 80  # px
    
    # https://docs.opencv.org/3.4/da/d6a/tutorial_trackbar.html
    # trackbars are basically sliders
    # createTrackbar(trackbarname, winname, value, count (max), onChange)
    cv2.createTrackbar('Block Size', 'Parameter Tuning', default_block, 60, lambda x: None)
    cv2.createTrackbar('Constant', 'Parameter Tuning', default_constant, 20, lambda x: None)
    cv2.createTrackbar('Blur (odd)', 'Parameter Tuning', default_blur, 30, lambda x: None)
    cv2.createTrackbar('Min Area', 'Parameter Tuning', default_min_area, 200, lambda x: None)
    cv2.createTrackbar('Max Area', 'Parameter Tuning', default_max_area, 5000, lambda x: None)
    cv2.createTrackbar('Mask Overlap %', 'Parameter Tuning', default_mask_overlap, 100, lambda x: None)
    cv2.createTrackbar('Bottom Excl px', 'Parameter Tuning', default_bottom_exclusion, 400, lambda x: None)
    
    print("\nPARAMETER TUNING")
    print("Controls:")
    print("  - Adjust sliders to tune detection")
    print("  - SPACE: Pause/Unpause video")
    print("  - 'n': Next frame (when paused)")
    print("  - 'r': Reset to start")
    print("  - 's': Save/show current settings")
    print("  - 'm': Toggle static shadow/background mask (builds it on first press, samples the video)")
    print("  - 'b': Rebuild the mask using current slider values (do this after retuning)")
    print("  - 'q': Quit")
    print("\nTips:")
    print("  - Block Size: Should be roughly the size of the fly (odd numbers seem to work best)")
    print("  - Constant: Higher = stricter (only very dark objects)")
    print("  - Blur: Higher = smoother (reduces noise)")
    print("  - Min Area: Filter out small false detections")
    print("  - Max Area: Filter out oversized blobs (merged flies, shadows, tube slots)")
    print("  - Mask Overlap %: how much of a contour must sit in the persistent-dark")
    print("    region before it's rejected as shadow/background instead of a fly")
    print("  - Bottom Excl px: always ignore this many pixels at the bottom of the")
    print("    frame (shown as a red band) -- simple, no thresholding involved\n")
    print("  - Draw region to focus detection on specific region (like clearer zone)")
    
    paused = False
    
    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                # loop back to start
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
        
        # get current trackbar values
        block_size = cv2.getTrackbarPos('Block Size', 'Parameter Tuning') 
        constant = cv2.getTrackbarPos('Constant', 'Parameter Tuning')
        blur_size = cv2.getTrackbarPos('Blur (odd)', 'Parameter Tuning')
        min_area = cv2.getTrackbarPos('Min Area', 'Parameter Tuning')
        max_area = cv2.getTrackbarPos('Max Area', 'Parameter Tuning')
        mask_overlap_threshold = cv2.getTrackbarPos('Mask Overlap %', 'Parameter Tuning') / 100.0
        bottom_exclusion_px = cv2.getTrackbarPos('Bottom Excl px', 'Parameter Tuning')
        
        # ensure block_size and blur_size are odd and >= 3
        block_size = max(3, block_size)
        if block_size % 2 == 0:
            block_size += 1
        
        blur_size = max(1, blur_size)
        if blur_size % 2 == 0:
            blur_size += 1
        
        # process frame and apply threshold
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
        thresh = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY_INV,
            block_size,
            constant
        )
        
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
        #thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)

        # always zero out the bottom N rows, no thresholding/sampling involved
        if bottom_exclusion_px > 0:
            cutoff = max(0, thresh.shape[0] - bottom_exclusion_px)
            thresh[cutoff:, :] = 0

        # find contours and draw (copy) over frame
        cnts = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = cnts[0] if len(cnts) == 2 else cnts[1]
        
        result = frame.copy()

        # visual indicator for the bottom-exclusion band so we can see
        # where it is relative to the tube
        if bottom_exclusion_px > 0:
            band_y = max(0, result.shape[0] - bottom_exclusion_px)
            overlay = result.copy()
            cv2.rectangle(overlay, (0, band_y), (result.shape[1], result.shape[0]),
                          (0, 0, 255), -1)
            cv2.addWeighted(overlay, 0.25, result, 0.75, 0, result)
            cv2.line(result, (0, band_y), (result.shape[1], band_y), (0, 0, 255), 1)

        # draw ROI rectangle if set (visual feedback)
        if roi and roi[2] > 0 and roi[3] > 0:
            rx, ry, rw, rh = roi
            cv2.rectangle(result, (rx, ry), (rx + rw, ry + rh), (255, 0, 255), 2)

        # draw all contours above minimum area
        detected_count = 0
        rejected_by_mask_count = 0
        for contour in contours:
            area = cv2.contourArea(contour)
            if area <= min_area:
                continue
            if area > max_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)

            # ROI filter (only if ROI is set)
            if roi and roi[2] > 0 and roi[3] > 0:
                rx, ry, rw, rh = roi
                cx, cy = x + w // 2, y + h // 2
                if not (rx <= cx <= rx + rw and ry <= cy <= ry + rh):
                    continue

            # static mask filter: reject anything sitting inside a
            # region that's been dark for nearly the whole video (shadow, tube slot)
            if mask_enabled and static_mask is not None:
                overlap = contour_overlap_fraction(contour, static_mask)
                if overlap >= mask_overlap_threshold:
                    rejected_by_mask_count += 1
                    cv2.rectangle(result, (x, y), (x + w, y + h), (0, 140, 255), 1)
                    cv2.putText(result, f'{int(area)} (masked)', (x, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 140, 255), 1)
                    continue

            # if we got here, it's a valid detection (and will be drawn)
            detected_count += 1

            cv2.rectangle(result, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(result, f'{int(area)}', (x, y - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        
        # display current settings on frame
        mask_status = f'Mask: ON ({rejected_by_mask_count} rejected)' if mask_enabled else 'Mask: OFF'
        settings_text = [
            f'Block: {block_size}',
            f'Const: {constant}',
            f'Blur: {blur_size}',
            f'MinArea: {min_area}',
            f'MaxArea: {max_area}',
            f'Detected: {detected_count}',
            mask_status,
            f'BottomExcl: {bottom_exclusion_px}px',
        ]
        
        if roi and roi[2] > 0 and roi[3] > 0:
            settings_text.append(f'ROI: {roi[2]}x{roi[3]}px')

        y_offset = 30
        for text in settings_text:
            cv2.putText(result, text, (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            y_offset += 30
        
        if paused:
            cv2.putText(result, 'PAUSED', (result.shape[1] - 150, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        
        # show windows
        cv2.imshow('Original', frame)
        cv2.imshow('Threshold Result', thresh)
        cv2.imshow('Parameter Tuning', result)

        if static_mask is not None:
            # show it as a 3-channel image so it displays the same way
            # regardless of window backend, orange tint to match the
            # rejected-contour boxes above
            mask_preview = cv2.cvtColor(static_mask, cv2.COLOR_GRAY2BGR)
            mask_preview[static_mask > 0] = (0, 140, 255)
            cv2.imshow('Static Mask (shadows/background)', mask_preview)
        else:
            placeholder = np.zeros((150, 500, 3), dtype=np.uint8)
            cv2.putText(placeholder, "Press 'm' to build the mask",
                        (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
            cv2.imshow('Static Mask (shadows/background)', placeholder)

        # key presses
        key = cv2.waitKey(30) & 0xFF        
        if key == ord('q'):
            break
        elif key == ord(' '):  # spacebar
            paused = not paused
            print("PAUSED" if paused else "PLAYING")
        elif key == ord('n') and paused:  # next frame
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        elif key == ord('r'):  # reset 
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            print("Reset to start")
        elif key == ord('c'):
            roi = None
            print("ROI cleared")
        elif key == ord('m'):
            if static_mask is None:
                print("\nBuilding occupancy-based exclusion mask, sampling video frames...")
                static_mask = build_static_exclusion_mask(
                    video_path,
                    roi=None,
                    block_size=block_size,
                    constant=constant,
                    blur_size=blur_size,
                    min_area=min_area,
                    max_area=max_area,
                )
                if static_mask is None:
                    print("Not enough frames to build a reliable mask.")
                else:
                    pct = 100 * np.count_nonzero(static_mask) / static_mask.size
                    print(f"Mask built: {pct:.1f}% of frame flagged as persistent shadow/background")
                    print("Note: the mask uses whatever Block/Constant/Blur/Min/Max Area "
                          "values are set right now. If you change those sliders afterward, "
                          "press 'b' to rebuild the mask so it stays in sync.")
            mask_enabled = not mask_enabled
            print(f"Static mask: {'ENABLED' if mask_enabled else 'DISABLED'}")
        elif key == ord('b'):
            print("\nRebuilding exclusion mask with current slider values...")
            static_mask = build_static_exclusion_mask(
                video_path,
                roi=None,
                block_size=block_size,
                constant=constant,
                blur_size=blur_size,
                min_area=min_area,
                max_area=max_area,
            )
            if static_mask is None:
                print("Not enough frames to build a reliable mask.")
            else:
                pct = 100 * np.count_nonzero(static_mask) / static_mask.size
                print(f"Mask rebuilt: {pct:.1f}% of frame flagged as persistent shadow/background")
        elif key == ord('s'):  # save/.print settings
            print("\nCURRENT SETTINGS:")
            print(f"Block Size: {block_size}")
            print(f"Constant: {constant}")
            print(f"Blur: {blur_size}")
            print(f"Min Area: {min_area}")
            print(f"Max Area: {max_area}")
            print(f"Mask Overlap Threshold: {mask_overlap_threshold:.2f}")
            print(f"Bottom Exclusion: {bottom_exclusion_px}px")
            print(f"blurred = cv2.GaussianBlur(gray, ({blur_size}, {blur_size}), 0)")
            print(f"thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_MEAN_C,")
            print(f"                                cv2.THRESH_BINARY_INV, {block_size}, {constant})")
            print(f"if {min_area} < area <= {max_area}:")
            print()
    
    # cleanup
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    VIDEO_FILE = "input_videos/IMG_5323.MOV"
    tune_parameters(VIDEO_FILE)
