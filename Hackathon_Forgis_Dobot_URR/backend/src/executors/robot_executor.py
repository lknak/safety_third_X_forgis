"""Robot executor wrapping RobotNode for motion control."""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional

from .base import Executor

if TYPE_CHECKING:
    from nodes.ur_node import RobotNode

logger = logging.getLogger(__name__)


class RobotExecutor(Executor):
    """
    Executor for robot motion commands.

    Wraps RobotNode and provides async interface for skills.
    Handles the URScript control pattern: send command, poll completion, resend program.
    """

    executor_type = "robot"

    def __init__(self, robot_node: "RobotNode"):
        self._robot = robot_node
        self._motion_poll_interval = 0.1  # seconds

    async def initialize(self) -> None:
        """Wait for robot connection and set TCP.

        Polls for up to 30 s so that slow UR driver starts don't cause a
        false "not connected" result.  Logs progress every 5 s to make it
        easy to diagnose ROBOT_IP / network issues.
        """
        import os
        robot_ip = os.environ.get("ROBOT_IP", "?")
        logger.info("RobotExecutor: waiting for joint states from UR driver (ROBOT_IP=%s)...", robot_ip)
        timeout = 30.0
        elapsed = 0.0
        while not self._robot._has_fresh_joint_state() and elapsed < timeout:
            await asyncio.sleep(0.5)
            elapsed += 0.5
            if elapsed % 5.0 < 0.6:
                logger.info("RobotExecutor: still waiting... (%.0f s elapsed)", elapsed)

        if not self._robot._has_fresh_joint_state():
            logger.warning(
                "RobotExecutor: no joint states after %.0f s — "
                "verify ROBOT_IP=%s is reachable and the UR driver is running",
                timeout, robot_ip,
            )
        else:
            self._robot.set_tcp()
            logger.info("RobotExecutor ready — TCP configured, robot live")

    async def shutdown(self) -> None:
        """No cleanup needed - RobotNode lifecycle managed elsewhere."""
        pass

    def is_ready(self) -> bool:
        """True when the robot is publishing live joint states.

        Uses the fresh-joint-state check directly rather than the stricter
        is_connected() gate (which also requires the resend service).
        This prevents false "disconnected" readings while the UR driver
        service is still coming up after boot.
        """
        return self._robot._has_fresh_joint_state()

    async def move_joint(
        self,
        target_rad: list[float],
        acceleration: float = 1.4,
        velocity: float = 1.05,
        tolerance_rad: float = 0.02,
        timeout: float = 60.0,
    ) -> bool:
        """
        Execute a movej command and wait for completion.

        Args:
            target_rad: Target joint positions in radians.
            acceleration: Joint acceleration in rad/s².
            velocity: Joint velocity in rad/s.
            tolerance_rad: Position tolerance in radians.
            timeout: Maximum time to wait for motion completion.

        Returns:
            True if motion completed successfully, False otherwise.
        """
        logger.info(f"RobotExecutor: Starting movej to {target_rad}")

        # Send the motion command (interrupts External Control)
        self._robot.send_movej(target_rad, accel=acceleration, vel=velocity)

        # Brief settle so the UR has time to accept the script before we poll.
        await asyncio.sleep(0.3)

        # Poll until target reached or timeout
        elapsed = 0.0
        prev_joints: Optional[list[float]] = None
        stable_count = 0
        stable_threshold = 5

        while elapsed < timeout:
            current = self._get_raw_joint_positions()

            if current is not None:
                # Primary check: joints at target
                if all(abs(c - t) < tolerance_rad for c, t in zip(current, target_rad)):
                    logger.info("RobotExecutor: Target reached")
                    await asyncio.sleep(0.2)
                    self._robot.resend_robot_program()
                    return True

                # Stability fallback
                if prev_joints is not None:
                    max_diff = max(abs(c - p) for c, p in zip(current, prev_joints))
                    if max_diff < 0.001:
                        stable_count += 1
                        if stable_count >= stable_threshold:
                            max_err = max(abs(c - t) for c, t in zip(current, target_rad))
                            if max_err < tolerance_rad * 3:
                                logger.info(
                                    "RobotExecutor: Target reached (stable, max_err=%.4f rad)",
                                    max_err,
                                )
                                await asyncio.sleep(0.2)
                                self._robot.resend_robot_program()
                                return True
                    else:
                        stable_count = 0

                prev_joints = list(current)

            await asyncio.sleep(self._motion_poll_interval)
            elapsed += self._motion_poll_interval

        logger.error(f"RobotExecutor: Motion timeout after {timeout}s")
        self._robot.resend_robot_program()
        return False

    async def move_linear(
        self,
        pose: list[float],
        acceleration: float = 1.2,
        velocity: float = 0.25,
        timeout: float = 60.0,
    ) -> bool:
        """
        Execute a movel command and wait for completion.

        Args:
            pose: Target pose [x, y, z, rx, ry, rz] in meters and radians.
            acceleration: Tool acceleration in m/s².
            velocity: Tool velocity in m/s.
            timeout: Maximum time to wait for motion completion.

        Returns:
            True if motion completed successfully, False otherwise.
        """
        logger.info(f"RobotExecutor: Starting movel to {pose}")

        self._robot.send_movel(pose, accel=acceleration, vel=velocity)

        # Brief settle so the UR has time to accept the script before we poll.
        await asyncio.sleep(0.3)

        # Wait for motion to complete by detecting when joints stop moving
        elapsed = 0.0
        prev_joints = None
        stable_count = 0
        stable_threshold = 3  # Number of consecutive stable readings

        while elapsed < timeout:
            await asyncio.sleep(self._motion_poll_interval)
            elapsed += self._motion_poll_interval

            current_joints = self._get_raw_joint_positions()
            if current_joints is None:
                continue

            if prev_joints is not None:
                # Check if joints have stopped moving (all within tolerance)
                max_diff = max(abs(c - p) for c, p in zip(current_joints, prev_joints))
                if max_diff < 0.001:  # Less than ~0.06 degrees movement
                    stable_count += 1
                    if stable_count >= stable_threshold:
                        logger.info(f"RobotExecutor: Motion complete (stable for {stable_count} polls)")
                        await asyncio.sleep(0.2)  # Brief delay before resend
                        self._robot.resend_robot_program()
                        return True
                else:
                    stable_count = 0

            prev_joints = current_joints

        logger.error(f"RobotExecutor: Motion timeout after {timeout}s")
        self._robot.resend_robot_program()
        return False

    def _get_raw_joint_positions(self) -> Optional[list[float]]:
        """Read joint positions bypassing the strict is_connected() gate.

        During primary-script execution the RTDE stream can drop briefly,
        which makes is_connected() return False.  For motion-completion
        polling we only need the cached joint values (they are still updated
        by the subscription callback even if the freshness check fails).
        """
        jp = self._robot._joint_positions
        if jp is None:
            return None
        try:
            from nodes.ur_node import JOINT_NAMES
            return [jp[name] for name in JOINT_NAMES]
        except (KeyError, TypeError):
            return None

    async def jog_joint(
        self,
        target_rad: list[float],
        acceleration: float = 1.4,
        velocity: float = 1.05,
        tolerance_rad: float = 0.02,
        timeout: float = 30.0,
    ) -> bool:
        """
        Jog to a nearby target using a primary movej script.

        Completion is detected with a two-tier strategy:
        1. **Target check** — joints within *tolerance_rad* of target (fast exit).
        2. **Stability check** — joints stop moving for several consecutive
           polls (fallback when RTDE briefly reconnects and the cached
           positions are stale enough for the freshness gate to fail).

        Both tiers read the raw cached joint positions, bypassing the strict
        ``is_connected()`` gate that can return ``None`` during the transient
        period after a primary URScript replaces External Control.
        """
        logger.info(f"RobotExecutor: Jog to {target_rad}")
        self._robot.send_movej(target_rad, accel=acceleration, vel=velocity)

        # Brief settle so the UR has time to accept the script before we poll.
        await asyncio.sleep(0.3)

        elapsed = 0.0
        prev_joints: Optional[list[float]] = None
        stable_count = 0
        stable_threshold = 5  # ~0.5 s of no movement → done

        while elapsed < timeout:
            current = self._get_raw_joint_positions()

            if current is not None:
                # Tier-1: exact target check
                if all(abs(c - t) < tolerance_rad for c, t in zip(current, target_rad)):
                    logger.info("RobotExecutor: Jog complete (target reached)")
                    await asyncio.sleep(0.2)
                    self._robot.resend_robot_program()
                    return True

                # Tier-2: stability check (joints stopped moving)
                if prev_joints is not None:
                    max_diff = max(abs(c - p) for c, p in zip(current, prev_joints))
                    if max_diff < 0.001:  # <0.06 deg movement between polls
                        stable_count += 1
                        if stable_count >= stable_threshold:
                            # Joints are stable — check if we're *reasonably*
                            # close to the target so we don't report success
                            # when the robot never actually moved.
                            max_err = max(abs(c - t) for c, t in zip(current, target_rad))
                            if max_err < tolerance_rad * 5:
                                logger.info(
                                    "RobotExecutor: Jog complete (stable, max_err=%.4f rad)",
                                    max_err,
                                )
                                await asyncio.sleep(0.2)
                                self._robot.resend_robot_program()
                                return True
                            else:
                                logger.warning(
                                    "RobotExecutor: Jog — joints stable but far from target "
                                    "(max_err=%.4f rad). Robot may not have executed the command.",
                                    max_err,
                                )
                                break
                    else:
                        stable_count = 0

                prev_joints = list(current)

            await asyncio.sleep(self._motion_poll_interval)
            elapsed += self._motion_poll_interval

        logger.warning(f"RobotExecutor: Jog timeout after {timeout}s")
        self._robot.resend_robot_program()
        return False

    async def set_digital_output(self, pin: int, value: bool) -> None:
        """
        Set a digital output pin.

        Uses secondary script so it doesn't interrupt motion.
        """
        logger.info(f"RobotExecutor: Setting DO[{pin}] = {value}")
        self._robot.set_digital_output(pin, value)
        await asyncio.sleep(0.05)  # Brief delay for I/O propagation

    def get_joint_positions_deg(self) -> Optional[list[float]]:
        """Get current joint positions in degrees."""
        return self._robot.get_joint_positions_deg()

    def get_state_summary(self) -> dict:
        """Get robot state summary."""
        return self._robot.get_state_summary()

    def get_connection_status(self) -> dict:
        """Detailed connection diagnostics for health checks."""
        has_joints = self._robot._has_fresh_joint_state()
        has_service = self._robot._has_control_service()
        joint_age = None
        if self._robot._joint_positions is not None:
            import time
            joint_age = round(time.monotonic() - self._robot._last_joint_update_monotonic, 2)
        return {
            "has_fresh_joint_state": has_joints,
            "has_control_service": has_service,
            "joint_state_age_s": joint_age,
            "joint_state_timeout_s": self._robot._joint_state_timeout_s,
            "fully_operational": has_joints and has_service,
        }
