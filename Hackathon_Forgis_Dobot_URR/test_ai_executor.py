import asyncio
import sys
import os
os.environ["PYTHONUNBUFFERED"] = "1"
import cv2
import argparse
import platform

# Add the backend src directory to the python path so imports work correctly
backend_src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "src")
sys.path.append(backend_src_path)

# Try to import dotenv so API keys can be loaded automatically from the .env file
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".g-env")
    if os.path.exists(env_path):
        print(f"Loading environment variables from {env_path}", flush=True)
        load_dotenv(env_path)
except ImportError:
    print("python-dotenv not installed, continuing without auto-loading .env...", flush=True)

from executors.physical_ai_executor import PhysicalAiExecutor

class MockCameraNode:
    """A mock camera node that returns a static image."""
    def __init__(self, image_path):
        print(f"Loading test image from: {image_path}", flush=True)
        self.frame = cv2.imread(image_path)
        if self.frame is None:
            raise ValueError(f"Could not load image at {image_path}. Make sure the path is correct.")
            
    def has_frame(self) -> bool:
        return self.frame is not None
        
    def get_latest_frame(self):
        return self.frame

async def run_test(image_path, prompt, use_depth, current_pose):
    # Check for Gemini API Key
    if not os.environ.get("GEMINI_API_KEY"):
        print("WARNING: GEMINI_API_KEY environment variable is not set!", flush=True)
        print("The Gemini API will likely fail. Consider running: export GEMINI_API_KEY='your-key'", flush=True)
        print("---", flush=True)

    try:
        mock_camera = MockCameraNode(image_path)
    except Exception as e:
        print(f"Error initializing mock camera: {e}", flush=True)
        return

    # Initialize the executor with the mock camera
    print("Initializing PhysicalAiExecutor...", flush=True)
    executor = PhysicalAiExecutor(mock_camera)
    await executor.initialize()
    
    print("\n" + "="*50, flush=True)
    print(f"TASK PROMPT:   '{prompt}'", flush=True)
    print(f"USE DEPTH:     {use_depth}", flush=True)
    print(f"CURRENT POSE:  {current_pose}", flush=True)
    print("="*50 + "\n", flush=True)
    
    print("Running generate_trajectory... (this may take a moment depending on network/models)\n", flush=True)
    
    # Run the executor
    result = await executor.generate_trajectory(prompt=prompt, use_depth=use_depth, current_pose=current_pose)
    
    # Output the result
    print("="*20 + " RESULT " + "="*20)
    if result.get("success"):
        print("status: SUCCESS")
        print("\nExtracted Coordinates:")
        print(result.get("coordinates", {}))
        print("\nExtracted Waypoints:")
        for i, wp in enumerate(result.get("waypoints", [])):
            print(f"  {i+1}: {wp}")
            
        print(f"\nDepth map available: {result.get('depth_map_available', False)}")
        
        target_pose = result.get("target_pose", None)
        if target_pose:
            print(f"\nCalculated Target Robot Pose: {target_pose}")
        
        print("\n--- RAW RESPONSE ---")
        print(result.get("raw_response", ""))
    else:
        print("status: FAILED")
        print(f"error: {result.get('error')}")
        
    await executor.shutdown()

if __name__ == "__main__":
    # In Windows WSL environments matplotlib / asyncio sometimes requires this
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    parser = argparse.ArgumentParser(description="Test PhysicalAiExecutor standalone.")
    parser.add_argument("image", help="Path to input image (e.g. test_image.jpg)")
    parser.add_argument(
        "--prompt", 
        type=str, 
        default="Locate the suction cup and target box, and draw a 2-point trajectory picking up the box.",
        help="High-level task prompt for Gemini"
    )
    parser.add_argument(
        "--no-depth", 
        action="store_true", 
        help="Disable depth estimation map generation"
    )
    
    args = parser.parse_args()
    
    dummy_pose = {
        "position": {"x": 0.100, "y": -0.400, "z": 0.350},
        "orientation": {"x": 0, "y": 1, "z": 0, "w": 0}
    }
    
    # Run async test
    asyncio.run(run_test(args.image, args.prompt, not args.no_depth, current_pose=dummy_pose))
