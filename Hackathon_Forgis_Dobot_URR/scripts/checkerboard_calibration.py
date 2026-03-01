import numpy as np
import cv2
import glob
import argparse
import os

def run_calibration(objpoints, imgpoints, shape):
    """Executes the calibration math and saves the results."""
    if not objpoints:
        print("Error: Could not find calibration targets in any of the images.")
        return None, None
        
    print(f"\nSuccessfully found corners in {len(objpoints)} frames.")
    print("Running camera calibration...")
    # Perform calibration
    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, shape, None, None)

    print("\n" + "="*40)
    print("=== CALIBRATION RESULTS ===")
    print("="*40)
    print("\nCamera Matrix (Intrinsic Parameters):")
    print(mtx)
    print("\nDistortion Coefficients (k1, k2, p1, p2, k3):")
    print(dist)

    # Calculate reprojection error
    mean_error = 0
    for i in range(len(objpoints)):
        imgpoints2, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], mtx, dist)
        error = cv2.norm(imgpoints[i], imgpoints2, cv2.NORM_L2) / len(imgpoints2)
        mean_error += error
        
    avg_reprojection_error = mean_error / len(objpoints)
    print(f"\nTotal Average Reprojection Error: {avg_reprojection_error:.4f} pixels")
    print("(A rule of thumb: an error < 1.0 is acceptable, and < 0.5 is very good.)")
    print("="*40)
    
    # Save the calibration results
    np.savez("camera_calibration_results.npz", camera_matrix=mtx, dist_coeffs=dist)
    print("\nSaved parameters to 'camera_calibration_results.npz'")
    return mtx, dist

def process_images_from_camera(camera_id, checkerboard_size, square_size):
    """Opens a live feed, lets user capture frames manually, then runs calibration."""
    print(f"Opening camera ID {camera_id}...")
    cap = cv2.VideoCapture(camera_id, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    if not cap.isOpened():
        print(f"Error: Cannot open camera {camera_id}")
        return

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    cols, rows = checkerboard_size
    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp = objp * square_size

    objpoints = []
    imgpoints = []
    shape = None

    # Try setting higher resolution (optional, helps with calibration)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    while True:
        ret, img = cap.read()
        if not ret:
            print("Failed to grab frame from camera.")
            break

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if shape is None:
            shape = gray.shape[::-1]

        display_img = img.copy()
        
        # Detect corners live for visual feedback
        ret_corners, corners = cv2.findChessboardCorners(gray, checkerboard_size, None)
        
        if ret_corners:
            cv2.drawChessboardCorners(display_img, checkerboard_size, corners, ret_corners)
            text = "Checkerboard Found! Press SPACE to capture."
            color = (0, 255, 0)
        else:
            text = "Checkerboard not fully visible."
            color = (0, 0, 255)

        # Draw UI overlay
        cv2.putText(display_img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        cv2.putText(display_img, f"Captured: {len(objpoints)} frames", (10, 60), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        cv2.putText(display_img, "Press 'c' to Calibrate, 'q' to Quit", (10, 90), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
                    
        # Resize for display so it fits on screen nicely
        h, w = display_img.shape[:2]
        display_scaled = cv2.resize(display_img, (int(w * 0.75), int(h * 0.75))) if w > 1200 else display_img
        cv2.imshow('Camera Feed', display_scaled)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' '):
            if ret_corners:
                # Need to use raw image, not `display_img` with the drawings over it
                objpoints.append(objp)
                corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
                imgpoints.append(corners2)
                
                # Visual flash
                cv2.imshow('Camera Feed', 255 - display_scaled)
                cv2.waitKey(100)
                print(f"Frame captured! Total: {len(objpoints)}")
            else:
                print("Cannot capture: Checkerboard not fully visible.")
                
        elif key == ord('c'):
            print("Proceeding to calibration...")
            break
        elif key == ord('q'):
            print("Quitting...")
            cap.release()
            cv2.destroyAllWindows()
            return

    cap.release()
    cv2.destroyAllWindows()
    
    if objpoints:
        run_calibration(objpoints, imgpoints, shape)
    else:
        print("No frames captured, calibration aborted.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Intrinsic Camera Calibration Setup")
    parser.add_argument("--camera", type=int, default=None, 
                        help="Camera device ID (e.g., 0 for /dev/video0) to capture live.")
    parser.add_argument("--cols", type=int, default=9, 
                        help="Number of *inner* corners in a row. Default: 9")
    parser.add_argument("--rows", type=int, default=6, 
                        help="Number of *inner* corners in a column. Default: 6")
    parser.add_argument("--size", type=float, default=0.022, 
                        help="Real-world size of a checkerboard square (meters). Default: 0.025")
    parser.add_argument("--no_display", action="store_true", 
                        help="Disable showing images (only applies to image_dir mode).")
    
    args = parser.parse_args()
    checkerboard_dims = (args.cols, args.rows)
    
    if args.camera is not None:
        process_images_from_camera(args.camera, checkerboard_dims, args.size)
    else:
        print("Please provide --camera argument. Use -h for help.")
