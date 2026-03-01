"""Executor for the pneumatic gripper (now replaces COVVI hand)."""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from .base import Executor

if TYPE_CHECKING:
    from nodes.pneumatic_gripper_node import PneumaticGripperNode

logger = logging.getLogger(__name__)


class HandExecutor(Executor):
    """
    Executor for Gripper operations.
    
    Wraps PneumaticGripperNode and provides an async interface for skills.
    This replaces the COVVI hand implementation.
    """

    executor_type = "hand"

    def __init__(self, hand_node: "PneumaticGripperNode"):
        self._node = hand_node

    async def initialize(self) -> None:
        """Wait for the robot (and thus the gripper) connection to be established."""
        logger.info("GripperExecutor (was HandExecutor) initializing...")
        timeout = 10.0
        elapsed = 0.0
        while not self._node.is_connected() and elapsed < timeout:
            await asyncio.sleep(0.1)
            elapsed += 0.1
        if self._node.is_connected():
            logger.info("GripperExecutor ready")
        else:
            logger.warning(
                "GripperExecutor: Robot connection not reachable after timeout — "
                "gripper skills will fail until connection is established"
            )

    async def shutdown(self) -> None:
        pass

    def is_ready(self) -> bool:
        return self._node.is_connected()

    async def open(self) -> bool:
        """Open pneumatic gripper solenoid."""
        logger.info("GripperExecutor: opening gripper")
        return self._node.open_gripper()

    async def close(self) -> bool:
        """Close pneumatic gripper solenoid."""
        logger.info("GripperExecutor: closing gripper")
        return self._node.close_gripper()

    async def set_grip(self, grip_name: str) -> None:
        """Compatibility for old 'SetGrip' skill. Maps to open/close."""
        logger.info(f"GripperExecutor: set_grip={grip_name!r}")
        if grip_name.upper() in ["OPEN", "RELAXED"]:
            self._node.open_gripper()
        else:
            self._node.close_gripper()

    async def set_finger_positions(self, speed: int = 50, **fingers) -> None:
        """Compatibility for 'SetFingerPositions'. Maps to open/close based on average."""
        avg_pos = sum(fingers.values()) / len(fingers) if fingers else 0
        if avg_pos > 50:
            self._node.close_gripper()
        else:
            self._node.open_gripper()
        await asyncio.sleep(0.05)

    def get_hand_state(self) -> Optional[dict]:
        """Return the latest gripper state."""
        return self._node.get_hand_state()

    def get_hand_status(self) -> Optional[dict]:
        """Return latest status flags."""
        return self._node.get_hand_status()

    async def grip_until_contact(
        self,
        speed: int,
        fingers: list,
        min_contacts: int,
        timeout_s: float,
    ) -> dict:
        """
        Pneumatic grippers typically don't detect contact. Simply close and return success.
        """
        self._node.close_gripper()
        await asyncio.sleep(0.5) # Simulating movement time
        return {"contacted": True, "contact_fingers": fingers}
