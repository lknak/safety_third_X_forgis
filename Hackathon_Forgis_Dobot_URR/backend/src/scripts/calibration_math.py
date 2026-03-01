import cv2
import numpy as np
import os
import glob
import json
import argparse

# Paths inside Docker
CALIBRATION_DIR = "/app/src/data/calibration"
INTRINSIC_DIR = os.path.join(CALIBRATION_DIR, "intrinsic")
EXTRINSIC_DIR = os.path.join(CALIBRATION_DIR, "extrinsic")
OUTPUT_DIR = "/app/src/data"

def run_intrinsic():
    print("--- Running Intrinsic Calibration Calculation ---")
    checkerboard_size = (9, 6)
    square_size = 25.0 # mm
    objp = np.zeros((checkerboard_size[0] * checkerboard_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:checkerboard_size[0], 0:checkerboard_size[1]].T.reshape(-1, 2)
    objp *= square_size
    obj_points, img_points = [], []
    image_paths = glob.glob(os.path.join(INTRINSIC_DIR, "*.jpg"))
    if not image_paths:
        print(f"Error: No images found in {INTRINSIC_DIR}")
        return
    shape = None
    for path in image_paths:
        img = cv2.imread(path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        shape = gray.shape[::-1]
        ret, corners = cv2.findChessboardCorners(gray, checkerboard_size, None)
        if ret:
            obj_points.append(objp)
            img_points.append(corners)
    if not img_points:
        print("Error: No corners found.")
        return
    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(obj_points, img_points, shape, None, None)
    if ret:
        np.savez(os.path.join(OUTPUT_DIR, "camera_calibration_results.npz"), 
                 camera_matrix=mtx, dist_coeffs=dist, rvecs=rvecs, tvecs=tvecs)
        print("Intrinsic calibration successful!")
    else:
        print("Calibration failed.")

def run_extrinsic():
    print("--- Running Extrinsic Calibration Calculation (PnP) ---")
    json_path = os.path.join(EXTRINSIC_DIR, "extrinsic_data.json")
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return
    with open(json_path, 'r') as f:
        data = json.load(f)
    pixels = np.array(data["pixels"], dtype=np.float32)
    # Robot poses are [x, y, z] in mm
    robot_poses = np.array(data["robot_poses"], dtype=np.float32)
    obj_pts = robot_poses / 1000.0 # Convert to meters
    intrinsics_path = os.path.join(OUTPUT_DIR, "camera_calibration_results.npz")
    if not os.path.exists(intrinsics_path):
        print("Error: Intrinsics not found. Run intrinsic mode first!")
        return
    calib = np.load(intrinsics_path)
    mtx, dist = calib["camera_matrix"], calib["dist_coeffs"]
    success, rvec, tvec = cv2.solvePnP(obj_pts, pixels, mtx, dist)
    if success:
        R_obj_to_cam, _ = cv2.Rodrigues(rvec)
        R_inv = R_obj_to_cam.T
        t_inv = -R_inv @ tvec
        T = np.eye(4)
        T[0:3, 0:3], T[0:3, 3] = R_inv, t_inv.flatten()
        np.save(os.path.join(OUTPUT_DIR, "camera_to_robot_transform.npy"), T)
        print("Extrinsic calibration successful!")
    else:
        print("solvePnP failed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", type=str, choices=["intrinsic", "extrinsic"], required=True)
    args = parser.parse_args()
    if args.mode == "intrinsic": run_intrinsic()
    elif args.mode == "extrinsic": run_extrinsic()
