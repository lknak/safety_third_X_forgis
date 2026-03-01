"""Quick test: check frame brightness from ROS /image_raw topic."""
import json
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

rclpy.init()
node = rclpy.create_node("test_cam_brightness")
qos = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
result = [None]

def cb(msg):
    arr = np.frombuffer(msg.data, dtype=np.uint8).reshape((msg.height, msg.width, 3))
    if msg.encoding.lower() == "rgb8":
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    h = arr.shape[0]
    m = float(np.mean(arr))
    t = float(np.mean(arr[:20, :, :]))
    b = float(np.mean(arr[h // 2 :, :, :]))
    nonzero_pct = float(np.count_nonzero(arr) / arr.size * 100)
    result[0] = {
        "w": msg.width,
        "h": msg.height,
        "enc": msg.encoding,
        "data_len": len(msg.data),
        "expected_len": msg.height * msg.width * 3,
        "step": msg.step,
        "mean": round(m, 1),
        "top20_mean": round(t, 1),
        "bottom_half_mean": round(b, 1),
        "nonzero_pct": round(nonzero_pct, 1),
    }
    print(json.dumps(result[0], indent=2))

node.create_subscription(Image, "/image_raw", cb, qos)

for _ in range(50):
    rclpy.spin_once(node, timeout_sec=0.1)
    if result[0]:
        break

if not result[0]:
    print("No frames received on /image_raw in 5 seconds")

node.destroy_node()
rclpy.shutdown()
