import os
import cv2
import time
import numpy  # For some colormap effects if needed
import tkinter as tk
from tkinter import filedialog


# Helper function to convert FourCC integer to string for printing
def fourcc_to_string(fourcc_int):
    if fourcc_int == 0: return "UNKNOWN/FAILED"
    try:
        val = int(fourcc_int)
        return "".join([chr((val >> 8 * i) & 0xFF) for i in range(4)])
    except Exception: return str(fourcc_int)
    return None

def ask_for_save_path(initial_dir, title, file_types, default_extension):
    """Opens a 'Save As' dialog and returns the selected path."""
    root = tk.Tk()
    root.withdraw()  # Hide the main Tkinter window
    
    filepath = filedialog.asksaveasfilename(
        initialdir=initial_dir,
        title=title,
        filetypes=file_types,
        defaultextension=default_extension
    )
    
    root.destroy()  # Clean up the Tkinter instance
    return filepath

# --- Configuration ---
CAMERA_INDEX = 0 # Try 0, 1, 2, etc.
WINDOW_NAME = "Microscope Power Tools"
CAPTURE_PATH = "./microscope_captures/"

if not os.path.exists(CAPTURE_PATH):
    os.makedirs(CAPTURE_PATH)
    print(f"Created directory: {CAPTURE_PATH}")

DISPLAY_WIDTH = 960 # Adjusted for more space for info text
DISPLAY_HEIGHT = None

PIXELS_PER_REAL_UNIT = 3.0
REAL_WORLD_UNIT_LABEL = "µm"
SCALE_BAR_LENGTH_REAL_UNITS = 100
SCALE_BAR_COLOR = (255, 255, 255)
SCALE_BAR_THICKNESS = 2
TEXT_COLOR = (255, 255, 255)
TEXT_FONT = cv2.FONT_HERSHEY_SIMPLEX
TEXT_SCALE = 0.5 # Slightly smaller for more info
TEXT_THICKNESS = 1
MARGIN = 20

# --- Measurement Tool Config ---
MEASURE_POINT_COLOR = (0, 255, 0)
MEASURE_LINE_COLOR = (0, 255, 255)
MEASURE_TEXT_COLOR = (0, 255, 255)
POINT_RADIUS = 5

# --- Annotation Config ---
ANNOTATION_POINT_COLOR = (255, 0, 0) # Blue for annotation points
ANNOTATION_TEXT_COLOR = (255, 200, 200) # Light blue for annotation text

# --- Visual Filters / Colormaps ---
FILTER_MODES = ["Normal", "Grayscale", "Jet Colormap", "HSV Colormap", "Cool Colormap", "Channel Swap RGB", "Invert Colors"]
current_filter_index = 0

# --- Global State Variables ---
# General
mode = "normal" # "normal", "distance_measure", "angle_measure", "annotate_place_point", "annotate_type_text"
info_message = ""
scale_x_display_to_original = 1.0
scale_y_display_to_original = 1.0

# Distance Measurement
dist_measure_points = []
dist_measured_pixels = 0
dist_measured_real = 0.0

# Angle Measurement
angle_measure_points = []
angle_measured_degrees = 0.0

# Annotations
annotations = [] # List of dicts: {'point': (x,y), 'text': "string"}
current_annotation_text = ""
current_annotation_point = None


# --- Mouse Callback ---
def mouse_events(event, x_click, y_click, flags, param):
    global mode, dist_measure_points, angle_measure_points, current_annotation_point
    global dist_measured_pixels, dist_measured_real, angle_measured_degrees
    global scale_x_display_to_original, scale_y_display_to_original, info_message

    # Scale click coordinates back to original frame resolution
    original_x = int(x_click * scale_x_display_to_original)
    original_y = int(y_click * scale_y_display_to_original)

    if event == cv2.EVENT_LBUTTONDOWN:
        if mode == "distance_measure":
            if len(dist_measure_points) < 2:
                dist_measure_points.append((original_x, original_y))
            if len(dist_measure_points) == 2:
                p1, p2 = dist_measure_points[0], dist_measure_points[1]
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                dist_measured_pixels = numpy.sqrt(dx**2 + dy**2)
                dist_measured_real = dist_measured_pixels / PIXELS_PER_REAL_UNIT if PIXELS_PER_REAL_UNIT > 0 else 0
                info_message = f"Distance: {dist_measured_real:.2f}{REAL_WORLD_UNIT_LABEL}"
        elif mode == "angle_measure":
            if len(angle_measure_points) < 3:
                angle_measure_points.append((original_x, original_y))
            if len(angle_measure_points) == 3:
                p1, p2, p3 = angle_measure_points[0], angle_measure_points[1], angle_measure_points[2] # p1 is vertex
                v1 = (p2[0] - p1[0], p2[1] - p1[1])
                v2 = (p3[0] - p1[0], p3[1] - p1[1])
                dot_product = v1[0]*v2[0] + v1[1]*v2[1]
                mag_v1 = numpy.sqrt(v1[0]**2 + v1[1]**2)
                mag_v2 = numpy.sqrt(v2[0]**2 + v2[1]**2)
                if mag_v1 * mag_v2 == 0: # Avoid division by zero
                    angle_measured_degrees = 0
                else:
                    cos_angle = dot_product / (mag_v1 * mag_v2)
                    cos_angle = max(-1.0, min(1.0, cos_angle)) # Clamp to avoid domain errors with acos
                    angle_rad = numpy.acos(cos_angle)
                    angle_measured_degrees = numpy.degrees(angle_rad)
                info_message = f"Angle: {angle_measured_degrees:.2f} degrees"
        elif mode == "annotate_place_point":
            current_annotation_point = (original_x, original_y)
            info_message = "Type annotation text, Enter to save, Esc to cancel."
            # This is a bit of a hack: change mode here so main loop can handle text input
            # Ideally, mouse callback shouldn't change global 'mode' directly affecting main loop logic this way
            # For more complex state, a state machine pattern would be better.
            param['change_mode_to'] = "annotate_type_text" # Pass mode change request via param

# --- Main Program ---
cap = cv2.VideoCapture(CAMERA_INDEX)
if not cap.isOpened():
    print(f"Error: Could not open video device at index {CAMERA_INDEX}.")
    exit()

original_frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
original_frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
aspect_ratio = original_frame_width / original_frame_height if original_frame_height > 0 else 1.0

display_w, display_h = original_frame_width, original_frame_height
if DISPLAY_WIDTH is not None and DISPLAY_HEIGHT is None:
    display_w = DISPLAY_WIDTH
    display_h = int(display_w / aspect_ratio) if aspect_ratio > 0 else DISPLAY_WIDTH # handle aspect_ratio = 0
elif DISPLAY_HEIGHT is not None and DISPLAY_WIDTH is None:
    display_h = DISPLAY_HEIGHT
    display_w = int(display_h * aspect_ratio)
elif DISPLAY_WIDTH is not None and DISPLAY_HEIGHT is not None:
    display_w, display_h = DISPLAY_WIDTH, DISPLAY_HEIGHT

if display_w > 0 and display_h > 0:
    scale_x_display_to_original = original_frame_width / display_w
    scale_y_display_to_original = original_frame_height / display_h

print(f"Camera: {CAMERA_INDEX}, Original Res: {original_frame_width}x{original_frame_height}, Display Res: {display_w}x{display_h}")
print("--- CONTROLS ---")
print(" 's': Save image | 'r': Record video | 'q': Quit")
print(" 'd': Distance measure | 'a': Angle measure | 't': Annotate point")
print(" 'c': Clear current measurement/annotation points")
print(" 'C' (Shift+C): Clear ALL annotations")
print(" 'f': Cycle visual filters/colormaps")
print("------------------")
print(f"Scale: {PIXELS_PER_REAL_UNIT} px/{REAL_WORLD_UNIT_LABEL} | Bar: {SCALE_BAR_LENGTH_REAL_UNITS} {REAL_WORLD_UNIT_LABEL}")

is_recording = False
video_writer = None
fps = cap.get(cv2.CAP_PROP_FPS)
fps = float(fps) if fps and fps > 0 else 20.0

scale_bar_length_pixels = int(SCALE_BAR_LENGTH_REAL_UNITS * PIXELS_PER_REAL_UNIT)

cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
if display_w != original_frame_width or display_h != original_frame_height:
     cv2.resizeWindow(WINDOW_NAME, display_w, display_h)

# Param dictionary for mouse callback to request mode changes
mouse_callback_param = {'change_mode_to': None}
cv2.setMouseCallback(WINDOW_NAME, mouse_events, mouse_callback_param)

while True:
    ret, frame_bgr_original = cap.read()
    if not ret: break

    # --- Apply Visual Filters/Colormaps First ---
    processed_frame = frame_bgr_original.copy()
    filter_name = FILTER_MODES[current_filter_index]

    if filter_name == "Grayscale":
        gray = cv2.cvtColor(frame_bgr_original, cv2.COLOR_BGR2GRAY)
        processed_frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR) # Keep 3 channels for consistency
    elif filter_name == "Jet Colormap":
        gray = cv2.cvtColor(frame_bgr_original, cv2.COLOR_BGR2GRAY)
        processed_frame = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
    elif filter_name == "HSV Colormap":
        gray = cv2.cvtColor(frame_bgr_original, cv2.COLOR_BGR2GRAY)
        processed_frame = cv2.applyColorMap(gray, cv2.COLORMAP_HSV)
    elif filter_name == "Cool Colormap":
        gray = cv2.cvtColor(frame_bgr_original, cv2.COLOR_BGR2GRAY)
        processed_frame = cv2.applyColorMap(gray, cv2.COLORMAP_COOL)
    elif filter_name == "Channel Swap RGB":
        b, g, r = cv2.split(frame_bgr_original)
        processed_frame = cv2.merge((g, r, b)) # Example: BGR -> GRB
    elif filter_name == "Invert Colors":
        processed_frame = cv2.bitwise_not(frame_bgr_original)
    # "Normal" mode uses processed_frame which is a copy of frame_bgr_original

    overlay_frame = processed_frame.copy() # For drawing overlays at original resolution

    # --- Drawing Overlays ---
    # Scale Bar
    bar_x_start = MARGIN; bar_y_pos = original_frame_height - MARGIN
    cv2.line(overlay_frame, (bar_x_start, bar_y_pos), (bar_x_start + scale_bar_length_pixels, bar_y_pos), SCALE_BAR_COLOR, SCALE_BAR_THICKNESS)
    # ... (ticks for scale bar - can be added back if desired) ...
    cv2.putText(overlay_frame, f"{SCALE_BAR_LENGTH_REAL_UNITS} {REAL_WORLD_UNIT_LABEL}", (bar_x_start, bar_y_pos - 10), TEXT_FONT, TEXT_SCALE, TEXT_COLOR, TEXT_THICKNESS, cv2.LINE_AA)

    # Mode/Info text
    mode_display_text = f"Mode: {mode.replace('_', ' ')} | Filter: {filter_name}"
    cv2.putText(overlay_frame, mode_display_text, (MARGIN, MARGIN + int(20*TEXT_SCALE/.5)), TEXT_FONT, TEXT_SCALE*1.2, (200,255,200), TEXT_THICKNESS, cv2.LINE_AA)
    if info_message:
        cv2.putText(overlay_frame, info_message, (MARGIN, MARGIN + int(50*TEXT_SCALE/.5)), TEXT_FONT, TEXT_SCALE*1.1, (200,200,255), TEXT_THICKNESS, cv2.LINE_AA)

    # Distance Measurement Drawing
    for i, p in enumerate(dist_measure_points): cv2.circle(overlay_frame, p, POINT_RADIUS, MEASURE_POINT_COLOR, -1)
    if len(dist_measure_points) == 2:
        cv2.line(overlay_frame, dist_measure_points[0], dist_measure_points[1], MEASURE_LINE_COLOR, 1)

    # Angle Measurement Drawing
    for i, p in enumerate(angle_measure_points): cv2.circle(overlay_frame, p, POINT_RADIUS, MEASURE_POINT_COLOR, -1)
    if len(angle_measure_points) == 3:
        cv2.line(overlay_frame, angle_measure_points[0], angle_measure_points[1], MEASURE_LINE_COLOR, 1)
        cv2.line(overlay_frame, angle_measure_points[0], angle_measure_points[2], MEASURE_LINE_COLOR, 1)
        # Arc for angle (simplified)
        # cv2.ellipse(overlay_frame, angle_measure_points[0], (30,30), ...) # More complex to draw nicely

    # Annotations Drawing
    for ann in annotations:
        cv2.circle(overlay_frame, ann['point'], POINT_RADIUS-2, ANNOTATION_POINT_COLOR, -1)
        cv2.putText(overlay_frame, ann['text'], (ann['point'][0] + 10, ann['point'][1] + 5), TEXT_FONT, TEXT_SCALE, ANNOTATION_TEXT_COLOR, TEXT_THICKNESS, cv2.LINE_AA)
    if mode == "annotate_type_text" and current_annotation_point:
        cv2.circle(overlay_frame, current_annotation_point, POINT_RADIUS-1, (255,255,0), -1) # Highlight current point
        cv2.putText(overlay_frame, current_annotation_text + "|", (current_annotation_point[0] + 10, current_annotation_point[1] + 5), TEXT_FONT, TEXT_SCALE, (255,255,0), TEXT_THICKNESS, cv2.LINE_AA)


    # Recording Indicator
    if is_recording:
        cv2.circle(overlay_frame, (original_frame_width - MARGIN - 10, MARGIN + 10), 10, (0, 0, 255), -1)
        video_writer.write(overlay_frame) # Save frame with overlays

    # --- Display ---
    display_output_frame = overlay_frame
    if (display_w != original_frame_width or display_h != original_frame_height):
        if display_w > 0 and display_h > 0: # Ensure valid dimensions
            display_output_frame = cv2.resize(overlay_frame, (display_w, display_h), interpolation=cv2.INTER_AREA)

    cv2.imshow(WINDOW_NAME, display_output_frame)

    # --- Key Handling ---
    # Check if mouse callback requested a mode change
    if mouse_callback_param['change_mode_to']:
        mode = mouse_callback_param['change_mode_to']
        mouse_callback_param['change_mode_to'] = None # Reset request

    key_wait_time = 1 if mode != "annotate_type_text" else 30 # Shorter wait for typing
    key = cv2.waitKey(key_wait_time) & 0xFF

    if mode == "annotate_type_text":
        if key != 255: # 255 is no key pressed
            if key == 13: # Enter
                if current_annotation_text and current_annotation_point:
                    annotations.append({'point': current_annotation_point, 'text': current_annotation_text})
                current_annotation_text = ""
                current_annotation_point = None
                mode = "normal"
                info_message = "Annotation saved. Press 't' for new."
            elif key == 27: # Escape
                current_annotation_text = ""
                current_annotation_point = None
                mode = "normal"
                info_message = "Annotation cancelled."
            elif key == 8: # Backspace
                current_annotation_text = current_annotation_text[:-1]
            elif 32 <= key <= 126: # Printable ASCII
                current_annotation_text += chr(key)
        # Continue in annotate_type_text mode until Enter/Esc
    else: # Normal key handling for other modes
        if key == ord('q'): break
        elif key == ord('s'):
            ts = time.strftime("%Y%m%d-%H%M%S")
            default_filename = f"capture_{ts}.png"
            
            filepath = ask_for_save_path(
                initial_dir=CAPTURE_PATH,
                title="Save Image As...",
                file_types=(("PNG files", "*.png"), ("JPEG files", "*.jpg"), ("All files", "*.*")),
                default_extension=".png"
            )

            # If the user selected a path (didn't cancel)
            if filepath:
                cv2.imwrite(filepath, overlay_frame) # Save with overlays
                # Use os.path.basename to show just the filename in the message
                info_message = f"Saved: {os.path.basename(filepath)}"
            else:
                info_message = "Save cancelled."
        elif key == ord('r'):
            if not is_recording:
                # --- MODIFIED: Start Recording Logic ---
                ts = time.strftime("%Y%m%d-%H%M%S")
                default_filename = f"video_{ts}.mp4"
                
                filepath = ask_for_save_path(
                    initial_dir=CAPTURE_PATH,
                    title="Record Video As...",
                    file_types=(("MP4 files", "*.mp4"), ("AVI files", "*.avi"), ("All files", "*.*")),
                    default_extension=".mp4"
                )

                if filepath:
                    fourcc = cv2.VideoWriter_fourcc(*'X264') # or 'MP4V'
                    video_writer = cv2.VideoWriter(filepath, fourcc, fps, (original_frame_width, original_frame_height))
                    if video_writer.isOpened():
                        is_recording = True
                        info_message = f"Recording to {os.path.basename(filepath)}"
                    else:
                        info_message = "Error starting recording!"
                else:
                    info_message = "Recording cancelled."
                # -----------------------------------
            else:
                is_recording = False
                video_writer.release()
                info_message = "Recording stopped."
        elif key == ord('d'):
            mode = "distance_measure"; dist_measure_points = []; info_message = "Distance Mode: Click 2 points."
        elif key == ord('a'):
            mode = "angle_measure"; angle_measure_points = []; info_message = "Angle Mode: Click 3 points (Vertex first)."
        elif key == ord('t'):
            mode = "annotate_place_point"; info_message = "Annotation Mode: Click to place text."
            current_annotation_text = ""; current_annotation_point = None
        elif key == ord('c'): # Clear current tool's points
            if mode == "distance_measure": dist_measure_points = []
            elif mode == "angle_measure": angle_measure_points = []
            # If in annotate_place_point or annotate_type_text and 'c' is pressed, cancel current
            elif mode.startswith("annotate"):
                current_annotation_text = ""; current_annotation_point = None; mode = "normal"
            info_message = "Current points cleared."
        elif key == ord('C'): # Clear ALL annotations
            annotations = []
            info_message = "All annotations cleared."
        elif key == ord('f'): # Cycle filters
            current_filter_index = (current_filter_index + 1) % len(FILTER_MODES)
            info_message = f"Filter: {FILTER_MODES[current_filter_index]}"
        elif key != 255 : # Any other key resets info_message if not consumed
             if mode == "normal" and info_message : info_message = "" # Clear info if in normal mode and a key is pressed


if is_recording and video_writer: video_writer.release()
cap.release()
cv2.destroyAllWindows()
