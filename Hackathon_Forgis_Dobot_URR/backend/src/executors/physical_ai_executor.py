"""Physical AI executor for Gemini ER and Depth estimation."""

import asyncio
import json
import logging
import os
import datetime
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np

from .base import Executor

if TYPE_CHECKING:
    from nodes.camera_node import CameraNode

logger = logging.getLogger(__name__)

class PhysicalAiExecutor(Executor):
    """
    Executor for Physical AI (Gemini ER + Depth estimation).
    """

    executor_type = "physical_ai_node"

    def __init__(self, camera_node: "CameraNode"):
        self._camera = camera_node
        
        # Lazy loaded models
        self._gemini_client = None
        self._depth_model = None
        
    async def initialize(self) -> None:
        """Initialize models in the background."""
        logger.info("PhysicalAiExecutor initializing...")
        # Start background load
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._init_models)
        
        # Verify camera
        timeout = 5.0
        elapsed = 0.0
        while not self._camera.has_frame() and elapsed < timeout:
            await asyncio.sleep(0.1)
            elapsed += 0.1
            
        logger.info("PhysicalAiExecutor ready")

    def _init_models(self):
        """Load Gemini client and DepthAnything model."""
        try:
            from google import genai
            api_key = os.environ.get("GEMINI_API_KEY")
            if api_key:
                self._gemini_client = genai.Client(api_key=api_key)
            else:
                logger.warning("GEMINI_API_KEY not found in environment")
        except ImportError:
            logger.warning("google-genai module not found")
            
        try:
            import torch
            from depth_anything_3.api import DepthAnything3
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            logger.info("Loading DepthAnything3 model...")
            self._depth_model = DepthAnything3.from_pretrained("depth-anything/da3-small")
            self._depth_model = self._depth_model.to(device=device)
        except ImportError:
            logger.warning("depth_anything_3 module not found")
        except Exception as e:
            logger.error(f"Error loading DepthAnything3: {e}")

    async def shutdown(self) -> None:
        """Cleanup."""
        pass

    def is_ready(self) -> bool:
        """Check if camera frame is available."""
        return self._camera.has_frame()

    def run_gemini(self, image_bytes: bytes, user_prompt: str) -> Optional[str]:
        if not self._gemini_client:
            logger.error("Gemini client not initialized")
            return None
            
        full_prompt = f"""
        TASK: {user_prompt}
        
        INSTRUCTIONS:
        1. Comply with the TASK above.
        2. Determine the coordinates of the robot gripper's suction cup and the target object in [y, x] format (0-1000).
        3. If there are obstacles on the way which the robot must avoid, provide their highest point in [y, x] format (0-1000) as a list of elements called obstacles.
        4. Output the result strictly in JSON format with 'coordinates' and 'obstacles' keys.

        OUTPUT FORMAT
        {{
            "coordinates": {{
                "robot": [y, x],
                "target": [y, x]
            }},
            "obstacles": [
                [y, x], // only if there actually is an obstacle in the way
                ...
            ]
        }}
        """

        from google.genai import types
        try:
            response = self._gemini_client.models.generate_content(
                model="gemini-robotics-er-1.5-preview", 
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    full_prompt
                ]
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None

    def run_depth(self, cv_image: np.ndarray, run_dir: str) -> np.ndarray:
        if self._depth_model is None:
            return np.zeros(cv_image.shape[:2], dtype=np.float32)
            
        import torch
        rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        
        try:
            prediction = self._depth_model.inference(
                [rgb_image],
                export_dir=run_dir,
                export_format="glb"
            )
            depth_tensor = prediction.depth[0]
            if isinstance(depth_tensor, torch.Tensor):
                return depth_tensor.cpu().numpy()
            return depth_tensor
        except Exception as e:
            logger.error(f"Depth model error: {e}")
            return np.zeros(cv_image.shape[:2], dtype=np.float32)

    async def generate_trajectory(self, prompt: str, use_depth: bool, current_pose: dict = None) -> dict:
        frame = self._camera.get_latest_frame()
        if frame is None:
            return {"success": False, "error": "No frame available from camera"}

        # Encode frame to JPEG
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 90]
        success, encoded = cv2.imencode(".jpg", frame, encode_params)
        if not success:
            return {"success": False, "error": "Failed to encode image"}

        image_bytes = encoded.tobytes()
        
        # Setup logging dir
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(os.getcwd(), 'runs', f'run_{timestamp}')
        os.makedirs(run_dir, exist_ok=True)
        cv2.imwrite(os.path.join(run_dir, 'input.jpg'), frame)
        
        # Run on threadpool
        loop = asyncio.get_running_loop()
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as t_exec:
            future_gemini = loop.run_in_executor(t_exec, self.run_gemini, image_bytes, prompt)
            
            if use_depth:
                future_depth = loop.run_in_executor(t_exec, self.run_depth, frame.copy(), run_dir)
            else:
                future_depth = None
                
            gemini_result = await future_gemini
            if future_depth:
                depth_map = await future_depth
            else:
                depth_map = None

        if not gemini_result:
            return {"success": False, "error": "Failed to get response from Gemini"}

        # Extract JSON
        json_str = gemini_result
        if "```json" in json_str:
            json_str = json_str.split("```json")[-1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[-1].split("```")[0].strip()
            
        try:
            data = json.loads(json_str)
            waypoints = data.get('waypoints', [])
            coords = data.get('coordinates', {})
            
            # Extract depth and box pose relative to robot
            target_pose = None
            if current_pose and depth_map is not None:
                robot_pos = coords.get('robot')
                target_pos = coords.get('target')
                
                if robot_pos and target_pos:
                    d_h, d_w = depth_map.shape
                    
                    ry_norm, rx_norm = robot_pos
                    ty_norm, tx_norm = target_pos
                    
                    ry = int(ry_norm * d_h / 1000.0)
                    rx = int(rx_norm * d_w / 1000.0)
                    
                    ty = int(ty_norm * d_h / 1000.0)
                    tx = int(tx_norm * d_w / 1000.0)
                    
                    # Ensure indices are within bounds
                    ry = max(0, min(d_h - 1, ry))
                    rx = max(0, min(d_w - 1, rx))
                    ty = max(0, min(d_h - 1, ty))
                    tx = max(0, min(d_w - 1, tx))
                    
                    depth_robot = depth_map[ry, rx]
                    depth_target = depth_map[ty, tx]
                    depth_diff = float(depth_target) - float(depth_robot)
                    
                    # Convert pixel diff to approx meter offset (Naive linear approximation approach)
                    # For a real system we'd use camera intrinsics. We'll assign arbitrary constants.
                    # dy is down in image, map to robot x or y depending on camera mount.
                    # Usually:
                    # diff_x_px -> robot y
                    # diff_y_px -> robot x
                    # depth_diff -> robot z
                    
                    diff_x_px = tx - rx
                    diff_y_px = ty - ry
                    
                    pixel_to_m = 0.001 # 1 pixel = 1mm at this scale as a naive guess
                    
                    dx_m = diff_y_px * pixel_to_m  # vertical image diff -> robot X 
                    dy_m = diff_x_px * pixel_to_m  # horizontal image diff -> robot Y
                    dz_m = depth_diff  # depth diff -> robot Z
                    
                    target_pose = current_pose.copy()
                    target_pose["position"]["x"] += dx_m
                    target_pose["position"]["y"] += dy_m
                    target_pose["position"]["z"] += dz_m
            
            # Draw visualizations
            cv_image = frame.copy()
            h, w = cv_image.shape[:2]
            
            def to_pixel(normalized_coord):
                # Normalized coords are [y, x] in 0-1000 range
                ny, nx = normalized_coord
                return (int(nx * w / 1000.0), int(ny * h / 1000.0))
                
            robot_pos = coords.get('robot')
            target_pos = coords.get('target')
            px_robot = None
            px_target = None
            
            if robot_pos:
                px_robot = to_pixel(robot_pos)
                cv2.circle(cv_image, px_robot, 10, (255, 0, 0), -1)
                cv2.putText(cv_image, 'Robot', (px_robot[0]+15, px_robot[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
                
            if target_pos:
                px_target = to_pixel(target_pos)
                cv2.circle(cv_image, px_target, 10, (0, 0, 255), -1)
                cv2.putText(cv_image, 'Target', (px_target[0]+15, px_target[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                
            prev_pt = px_robot if robot_pos else None
            
            for i, wp in enumerate(waypoints):
                px_wp = to_pixel(wp)
                cv2.circle(cv_image, px_wp, 5, (0, 255, 0), -1)
                cv2.putText(cv_image, str(i+1), (px_wp[0]+10, px_wp[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                if prev_pt:
                    cv2.line(cv_image, prev_pt, px_wp, (0, 255, 255), 2)
                prev_pt = px_wp
                
            if prev_pt and target_pos:
                 cv2.line(cv_image, prev_pt, px_target, (0, 255, 255), 2)
                 
            # Save the waypoint image
            output_path = os.path.join(run_dir, 'output.jpg')
            cv2.imwrite(output_path, cv_image)
            logger.info(f"Saved waypoint image to {output_path}")
            
            # Save the depth map image
            depth_log = ""
            if depth_map is not None:
                depth_normalized = cv2.normalize(depth_map, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                depth_colormap = cv2.applyColorMap(depth_normalized, cv2.COLORMAP_INFERNO)
                depth_path = os.path.join(run_dir, 'depth.jpg')
                cv2.imwrite(depth_path, depth_colormap)
                logger.info(f"Saved depth map image to {depth_path}")
                
            # Logging
            log_path = os.path.join(run_dir, 'log.txt')
            with open(log_path, 'w') as f:
                f.write(f"Run Timestamp: {timestamp}\n")
                if robot_pos and target_pos and depth_map is not None:
                    f.write("\nDepth Information:\n")
                    f.write(f"Depth at Robot (Z): {depth_robot}\n")
                    f.write(f"Depth at Target (Z): {depth_target}\n")
                    f.write(f"Calculated Relative Targets (dx:{dx_m}, dy:{dy_m}, dz:{dz_m})\n")
                f.write("\nGemini Raw JSON Response:\n")
                f.write(json_str)
            logger.info(f"Saved text log to {log_path}")
            return {
                "success": True, 
                "waypoints": waypoints, 
                "coordinates": coords,
                "depth_map_available": depth_map is not None, 
                "target_pose": target_pose,
                "raw_response": gemini_result
            }
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            return {"success": False, "error": f"JSON Parse Error: {e}\nRaw={gemini_result}"}
