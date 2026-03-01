import cv2
import numpy as np
import requests
import json
import os
import argparse
import subprocess
import sys

# Shared paths
CALIBRATION_DIR = "backend/src/data/calibration"
INTRINSIC_DIR = os.path.join(CALIBRATION_DIR, "intrinsic")
EXTRINSIC_DIR = os.path.join(CALIBRATION_DIR, "extrinsic")
BACKEND_URL = "http://localhost:8000/api/robot/state"

def get_robot_pose():
    try:
        response = requests.get(BACKEND_URL, timeout=1.0)
        if response.status_code == 200:
            data = response.json()
            return data.get("tcp_pose_mm_deg", [0, 0, 0, 0, 0, 0])
        return None
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser(description="Unified Calibration Capture (Windows)")
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    parser.add_argument("--mode", type=str, choices=["intrinsic", "extrinsic"], required=True)
    args = parser.parse_args()

    os.makedirs(INTRINSIC_DIR, exist_ok=True)
    os.makedirs(EXTRINSIC_DIR, exist_ok=True)

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"Error: Could not open camera {args.camera}")
        return

    print(f"\n--- Unified Calibration: {args.mode.upper()} Mode ---")
    
    if args.mode == "intrinsic":
        print("1. Show checkerboard. Press SPACE to capture (10+ frames).")
        print("2. Press 'c' to calculate.")
        count = 0
        while True:
            ret, frame = cap.read()
            if not ret: continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ret_corners, corners = cv2.findChessboardCorners(gray, (9, 6), None)
            display = frame.copy()
            if ret_corners:
                cv2.drawChessboardCorners(display, (9, 6), corners, ret_corners)
            cv2.putText(display, f"Captured: {count}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            cv2.imshow("Capture", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord(' '):
                if ret_corners:
                    cv2.imwrite(os.path.join(INTRINSIC_DIR, f"frame_{count:03d}.jpg"), frame)
                    count += 1
            elif key == ord('c'): break
            elif key == ord('q'): return

    elif args.mode == "extrinsic":
        print("1. Click 4 points on the table in the camera feed.")
        print("2. For each point, manually enter the Robot Coordinates (X, Y, Z) from the Teach Pendant.")
        
        clicked_pts = []
        robot_poses = []

        def on_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN and len(clicked_pts) < 4:
                clicked_pts.append([x, y])
                print(f"\nLocked Pixel {len(clicked_pts)}: ({x}, {y})")
                
                # Prompt for robot coordinates immediately after clicking
                while True:
                    try:
                        inp = input(f"Enter Robot X,Y,Z (mm) for Pt {len(clicked_pts)} (e.g. 350.5, -120, 15.2): ")
                        coords = [float(v.strip()) for v in inp.split(",")]
                        if len(coords) == 3:
                            robot_poses.append(coords)
                            print(f"Captured Point {len(robot_poses)}: Pixel={clicked_pts[-1]}, Robot={coords}")
                            break
                        else:
                            print("Error: Please enter exactly 3 values (X, Y, Z).")
                    except ValueError:
                        print("Error: Invalid numbers. Please use format: X, Y, Z")

                if len(robot_poses) == 4:
                    # Save extrinsic data to shared JSON
                    data = {
                        "pixels": clicked_pts,
                        "robot_poses": robot_poses
                    }
                    json_path = os.path.join(EXTRINSIC_DIR, "extrinsic_data.json")
                    with open(json_path, 'w') as f:
                        json.dump(data, f, indent=2)
                    print(f"\nExtrinsic data saved to {json_path}")
                    # Signal loop to end by closing window
                    cv2.destroyAllWindows()

        cv2.namedWindow("Extrinsic Capture")
        cv2.setMouseCallback("Extrinsic Capture", on_mouse)

        while len(robot_poses) < 4:
            ret, frame = cap.read()
            if not ret: continue
            
            display = frame.copy()
            for i, pt in enumerate(clicked_pts):
                cv2.circle(display, tuple(pt), 8, (0, 255, 0), -1)
                cv2.putText(display, f"Pt {i+1}", (pt[0]+10, pt[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            cv2.imshow("Extrinsic Capture", display)
            if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()
    print("\nTriggering Docker math processing...")
    subprocess.run(["docker", "exec", "forgis-backend", "python3", "/app/src/scripts/calibration_math.py", "--mode", args.mode])

if __name__ == "__main__":
    main()
