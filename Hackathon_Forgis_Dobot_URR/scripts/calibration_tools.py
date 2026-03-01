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
        
        # We'll wait a bit to see what type is being published, or just try to subscribe.
        # To avoid collision, we only subscribe to one. 
        # Attempt to detect or default to PoseStamped.
        self.get_logger().info(f"Subscribing to pose topic: {pose_topic}")
        
        # In ROS 2, we can't easily subscribe to multiple types on the same topic name.
        # We'll use a timer to check the type if it's not immediately obvious, 
        # but for simplicity in this script, we'll just try PoseStamped first.
        # If the user specifically needs Pose, they can change this or we can add an arg.
        self.sub_pose = self.create_subscription(PoseStamped, pose_topic, self.pose_callback, 10)
        
        # We'll also allow a fallback BUT only if it doesn't collide or after we know.
        # For now, let's just use a more flexible subscriber pattern if possible, 
        # or just stick to one and tell the user.
        
        self.latest_image = None
        if image_topic:
            self.bridge = CvBridge()
            self.sub_image = self.create_subscription(Image, image_topic, self.image_callback, 10)

    def pose_callback(self, msg):
        if isinstance(msg, PoseStamped):
            self.latest_position = [msg.pose.position.x, msg.pose.position.y, msg.pose.position.z]
        elif hasattr(msg, 'position'): # Fallback for Pose
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

def on_mouse(event, x, y, flags, param):
    """
    Mouse callback for manual refinement and ADDITION of calibration points.
    """
    if event == cv2.EVENT_LBUTTONDOWN:
        # 1. If we haven't started adding points yet, initialize list
        if param['locked_pts'] is None:
            param['locked_pts'] = [[int(x), int(y)]]
            param['selected_idx'] = 0
            return

        # 2. If we have fewer than 4 points, add a new one
        if len(param['locked_pts']) < 4:
            param['locked_pts'].append([int(x), int(y)])
            param['selected_idx'] = len(param['locked_pts']) - 1
            return

        # 3. If we have exactly 4 points, handle selection/dragging
        for i, (px, py) in enumerate(param['locked_pts']):
            dist = np.hypot(px - x, py - y)
            if dist < 25: # Click radius
                param['selected_idx'] = i
                param['dragging'] = True
                return
    
    elif event == cv2.EVENT_MOUSEMOVE:
        if param['dragging'] and param['selected_idx'] is not None and param['locked_pts'] is not None:
            if param['selected_idx'] < len(param['locked_pts']):
                param['locked_pts'][param['selected_idx']] = [int(x), int(y)]
    
    elif event == cv2.EVENT_LBUTTONUP:
        param['dragging'] = False

def main():
    parser = argparse.ArgumentParser(description="Interactive PnP Calibration using 4 Red Points")
    parser.add_argument("--pose_topic", type=str, default="/robot_pose", help="ROS topic for robot end-effector coordinates")
    parser.add_argument("--pose_type", type=str, default="PoseStamped", choices=["PoseStamped", "Pose"], help="Message type for the pose topic")
    parser.add_argument("--image_topic", type=str, default=None, help="ROS topic for image feed (optional, will use camera device if not provided)")
    parser.add_argument("--camera", type=int, default=0, help="Camera device index if not using image_topic")
    args = parser.parse_args()

    # --- Start ROS Node ---
    rclpy.init()
    
    # Map string type to class
    msg_type = PoseStamped if args.pose_type == "PoseStamped" else Pose
    
    node = CalibrationNode(pose_topic=args.pose_topic, image_topic=args.image_topic)
    # Re-initialize subscription with correct type from args
    node.destroy_subscription(node.sub_pose)
    node.sub_pose = node.create_subscription(msg_type, args.pose_topic, node.pose_callback, 10)
    
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
        cap = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        if not cap.isOpened():
            print(f"Error: Could not open camera {args.camera}")
            sys.exit(1)

    print("\n" + "="*50)
    print("--- Interactive PnP Calibration Workflow ---")
    print(f"Subscribed to Pose topic: {args.pose_topic}")
    print("Workflow:")
    print("  1. Align camera to see all 4 red points clearly.")
    print("  2. Press SPACE to lock the pixel coordinates.")
    print("  3. (Optional) Drag points or use WASD to refine locations.")
    print("  4. Manually guide the robot to each numbered point.")
    print("  5. Press ENTER at each point to save its 3D coordinate.")
    print("====================================================\n")

    # --- State for Interaction ---
    state = {
        'locked_pts': None,
        'selected_idx': None,
        'dragging': False
    }

    cv2.namedWindow("Interactive Calibration")
    cv2.setMouseCallback("Interactive Calibration", on_mouse, state)

    robot_points_3d = []
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
            
            # 2. Point Selection Phase
            if state['locked_pts'] is None or len(state['locked_pts']) < 4:
                # Automatic detection (only if user hasn't started clicking)
                pts = extract_red_points(img) if state['locked_pts'] is None else None
                
                # Show instructions
                cv2.putText(display_img, "MANUAL MODE: Left click 4 points in order", (20, 25), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                
                if pts is not None:
                    # Show auto-detected points
                    for i, (cx, cy) in enumerate(pts):
                        cv2.circle(display_img, (cx, cy), 8, (0, 255, 0), -1)
                        cv2.putText(display_img, f"Pt {i+1}", (cx+15, cy-15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    
                    cv2.putText(display_img, "4 Red Points Found!", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    cv2.putText(display_img, "Press SPACE to lock locations", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                else:
                    # Show manually clicked points
                    if state['locked_pts'] is not None:
                        for i, (cx, cy) in enumerate(state['locked_pts']):
                            cv2.circle(display_img, (cx, cy), 8, (255, 0, 0), -1)
                            cv2.putText(display_img, f"Pt {i+1}", (cx+15, cy-15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
                    
                    msg = f"Click point {len(state['locked_pts']) + 1 if state['locked_pts'] else 1}/4..."
                    cv2.putText(display_img, msg, (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            else:
                # 4 Points are locked (either via SPACE or 4 clicks)
                # Points are locked. Draw them permanently on the display
                for i, (cx, cy) in enumerate(state['locked_pts']):
                    # Highlight the active trajectory goal in Red
                    color = (0, 0, 255) if i == points_collected else (0, 255, 0)
                    active_text = "<-- OVER HERE" if i == points_collected else ""
                    
                    # Selection ring
                    if i == state['selected_idx']:
                        cv2.circle(display_img, (cx, cy), 12, (255, 255, 255), 2)

                    cv2.circle(display_img, (cx, cy), 8, color, -1)
                    cv2.putText(display_img, f"Pt {i+1} {active_text}", (cx+15, cy-15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                    
                if points_collected < 4:
                    cv2.putText(display_img, f"Move Robot Tool to Point {points_collected + 1}", (20, 40), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                    cv2.putText(display_img, "Press ENTER to save ROS pose", (20, 70), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                    cv2.putText(display_img, "Drag pts / WASD to refine", (20, 100), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                
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
                if state['locked_pts'] is None and pts is not None:
                    state['locked_pts'] = pts.tolist()
                    state['selected_idx'] = 0
                    print("\n>> Images points locked! <<")
                    print(">> You can now refine them by dragging with mouse or using WASD.")
                    print(">> Please manually move the robot to each locked point.")
                    # Visual flash
                    cv2.imshow("Interactive Calibration", 255 - display_img)
                    cv2.waitKey(150)
                elif state['locked_pts'] is None and pts is None:
                    print("Cannot lock. 4 red points are not fully visible right now.")

            # Nudge logic (WASD)
            elif key in [ord('w'), ord('a'), ord('s'), ord('d')]:
                if state['locked_pts'] is not None and state['selected_idx'] is not None:
                    idx = state['selected_idx']
                    if key == ord('w'): state['locked_pts'][idx][1] -= 1
                    elif key == ord('s'): state['locked_pts'][idx][1] += 1
                    elif key == ord('a'): state['locked_pts'][idx][0] -= 1
                    elif key == ord('d'): state['locked_pts'][idx][0] += 1

            # Enter key (Carriage Return)
            elif key == 13 or key == 10:
                if state['locked_pts'] is None or len(state['locked_pts']) < 4:
                    print("Please specify 4 image points first (detect red points + SPACE, or click 4 times).")
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
                        image_points_2d=state['locked_pts'],
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
        try:
            rclpy.shutdown()
        except:
            pass

if __name__ == "__main__":
    main()
