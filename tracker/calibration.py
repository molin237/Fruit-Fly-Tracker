import numpy as np
import cv2

def calibrate_scale(video_path, known_distance_cm=None):
    """
    Interactively calibrate pixels-to-cm scale by clicking two points of known distance.

    Shows the first frame of the video and lets the user click two points
    (the top and bottom of a reference object like tube).
    Computes the cm/pixel ratio from the pixel distance between those points
    and the provided real-world distance.

    args:
        video_path: path to the input video file
        known_distance_cm: real-world distance in cm between the two points you'll click.
    returns:
        scale as a float (cm per pixel), or None if calibration was cancelled/failed
    """
    # guard against missing known distance.
    # without this, known_distance_cm / pixel_distance will raise a TypeError.
    # we explicitly require a physical measurement (in cm) for calibration.
    if known_distance_cm is None:
        print("Calibration error: known_distance_cm was not provided.")
        print("You must pass a real-world distance in cm (e.g., 10).")
        return None

    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()

    print("Click two points of known distance (like top and bottom of straw)")
    print("ENTER when done, ESC to cancel")

    points = []

    def mouse_callback(event, x, y, flags, param):
        nonlocal points
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 2:
            points.append((x, y))
            # draw each clicked point
            cv2.circle(frame, (x, y), 5, (0, 255, 0), -1)
            if len(points) == 2:
                # draw line between the two points so the user can confirm
                cv2.line(frame, points[0], points[1], (0, 255, 0), 2)
            cv2.imshow("Calibration", frame)

    cv2.namedWindow("Calibration", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("Calibration", mouse_callback)
    cv2.imshow("Calibration", frame)

    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == 13:    # enter
            break
        elif key == 27:  # esc
            points = []
            break

    cv2.destroyAllWindows()

    if len(points) != 2:
        print("Calibration cancelled or invalid")
        return None

    # euclidean distance between the two clicked points in pixels
    pixel_distance = np.sqrt(
        (points[1][0] - points[0][0]) ** 2 +
        (points[1][1] - points[0][1]) ** 2
    )

    print(f"Pixel distance: {pixel_distance:.2f} px")

    if pixel_distance <= 0:
        print("Invalid pixel distance (0). Calibration failed.")
        return None

    scale = known_distance_cm / pixel_distance

    print(f"Scale: {scale:.6f} cm/pixel")
    print(f"(1 pixel = {scale:.6f} cm, or {scale * 10:.6f} mm)")

    return scale

def select_roi(video_path):
    """
    Manually select a region of interest from the first frame of a video.

    Click and drag to draw a rectangle around the area where the fly will be.
    Press ENTER to confirm, ESC to cancel.

    args:
        video_path: path to the input video file
    returns:
        roi tuple (x, y, width, height) if a valid selection was made, else None
    """
    # fortunately, OpenCV has its own selectROI function, so we are just using that
    cap = cv2.VideoCapture(video_path)
    _, frame = cap.read()
    cap.release()

    print("\nROI Selection")
    print("Click and drag to select the region where the will be")
    print("Press ENTER when done, ESC to cancel")

    cv2.namedWindow("Select Fly Region", cv2.WINDOW_NORMAL)
    roi = cv2.selectROI("Select Fly Region", frame, fromCenter=False, showCrosshair=True)
    cv2.destroyAllWindows()
    
    # roi params:
    if roi[2] > 0 and roi[3] > 0:  # valid selection
        print(f"ROI selected: x={roi[0]}, y={roi[1]}, width={roi[2]}, height={roi[3]}")
        return roi
    else:
        print("No ROI selected")
        return None