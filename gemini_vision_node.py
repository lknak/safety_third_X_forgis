#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import os
import json

from google import genai
from google.genai import types

from dotenv import load_dotenv
load_dotenv()

class GeminiVisionNode(Node):
    def __init__(self):
        super().__init__('gemini_vision_node')
        # Subscribing to the image topic that is currently running
        self.subscription = self.create_subscription(
            Image,
            '/image_raw',
            self.image_callback,
            10)
        self.bridge = CvBridge()
        
        # Look for GEMINI_API_KEY in the environment loaded from .env
        api_key = os.environ.get("GEMINI_API_KEY")
        
        self.client = genai.Client(api_key=api_key)
        self.processing = False
        self.get_logger().info("Gemini Vision Node initialized. Waiting for image on /image_raw...")

    def image_callback(self, msg):
        # We only want to process one image at a time
        if self.processing:
            return

        self.processing = True
        self.get_logger().info("Received image! Converting and sending to Gemini...")

        try:
            # Convert ROS Image message to OpenCV image
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            
            # Encode OpenCV image to JPEG bytes
            success, encoded_image = cv2.imencode('.jpg', cv_image)
            if not success:
                self.get_logger().error("Failed to encode image to JPEG")
                self.processing = False
                return

            image_bytes = encoded_image.tobytes()

            PROMPT = """
            1. Locate the robot gripper's suction cup and the center of the box in this image.
            2. Provide their coordinates in [y, x] format (0-1000).
            3. Generate a sequence of 10 steps for the robot to move to the box.
            4. Generate a list of [y, x] normalized waypoints (0-1000) that form a safe path from the robot's current position to the box, avoiding any visible obstacles.
            5. Output the result in JSON format with 'coordinates', 'steps', and 'waypoints' keys.
            """

            response = self.client.models.generate_content(
                model="gemini-robotics-er-1.5-preview", 
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    PROMPT
                ]
            )

            self.get_logger().info(f"Gemini Response:\n{response.text}")

            # Parse the JSON response
            try:
                # Find the JSON part in the response (it might be wrapped in ```json ... ```)
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
                coords = data.get('coordinates', {})
                robot_pos = coords.get('robot')
                box_pos = coords.get('box')
                
                if robot_pos:
                    px_robot = to_pixel(robot_pos)
                    cv2.circle(cv_image, px_robot, 10, (255, 0, 0), -1)
                    cv2.putText(cv_image, 'Robot', (px_robot[0]+15, px_robot[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
                    
                if box_pos:
                    px_box = to_pixel(box_pos)
                    cv2.circle(cv_image, px_box, 10, (0, 0, 255), -1)
                    cv2.putText(cv_image, 'Box', (px_box[0]+15, px_box[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                
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
                output_path = '/home/wayl/workspace/waypoints_output.jpg'
                cv2.imwrite(output_path, cv_image)
                self.get_logger().info(f"Saved waypoint image to {output_path}")
                
            except Exception as parse_e:
                self.get_logger().error(f"Failed to parse and draw waypoints: {parse_e}")

        except Exception as e:
            self.get_logger().error(f"Error calling Gemini: {e}")
            
        finally:
            # Process one image and then shut down. 
            # If you want it to run continuously on a timer, you can remove shutdown and reset processing
            self.get_logger().info("Finished processing. Shutting down node.")
            rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    node = GeminiVisionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except rclpy.executors.ExternalShutdownException:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()

if __name__ == '__main__':
    main()
