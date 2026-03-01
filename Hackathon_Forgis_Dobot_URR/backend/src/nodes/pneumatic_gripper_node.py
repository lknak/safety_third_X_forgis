import os
import logging
from typing import Union, Optional
from rclpy.node import Node
from .ur_node import RobotNode
from .dobot_nova5_node import DobotNova5Node

logger = logging.getLogger(__name__)

class PneumaticGripperNode:
    """
    ROS 2-style node that controls a pneumatic gripper via 2 digital outputs
    on the robot controller (or tool head).
    
    This replaces the COVVI hand and provides simple open/close methods.
    """
    def __init__(self, robot_node: Union[RobotNode, DobotNova5Node]):
        self._robot = robot_node
        self._open_pin = int(os.environ.get("GRIPPER_OPEN_PIN", "0"))
        self._close_pin = int(os.environ.get("GRIPPER_CLOSE_PIN", "1"))
        self._robot_type = os.environ.get("ROBOT_TYPE", "ur").lower()
        
        # We store the state for UI purposes
        self._last_state = "unknown" # "open", "closed", "unknown"

    def open_gripper(self) -> bool:
        """Set DOUT to open state."""
        logger.info(f"Opening pneumatic gripper (DOUT[{self._open_pin}]=True, DOUT[{self._close_pin}]=False)")
        try:
            if self._robot_type == "dobot":
                # For DOBOT, use ToolDO for now or standard DO if available
                # Assuming index 1 and 2 for open/close solenoid
                self._robot.tool_do(self._open_pin, 1)
                self._robot.tool_do(self._close_pin, 0)
            else:
                self._robot.set_digital_output(self._open_pin, True)
                self._robot.set_digital_output(self._close_pin, False)
            self._last_state = "open"
            return True
        except Exception as e:
            logger.error(f"Failed to open pneumatic gripper: {e}")
            return False

    def close_gripper(self) -> bool:
        """Set DOUT to closed state."""
        logger.info(f"Closing pneumatic gripper (DOUT[{self._open_pin}]=False, DOUT[{self._close_pin}]=True)")
        try:
            if self._robot_type == "dobot":
                self._robot.tool_do(self._open_pin, 0)
                self._robot.tool_do(self._close_pin, 1)
            else:
                self._robot.set_digital_output(self._open_pin, False)
                self._robot.set_digital_output(self._close_pin, True)
            self._last_state = "closed"
            return True
        except Exception as e:
            logger.error(f"Failed to close pneumatic gripper: {e}")
            return False

    def get_hand_state(self) -> Optional[dict]:
        """
        Mock for compatibility with HandExecutor.
        Pneumatic grippers usually don't have partial finger positions (0 or 100).
        """
        val = 0 if self._last_state == "open" else 100
        return {
            "thumb": val,
            "index": val,
            "middle": val,
            "ring": val,
            "little": val,
            "rotate": 0,
            "pneumatic_state": self._last_state
        }

    def get_hand_status(self) -> Optional[dict]:
        """Mock for compatibility. Returns stall=False (pnuematic grippers don't detect stalls typically)."""
        return {
            "thumb": False,
            "index": False,
            "middle": False,
            "little": False,
        }

    def stop_fingers(self):
        """No action needed for pneumatic solenoid typically."""
        pass

    def is_connected(self) -> bool:
        """Status depends on the robot connection."""
        return self._robot.is_connected()

    def destroy_node(self):
        """Required by main loop cleanup."""
        pass
