import numpy as np

def norm_position(positions):
    """
    Performs a normalization on the cx and cy coordinates of multiple flies' positions
    to provide more readable data for researchers

    Original: origin (0,0) is located at the top left corner
    Positive x-axis goes from left to right
    Positive y-axis goes from top to bottom

    Normalized: origin (0,0) is where each of the fruit fly runs begin
    Positive x-axis goes from left to right
    Positive y-axis goes from bottom to top

    args:
        positions: list of (frame_num, cx, cy, distance_cm, velocity_cm_s) tuples
                   returned by track_fly()
    returns:
        new_positions list with normalized cx and cy
    """
    temp_x = []
    temp_y = []
    new_positions = []

    # Make temporary copy from positions tuple
    for frame_num, cx, cy, distance_cm, velocity_cm_s in positions:
        temp_x.append(cx)
        temp_y.append(cy)
    temp_x = np.array(temp_x)
    temp_y = np.array(temp_y)

    # Select all values that are not NaN
    norm_x_mask = ~np.isnan(temp_x)
    norm_y_mask = ~np.isnan(temp_y)

    # Normalize all coordinates so that trace starts at x=0, y=0
    temp_x[norm_x_mask] -= temp_x[norm_x_mask][0]
    temp_y[norm_y_mask] -= temp_y[norm_y_mask][0]

    # Flip sign of Y-coordinates so that it is increasing rather than decreasing
    temp_y = [-value for value in temp_y]

    # Create new tuple
    for i, data in enumerate(positions):
        new_positions.append(data[:1] + (temp_x[i],) + (temp_y[i],) + data[3:])

    return new_positions