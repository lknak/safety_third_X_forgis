"""ROS 2 node for camera image subscription."""

import os
import threading
from typing import Optional

import cv2
import numpy as np
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image


class CameraNode(Node):
    """
    ROS 2 node that subscribes to camera images from a configurable ROS topic.

    Stores the latest frame and a cached JPEG in a thread-safe manner
    for access by the executor.
    """

    def __init__(self):
        super().__init__("camera_node")

        self._frame: Optional[np.ndarray] = None
        self._frame_jpeg: Optional[bytes] = None
        self._frame_lock = threading.Lock()

        self._image_topic = os.environ.get("CAMERA_IMAGE_TOPIC", "/image_raw")

        # QoS tuned for camera streams (BEST_EFFORT, low latency).
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )

        self.create_subscription(Image, self._image_topic, self._on_image, qos)
        self.get_logger().info(f"CameraNode initialized - waiting for {self._image_topic}")

    def _on_image(self, msg: Image) -> None:
        """Convert ROS Image to OpenCV BGR numpy array and cache it + JPEG."""
        encoding = (msg.encoding or "").lower()
        frame = np.frombuffer(msg.data, dtype=np.uint8).reshape((msg.height, msg.width, 3))

        if encoding == "rgb8":
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        elif encoding == "bgr8":
            frame_bgr = frame
        else:
            self.get_logger().warn(
                f"Unsupported image encoding: {msg.encoding}; expected rgb8/bgr8",
                throttle_duration_sec=5.0,
            )
            return

        success, jpeg_data = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])

        with self._frame_lock:
            self._frame = frame_bgr
            if success:
                self._frame_jpeg = jpeg_data.tobytes()

        if not hasattr(self, "_recv_count"):
            self._recv_count = 0
        self._recv_count += 1
        if self._recv_count % 100 == 0:
            self.get_logger().info(f"Received {self._recv_count} frames ({msg.width}x{msg.height})")

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Get the latest camera frame as BGR numpy array."""
        with self._frame_lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def get_frame_jpeg(self, quality: int = 80) -> Optional[bytes]:
        """Get the latest frame as JPEG bytes (cached)."""
        with self._frame_lock:
            return self._frame_jpeg

    def get_frame_dimensions(self) -> Optional[tuple[int, int]]:
        """Get current frame dimensions as (width, height)."""
        with self._frame_lock:
            if self._frame is None:
                return None
            h, w = self._frame.shape[:2]
            return (w, h)

    def has_frame(self) -> bool:
        """Check if at least one frame has been received."""
        with self._frame_lock:
            return self._frame is not None
