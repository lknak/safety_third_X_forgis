import json
import math
import os
import time
from typing import Optional, List

from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger
from sensor_msgs.msg import JointState
from ur_msgs.msg import IOStates
from geometry_msgs.msg import PoseStamped


# UR3 joint names
JOINT_NAMES = [
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
]


def _quaternion_to_axis_angle(x: float, y: float, z: float, w: float) -> List[float]:
    """Convert quaternion (x,y,z,w) to axis-angle (rx,ry,rz) in radians."""
    # Normalise
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm < 1e-12:
        return [0.0, 0.0, 0.0]
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    angle = 2.0 * math.acos(max(-1.0, min(1.0, w)))
    sin_half = math.sin(angle / 2.0)
    if abs(sin_half) < 1e-12:
        return [0.0, 0.0, 0.0]
    return [angle * x / sin_half, angle * y / sin_half, angle * z / sin_half]


class RobotNode(Node):
    def __init__(self):
        super().__init__("robot_node")

        # Publishers
        self.script_pub = self.create_publisher(String, "/urscript_interface/script_command", 10)
        self.digital_in_pub = self.create_publisher(String, "/events/digital_input_change", 10)

        # Subscribers — joint states
        self._joint_positions: Optional[dict] = None
        self._last_joint_update_monotonic: float = 0.0
        self._joint_state_timeout_s: float = float(
            os.environ.get("ROBOT_JOINT_STATE_TIMEOUT_S", "2.0")
        )
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, 10)

        # Subscribers — IO states
        self._io_states: Optional[IOStates] = None
        self._prev_digital_in: dict[int, bool] = {}
        self.create_subscription(IOStates, "/io_and_status_controller/io_states", self._on_io_states, 10)

        # Subscribers — TCP pose from tcp_pose_broadcaster
        self._tcp_pose: Optional[List[float]] = None  # [x, y, z, rx, ry, rz] m+rad
        self.create_subscription(PoseStamped, "/tcp_pose_broadcaster/pose", self._on_tcp_pose, 10)

        # Service Client
        self._resend_client = self.create_client(
            Trigger,
            "/io_and_status_controller/resend_robot_program",
        )

        # TCP configuration from environment (format: "x,y,z,rx,ry,rz" in meters and radians)
        # Default: 55mm Z offset (0.055 meters)
        tcp_str = os.environ.get("ROBOT_TCP_OFFSET", "0,0,0.055,0,0,0")
        self._tcp_offset: List[float] = [float(v.strip()) for v in tcp_str.split(",")]
        self.get_logger().info(f"TCP offset configured: {self._tcp_offset}")

        self.get_logger().info("RobotNode initialized")

    def _on_joint_states(self, msg: JointState):
        if len(msg.name) == len(msg.position):
            self._joint_positions = dict(zip(msg.name, msg.position))
            self._last_joint_update_monotonic = time.monotonic()

    def _on_tcp_pose(self, msg: PoseStamped):
        p = msg.pose.position
        q = msg.pose.orientation
        rx, ry, rz = _quaternion_to_axis_angle(q.x, q.y, q.z, q.w)
        self._tcp_pose = [p.x, p.y, p.z, rx, ry, rz]

    def _on_io_states(self, msg: IOStates):
        # Detect rising edges on digital inputs
        for s in msg.digital_in_states:
            pin = s.pin
            current = s.state
            prev = self._prev_digital_in.get(pin, False)
            if current and not prev:
                self.get_logger().info(f"Rising edge on digital_in[{pin}]")
                event = String()
                event.data = json.dumps({
                    "pin": pin,
                    "edge": "rising",
                    "timestamp": time.time(),
                })
                self.digital_in_pub.publish(event)
            self._prev_digital_in[pin] = current
        self._io_states = msg


    def send_script(self, script: str) -> None:
        """
        Publish raw URScript to the robot.

        WARNING: this INTERRUPTS the External Control program. The robot will
        execute this script, then stop. After it finishes, call
        resend_robot_program() to restore ros2_control.

        For commands that should NOT interrupt (IO, popups), use
        send_secondary_script() instead.
        """
        msg = String()
        msg.data = script
        self.script_pub.publish(msg)
        self.get_logger().info(f"URScript sent ({len(script)} chars)")

    def send_secondary_script(self, script_body: str) -> None:
        """
        Wrap as secondary program — runs in parallel, does NOT interrupt
        the External Control program or any active motion controller.

        Use for: set_digital_out, popup, textmsg, or any quick command.
        """
        indented = "\n".join(f"  {line}" for line in script_body.strip().split("\n"))
        full_script = f"sec my_sec_prog():\n{indented}\nend\n"
        self.send_script(full_script)

    def set_tcp(self, tcp: Optional[List[float]] = None) -> None:
        """
        Set the Tool Center Point (TCP) offset.

        Args:
            tcp: TCP offset [x, y, z, rx, ry, rz] in meters and radians.
                 If None, uses the configured TCP from environment.
        """
        tcp = tcp or self._tcp_offset
        tcp_str = ", ".join(f"{v:.6f}" for v in tcp)
        self.send_secondary_script(f"set_tcp(p[{tcp_str}])")
        self.get_logger().info(f"TCP set to: {tcp}")

    def send_movej_secondary(self, target_rad: List[float], accel: float = 1.4, vel: float = 1.05) -> None:
        """movej via secondary program — does NOT interrupt External Control."""
        joints_str = ", ".join(f"{j:.5f}" for j in target_rad)
        tcp_str = ", ".join(f"{v:.6f}" for v in self._tcp_offset)
        self.send_secondary_script(
            f"set_tcp(p[{tcp_str}])\nmovej([{joints_str}], a={accel}, v={vel})"
        )

    def send_movej(self, target_rad: List[float], accel: float = 1.4, vel: float = 1.05) -> None:
        joints_str = ", ".join(f"{j:.5f}" for j in target_rad)
        tcp_str = ", ".join(f"{v:.6f}" for v in self._tcp_offset)
        script = f"set_tcp(p[{tcp_str}])\nmovej([{joints_str}], a={accel}, v={vel})\n"
        self.send_script(script)

    def send_movel(self, pose: List[float], accel: float = 1.2, vel: float = 0.25) -> None:
        pose_str = ", ".join(f"{p:.5f}" for p in pose)
        tcp_str = ", ".join(f"{v:.6f}" for v in self._tcp_offset)
        script = f"set_tcp(p[{tcp_str}])\nmovel(p[{pose_str}], a={accel}, v={vel})\n"
        self.send_script(script)

    def set_digital_output(self, pin: int, value: bool) -> None:
        val_str = "True" if value else "False"
        self.send_secondary_script(f"set_digital_out({pin}, {val_str})")

    def resend_robot_program(self) -> bool:
        """
        Must be called after send_script() / send_movej() / send_movel()
        once the robot has finished executing the script.
        """
        if not self._resend_client.service_is_ready():
            self.get_logger().warn("resend_robot_program service not available")
            return False

        future = self._resend_client.call_async(Trigger.Request())

        # Wait for the result — the MultiThreadedExecutor handles the callback
        t0 = time.monotonic()
        while not future.done() and time.monotonic() - t0 < 5.0:
            time.sleep(0.1)

        if not future.done():
            self.get_logger().error("resend_robot_program timed out")
            return False

        result = future.result()
        if not result.success:
            self.get_logger().warn(f"resend_robot_program failed: {result.message}")
            return False

        self.get_logger().info("Robot program resent — control restored")
        return True

    def joints_at_target(self, target_rad: List[float], tolerance: float = 0.02) -> bool:
        """Check if current joints are within tolerance of target.
        Pipelines poll this to know when motion is complete."""
        current = self.get_joint_positions()
        if current is None:
            return False
        return all(abs(c - t) < tolerance for c, t in zip(current, target_rad))

    def _has_fresh_joint_state(self) -> bool:
        if self._joint_positions is None:
            return False
        age = time.monotonic() - self._last_joint_update_monotonic
        return age <= self._joint_state_timeout_s

    def _has_control_service(self) -> bool:
        return self._resend_client.service_is_ready()

    def _has_io_states(self) -> bool:
        if self._io_states is None:
            return False
        return (
            len(self._io_states.digital_in_states) > 0
            or len(self._io_states.digital_out_states) > 0
        )

    def is_connected(self) -> bool:
        # Motion control only requires fresh joint data and the control service.
        # IO states are checked separately when needed (get_digital_input, etc.).
        return (
            self._has_fresh_joint_state()
            and self._has_control_service()
        )

    def get_joint_positions(self) -> Optional[List[float]]:
        if not self.is_connected():
            return None
        return [self._joint_positions[name] for name in JOINT_NAMES]

    def get_joint_positions_deg(self) -> Optional[List[float]]:
        rads = self.get_joint_positions()
        if rads is None:
            return None
        return [math.degrees(r) for r in rads]

    def get_tcp_pose(self) -> Optional[List[float]]:
        """Get raw TCP pose [x, y, z, rx, ry, rz] in meters and radians."""
        return list(self._tcp_pose) if self._tcp_pose is not None else None

    def get_tcp_pose_mm_deg(self) -> Optional[List[float]]:
        """Get TCP pose as [x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg]."""
        if self._tcp_pose is None:
            return None
        x, y, z, rx, ry, rz = self._tcp_pose
        return [
            x * 1000.0, y * 1000.0, z * 1000.0,
            math.degrees(rx), math.degrees(ry), math.degrees(rz),
        ]

    def get_digital_input(self, pin: int) -> Optional[bool]:
        if self._io_states is None:
            return None
        if pin >= len(self._io_states.digital_in_states):
            return None
        return self._io_states.digital_in_states[pin].state

    def get_digital_output(self, pin: int) -> Optional[bool]:
        if self._io_states is None:
            return None
        if pin >= len(self._io_states.digital_out_states):
            return None
        return self._io_states.digital_out_states[pin].state

    def get_state_summary(self) -> dict:
        connected = self.is_connected()
        return {
            "timestamp": time.time(),
            "connected": connected,
            "joints_deg": self.get_joint_positions_deg(),
            "tcp_pose_mm_deg": self.get_tcp_pose_mm_deg(),
            "io": {
                "digital_in": [
                    {"pin": s.pin, "state": s.state}
                    for s in (self._io_states.digital_in_states if self._io_states else [])
                ],
                "digital_out": [
                    {"pin": s.pin, "state": s.state}
                    for s in (self._io_states.digital_out_states if self._io_states else [])
                ],
            },
        }
