import logging
import os
from typing import Any, Optional

from executors.base import Executor

logger = logging.getLogger(__name__)


class HealthService:
    """Manages health and diagnostics of all hardware devices/executors."""

    def __init__(self, executors: dict[str, Executor]):
        self.executors = executors
        self._input_mode = os.environ.get("CAMERA_INPUT_MODE", "bridge").strip().lower()

    async def get_overall_health(self) -> dict[str, Any]:
        """Get the health status of all devices."""
        health_data: dict[str, Any] = {}
        all_ready = True

        for name, executor in self.executors.items():
            if name == "camera":
                health_data[name] = self._check_camera(executor)
                if health_data[name]["status"] != "connected":
                    all_ready = False
                continue

            is_ready = executor.is_ready()
            if not is_ready:
                all_ready = False

            health_data[name] = {
                "status": "connected" if is_ready else "disconnected",
                "error": None if is_ready else f"{name.replace('_', ' ').title()} is not responding.",
                "suggestion": None if is_ready else self._suggestion(name),
                "device_type": self._device_type(name),
                "display_name": name.replace("_", " ").title(),
            }

        return {
            "overall_status": "healthy" if all_ready else "degraded",
            "devices": health_data,
        }

    def _check_camera(self, executor) -> dict[str, Any]:
        """Check camera health. Simple: frames arriving = connected."""
        has_frame = False
        if hasattr(executor, "get_state_summary"):
            summary = executor.get_state_summary()
            has_frame = bool(summary.get("connected")) if isinstance(summary, dict) else False

        if has_frame:
            return {
                "status": "connected",
                "error": None,
                "suggestion": None,
                "device_type": "camera",
                "display_name": "Camera",
                "detected": True,
                "source": "bridge" if self._input_mode == "bridge" else "ros_topic",
            }

        error = (
            "Camera server not sending frames. "
            "Ensure camera_server.py is running on the Windows host "
            "(cd assets/camera_server && python camera_server.py --mode uvc)."
            if self._input_mode == "bridge"
            else "No frames arriving on the configured ROS image topic."
        )

        return {
            "status": "disconnected",
            "error": error,
            "suggestion": self._suggestion("camera"),
            "device_type": "camera",
            "display_name": "Camera",
            "detected": False,
            "source": "bridge" if self._input_mode == "bridge" else "ros_topic",
        }

    def _device_type(self, name: str) -> str:
        return {"robot": "robot", "camera": "camera", "hand": "gripper", "io_robot": "sensor"}.get(name, "sensor")

    def _suggestion(self, name: str) -> str:
        suggestions = {
            "robot": (
                "Verify controller power, release e-stop/protective stop, and confirm "
                "remote/external control mode is enabled with the correct robot IP in .env."
            ),
            "io_robot": (
                "Confirm the robot driver is running and publishing IO states, then check "
                "field wiring and digital pin mapping."
            ),
            "camera": (
                "Run camera_server.py on the Windows host: "
                "cd assets/camera_server && python camera_server.py --mode uvc. "
                "Verify CAMERA_INPUT_MODE=bridge and CAMERA_BRIDGE_HOST=host.docker.internal in .env."
            ),
            "hand": (
                "Verify the robot connection, check DOUT wiring for the pneumatic gripper "
                "(GRIPPER_OPEN_PIN and GRIPPER_CLOSE_PIN in .env), and ensure air supply is active."
            ),
        }
        return suggestions.get(name, "Check power and network connectivity for this device.")

    async def retry_initialization(self, device_name: str = None) -> bool:
        """Retry initialization for a specific device or all devices."""
        if device_name:
            target = "camera" if device_name.startswith("camera_usb_") else device_name
            if target in self.executors:
                logger.info("Retrying initialization for %s", target)
                await self.executors[target].initialize()
                return self.executors[target].is_ready()
            return False

        logger.info("Retrying initialization for all devices")
        for _, executor in self.executors.items():
            await executor.initialize()
        return all(e.is_ready() for e in self.executors.values())


health_service: Optional[HealthService] = None


def init_health_service(executors: dict[str, Executor]) -> HealthService:
    global health_service
    health_service = HealthService(executors)
    return health_service


def get_health_service() -> HealthService:
    if health_service is None:
        raise RuntimeError("HealthService not initialized")
    return health_service
