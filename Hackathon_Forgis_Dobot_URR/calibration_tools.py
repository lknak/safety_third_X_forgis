import sys
import numpy as np
import cv2
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, Pose
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import threading
import argparse
import time

def calculate_calibration_with_pnp(image_points_2d, intrinsics, robot_points_3d):
    """
    Method 2: If you ONLY have RGB (no depth map), but the 4 points are coplanar on the robot.
    Uses cv2.solvePnP which implicitly computes depth via projective geometry.
    Note: OpenCV computes T_camera_to_robot. So we return its inverse if we want T_camera_to_robot_base.
    """
    print("--- Running RGB Only (SolvePnP) ---")
    img_pts = np.array(image_points_2d, dtype=np.float32)
    obj_pts = np.array(robot_points_3d, dtype=np.float32)
    dist_coeffs = np.zeros((4,1)) # Assuming minimal distortion 
    
    success, rvec, tvec = cv2.solvePnP(obj_pts, img_pts, intrinsics, dist_coeffs)
    
    if not success:
        print("Error: PnP solver failed.")
        return None
        
    R_cam_to_obj, _ = cv2.Rodrigues(rvec)
    
    # Output is Robot -> Camera Transform. 
    # To get T_camera_to_robot (Camera -> Robot), we invert it.
    R_inv = R_cam_to_obj.T
    t_inv = -R_inv @ tvec
    
    T = np.eye(4)
    T[0:3, 0:3] = R_inv
    T[0:3, 3] = t_inv.flatten()
    
    return T

class CalibrationNode(Node):
    def __init__(self, pose_topic, image_topic=None):
        super().__init__('pnp_calibration_node')
        self.latest_position = None
        
        # Subscribe to pose topic (Could be geometry_msgs/PoseStamped or geometry_msgs/Pose)
        self.sub_pose = self.create_subscription(PoseStamped, pose_topic, self.pose_callback, 10)
        self.sub_pose_fallback = self.create_subscription(Pose, pose_topic, self.pose_fallback_callback, 10)
        
        self.latest_image = None
        if image_topic:
            self.bridge = CvBridge()
            self.sub_image = self.create_subscription(Image, image_topic, self.image_callback, 10)

    def pose_callback(self, msg):
        self.latest_position = [msg.pose.position.x, msg.pose.position.y, msg.pose.position.z]

    def pose_fallback_callback(self, msg):
        self.latest_position = [msg.position.x, msg.position.y, msg.position.z]

    def image_callback(self, msg):
        try:
            self.latest_image = self.bridge.imgmsg_to_cv2(msg, "bgr8")
        except Exception as e:
            self.get_logger().error(f"Image conversion error: {str(e)}")

def extract_red_points(img):
    """
    Extracts exactly 4 red centroids from the provided image.
    Returns: numpy array of shape (4, 2) or None if not exactly 4 points found.
    """
    # Convert BGR to HSV
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Red hue wraps around in HSV
    lower_red_1 = np.array([0, 100, 100])
    upper_red_1 = np.array([10, 255, 255])
    lower_red_2 = np.array([160, 100, 100])
    upper_red_2 = np.array([180, 255, 255])
    
    mask1 = cv2.inRange(hsv, lower_red_1, upper_red_1)
    mask2 = cv2.inRange(hsv, lower_red_2, upper_red_2)
    mask = mask1 + mask2
    
    # Remove noise
    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    centroids = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 100: # Tune minimum area based on distance
            M = cv2.moments(cnt)
            if M['m00'] != 0:
                cx = int(M['m10']/M['m00'])
                cy = int(M['m01']/M['m00'])
                centroids.append([cx, cy])
                
    if len(centroids) == 4:
        # Sort spatially: top-left, top-right, bottom-right, bottom-left
        # First sort by Y
        centroids = sorted(centroids, key=lambda p: p[1])
        top = sorted(centroids[:2], key=lambda p: p[0]) # Top row, sort by X
        bottom = sorted(centroids[2:], key=lambda p: p[0]) # Bottom row, sort by X
        ordered = [top[0], top[1], bottom[1], bottom[0]] # Counter-clockwise or standard C-shape
        return np.array(ordered)
    return None

def main():
    parser = argparse.ArgumentParser(description="Interactive PnP Calibration using 4 Red Points")
    parser.add_argument("--pose_topic", type=str, default="/robot_pose", help="ROS topic for robot end-effector coordinates")
    parser.add_argument("--image_topic", type=str, default=None, help="ROS topic for image feed (optional, will use camera device if not provided)")
    parser.add_argument("--camera", type=int, default=0, help="Camera device index if not using image_topic")
    args = parser.parse_args()

    # --- Start ROS Node ---
    rclpy.init()
    node = CalibrationNode(pose_topic=args.pose_topic, image_topic=args.image_topic)
    
    spin_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_thread.start()

    # --- Setup Camera Intrinsics ---
    try:
        calib = np.load("camera_calibration_results.npz")
        cam_intrinsics = calib["camera_matrix"]
        print("Loaded camera intrinsics from 'camera_calibration_results.npz'")
    except Exception as e:
        print("Could not load 'camera_calibration_results.npz'. Using default dummy intrinsics. Ensure you run checkerboard_calibration.py first!")
        cam_intrinsics = np.array([
            [600.0, 0.0, 320.0],
            [0.0, 600.0, 240.0],
            [0.0, 0.0, 1.0]
        ])

    cap = None
    if args.image_topic is None:
        cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            print(f"Error: Could not open camera {args.camera}")
            sys.exit(1)

    print("\n" + "="*50)
    print("--- Interactive PnP Calibration Workflow ---")
    print(f"Subscribed to Pose topic: {args.pose_topic}")
    print("Workflow:")
    print("  1. Align camera to see all 4 red points clearly.")
    print("  2. Press SPACE to lock the pixel coordinates.")
    print("  3. Manually guide the robot to each numbered point.")
    print("  4. Press ENTER at each point to save its 3D coordinate.")
    print("====================================================\n")

    robot_points_3d = []
    locked_image_points_2d = None
    points_collected = 0
    pts = None

    try:
        while True:
            # 1. Get Image
            img = None
            if cap is not None:
                ret, img = cap.read()
                if not ret:
                    continue
            else:
                img = node.latest_image
                if img is None:
                    time.sleep(0.01)
                    continue
            
            display_img = img.copy()
            
            # 2. Extract Red Points if we haven't locked them yet
            if locked_image_points_2d is None:
                pts = extract_red_points(img)
                if pts is not None:
                    for i, (cx, cy) in enumerate(pts):
                        cv2.circle(display_img, (cx, cy), 8, (0, 255, 0), -1)
                        cv2.putText(display_img, f"Pt {i+1}", (cx+15, cy-15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    
                    cv2.putText(display_img, "4 Red Points Found!", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    cv2.putText(display_img, "Press SPACE to lock locations", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                else:
                    cv2.putText(display_img, "Looking for exact 4 red points...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            else:
                # Points are locked. Draw them permanently on the display
                for i, (cx, cy) in enumerate(locked_image_points_2d):
                    # Highlight the active trajectory goal in Red
                    color = (0, 0, 255) if i == points_collected else (0, 255, 0)
                    active_text = "<-- OVER HERE" if i == points_collected else ""
                    
                    cv2.circle(display_img, (cx, cy), 8, color, -1)
                    cv2.putText(display_img, f"Pt {i+1} {active_text}", (cx+15, cy-15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                    
                if points_collected < 4:
                    cv2.putText(display_img, f"Move Robot Tool to Point {points_collected + 1}", (20, 40), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                    cv2.putText(display_img, "Press ENTER to save ROS pose", (20, 70), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                
            # Log current points collected
            cv2.putText(display_img, f"Poses Saved: {points_collected}/4", (20, img.shape[0] - 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            # 3. Show Image
            cv2.imshow("Interactive Calibration", display_img)
            
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                print("Quitting...")
                break
                
            # SPACE bar
            elif key == ord(' '):
                if locked_image_points_2d is None and pts is not None:
                    locked_image_points_2d = pts
                    print("\n>> Images points locked! <<")
                    print(">> Please manually move the robot to each locked point.")
                    # Visual flash
                    cv2.imshow("Interactive Calibration", 255 - display_img)
                    cv2.waitKey(150)
                elif locked_image_points_2d is None and pts is None:
                    print("Cannot lock. 4 red points are not fully visible right now.")

            # Enter key (Carriage Return)
            elif key == 13 or key == 10:
                if locked_image_points_2d is None:
                    print("Please lock the 4 image points first by pressing SPACE.")
                    continue
                    
                if points_collected >= 4:
                    print("Already collected 4 points.")
                    continue

                if node.latest_position is None:
                    print(f"Cannot save: No position received yet from `{args.pose_topic}`. Are you sure you are publishing it?")
                    continue
                
                print(f"Success! Point {points_collected + 1} Saved | Robot Coordinates (x,y,z): {node.latest_position}")
                robot_points_3d.append(node.latest_position)
                points_collected += 1
                
                # Visual flash
                cv2.imshow("Interactive Calibration", 255 - display_img)
                cv2.waitKey(200)
                
                if points_collected == 4:
                    print("\n--- All 4 Points Collected ---")
                    print("Executing SolvePnP...")
                    T_pnp = calculate_calibration_with_pnp(
                        image_points_2d=locked_image_points_2d,
                        intrinsics=cam_intrinsics,
                        robot_points_3d=robot_points_3d
                    )
                    
                    if T_pnp is not None:
                        print("\n=== FINAL TRANSFORMATION MATRIX (Camera base to Robot base) ===")
                        print(T_pnp)
                        print("=====================================================\n")
                        
                        # Save it for later use
                        np.save("camera_to_robot_transform.npy", T_pnp)
                        print("Saved transformation to 'camera_to_robot_transform.npy'")
                        
                        print("\nCalibration workflow complete. Press 'q' to quit.")
                        
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        
    finally:
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
