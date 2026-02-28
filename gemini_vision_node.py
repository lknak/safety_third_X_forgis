import cv2
import os
import json
import numpy as np
import datetime

from google import genai
from google.genai import types
from PIL import Image as PILImage
import torch
try:
    from depth_anything_3.api import DepthAnything3
except ImportError:
    print("WARNING: depth_anything_3 module not found. Make sure the depth_anything_3 package is available in the Python path.")
    DepthAnything3 = None

from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
load_dotenv()

# Initialize models globally so they aren't reloaded on every function call
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    client = genai.Client(api_key=api_key)
else:
    print("WARNING: GEMINI_API_KEY not found in environment")
    client = None

print("Loading Depth Estimation model...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
if DepthAnything3 is not None:
    try:
        depth_model = DepthAnything3.from_pretrained("depth-anything/da3-small")
        depth_model = depth_model.to(device=device)
    except Exception as e:
        print(f"Error loading DepthAnything3: {e}")
        depth_model = None
else:
    depth_model = None

def run_gemini(image_bytes):
    if not client:
        return None
        
    PROMPT = """
    1. Locate the robot gripper's suction cup and the center of the box in this image.
    2. Provide their coordinates in [y, x] format (0-1000) as a list of 2 elements called waypoints.
    3. Output the result in JSON format with 'coordinates' and 'waypoints' keys.

    OUTPUT FORMAT
    {
        "coordinates": {
            "robot": [y, x],
            "box": [y, x]
        },
        "waypoints": [
            [y, x],
            [y, x]
        ]
    }
    """
    response = client.models.generate_content(
        model="gemini-robotics-er-1.5-preview", 
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            PROMPT
        ]
    )
    return response

def run_depth(cv_image, run_dir):
    if depth_model is None:
        print("Depth model not loaded, returning empty depth map")
        return np.zeros(cv_image.shape[:2], dtype=np.float32)
        
    rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
    
    # Run inference on the single image
    prediction = depth_model.inference(
        [rgb_image],
        export_dir=run_dir,
        export_format="glb"
    )
    
    # Prediction contains depth for the batch [N, H, W]
    # We pass 1 image so we access the first element
    depth_tensor = prediction.depth[0]
    
    # Convert tensor to numpy array
    if isinstance(depth_tensor, torch.Tensor):
        return depth_tensor.cpu().numpy()
    return depth_tensor

def estimate_depth_and_path(image_input):
    """
    Takes an image (either a file path or a cv2 image array) as input,
    runs Gemini and Depth estimation, and saves an output visualization.
    """
    if isinstance(image_input, str):
        print(f"Loading image from {image_input}...")
        cv_image = cv2.imread(image_input)
        if cv_image is None:
            print(f"Error: Failed to load image at {image_input}")
            return None, None
    else:
        cv_image = image_input.copy()

    # Create run-specific log directory
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(os.getcwd(), 'runs', f'run_{timestamp}')
    os.makedirs(run_dir, exist_ok=True)
    
    input_path = os.path.join(run_dir, 'input.jpg')
    cv2.imwrite(input_path, cv_image)
    print(f"Saved input image to {input_path}")

    # Encode OpenCV image to JPEG bytes for Gemini
    success, encoded_image = cv2.imencode('.jpg', cv_image)
    if not success:
        print("Error: Failed to encode image to JPEG")
        return None, None
    image_bytes = encoded_image.tobytes()

    print("Starting Gemini and Depth Estimation in parallel...")
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_gemini = executor.submit(run_gemini, image_bytes)
        future_depth = executor.submit(run_depth, cv_image, run_dir)
        
        response = future_gemini.result()
        depth_map = future_depth.result()

    if response:
        print(f"Gemini Response:\n{response.text}")

        # Parse the JSON response
        try:
            # Find the JSON part in the response
            json_str = response.text
            if "```json" in json_str:
                json_str = json_str.split("```json")[-1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[-1].split("```")[0].strip()
            
            data = json.loads(json_str)
            
            # Image dimensions for un-normalizing coordinates
            h, w = cv_image.shape[:2]
            
            def to_pixel(normalized_coord):
                # Normalized coords are [y, x] in 0-1000 range
                ny, nx = normalized_coord
                return (int(nx * w / 1000.0), int(ny * h / 1000.0))

            # Draw coordinates
            coords = data.get('coordinates', [])
            robot_pos = None
            box_pos = None
            
            # Handle both dictionary and list formats for coordinates
            if isinstance(coords, dict):
                robot_pos = coords.get('robot')
                box_pos = coords.get('box')
            elif isinstance(coords, list):
                for item in coords:
                    label = item.get('label', '').lower()
                    if 'robot' in label or 'suction' in label:
                        robot_pos = item.get('point')
                    elif 'box' in label:
                        box_pos = item.get('point')
            
            if robot_pos:
                px_robot = to_pixel(robot_pos)
                cv2.circle(cv_image, px_robot, 10, (255, 0, 0), -1)
                cv2.putText(cv_image, 'Robot', (px_robot[0]+15, px_robot[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
                
            if box_pos:
                px_box = to_pixel(box_pos)
                cv2.circle(cv_image, px_box, 10, (0, 0, 255), -1)
                cv2.putText(cv_image, 'Box', (px_box[0]+15, px_box[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                
            # Calculate Relative Depth Difference if both coords are found
            if robot_pos and box_pos:
                d_h, d_w = depth_map.shape
                
                ry_norm, rx_norm = robot_pos
                by_norm, bx_norm = box_pos
                
                ry = int(ry_norm * d_h / 1000.0)
                rx = int(rx_norm * d_w / 1000.0)
                
                by = int(by_norm * d_h / 1000.0)
                bx = int(bx_norm * d_w / 1000.0)
                
                # Ensure indices are within bounds
                ry = max(0, min(d_h - 1, ry))
                rx = max(0, min(d_w - 1, rx))
                by = max(0, min(d_h - 1, by))
                bx = max(0, min(d_w - 1, bx))
                
                depth_robot = depth_map[ry, rx]
                depth_box = depth_map[by, bx]
                depth_diff = float(depth_box) - float(depth_robot)
                
                depth_log = (
                    f"Depth at Robot Suction Cup: {depth_robot}\n"
                    f"Depth at Box (Suction Point): {depth_box}\n"
                    f"Relative Depth Difference (Box - Robot): {depth_diff}\n"
                )
                print(depth_log)

            # Draw waypoints
            waypoints = data.get('waypoints', [])
            prev_pt = px_robot if robot_pos else None
            
            for i, wp in enumerate(waypoints):
                px_wp = to_pixel(wp)
                cv2.circle(cv_image, px_wp, 5, (0, 255, 0), -1)
                cv2.putText(cv_image, str(i+1), (px_wp[0]+10, px_wp[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                if prev_pt:
                    cv2.line(cv_image, prev_pt, px_wp, (0, 255, 255), 2)
                prev_pt = px_wp
                
            if prev_pt and box_pos:
                 cv2.line(cv_image, prev_pt, px_box, (0, 255, 255), 2)
            
            # Save the image
            output_path = os.path.join(run_dir, 'output.jpg')
            cv2.imwrite(output_path, cv_image)
            print(f"Saved waypoint image to {output_path}")
            
            # Save the depth map image
            depth_normalized = cv2.normalize(depth_map, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
            depth_colormap = cv2.applyColorMap(depth_normalized, cv2.COLORMAP_INFERNO)
            depth_path = os.path.join(run_dir, 'depth.jpg')
            cv2.imwrite(depth_path, depth_colormap)
            print(f"Saved depth map image to {depth_path}")
            
            # Save the log file
            log_path = os.path.join(run_dir, 'log.txt')
            with open(log_path, 'w') as f:
                f.write(f"Run Timestamp: {timestamp}\n")
                if robot_pos and box_pos:
                    f.write("\nDepth Information:\n")
                    f.write(depth_log)
                f.write("\nGemini Raw JSON Response:\n")
                f.write(json_str)
            print(f"Saved text log to {log_path}")
            
        except Exception as parse_e:
            print(f"Failed to parse and draw waypoints: {parse_e}")
            
    return response, depth_map

if __name__ == '__main__':
    # Test on the image
    test_image_path = "/mnt/c/Users/wayl/Pictures/Camera Roll/WIN_20260228_17_21_56_Pro.jpg"
    estimate_depth_and_path(test_image_path)
