import asyncio
import logging
from typing import Dict, Any, List, Optional
from executors.base import Executor

logger = logging.getLogger(__name__)

class DeviceHealth:
    def __init__(self, device_id: str, status: str, error: Optional[str] = None, suggestion: Optional[str] = None):
        self.device_id = device_id
        self.status = status # "connected", "warning", "disconnected"
        self.error = error
        self.suggestion = suggestion

class HealthService:
    """
    Manages the health and diagnostics of all hardware devices/executors.
    """
    def __init__(self, executors: Dict[str, Executor]):
        self.executors = executors

    async def get_overall_health(self) -> Dict[str, Any]:
        """Get the health status of all devices."""
        health_data = {}
        all_ready = True
        
        for name, executor in self.executors.items():
            is_ready = executor.is_ready()
            if not is_ready:
                all_ready = False
                
            status = "connected" if is_ready else "disconnected"
            # Simple error heuristic for now
            error = None if is_ready else f"{name.capitalize()} executor is not responding or joint data is missing."
            
            suggestion = None
            if not is_ready:
                suggestion = await self._get_suggestion(name, error)
            
            health_data[name] = {
                "status": status,
                "error": error,
                "suggestion": suggestion
            }
            
        return {
            "overall_status": "healthy" if all_ready else "degraded",
            "devices": health_data
        }

    async def _get_suggestion(self, device_name: str, error: str) -> str:
        """Return deterministic troubleshooting guidance (AI diagnostics disabled)."""
        normalized = device_name.lower()

        if normalized == "robot":
            return (
                "Verify controller power, release e-stop/protective stop, and confirm remote/external control mode "
                "is enabled with the correct robot IP in .env."
            )
        if normalized == "io_robot":
            return (
                "Confirm the robot driver is running and publishing IO states, then check field wiring and digital "
                "pin mapping for this cell."
            )
        if normalized == "camera":
            return (
                "Check the USB camera connection and verify the configured ROS image topic (CAMERA_IMAGE_TOPIC, "
                "default /image_raw) is publishing frames. If using bridge mode, verify CAMERA_INPUT_MODE=bridge "
                "and camera bridge endpoint availability."
            )
        if normalized == "hand":
            return (
                "Verify hand power and IP connectivity, then retry initialization. Confirm the hand driver can read "
                "and command finger state."
            )

        return "Check power and network connectivity for this device, then retry initialization."

    async def retry_initialization(self, device_name: str = None) -> bool:
        """Retry initialization for a specific device or all devices."""
        if device_name:
            if device_name in self.executors:
                logger.info(f"Retrying initialization for {device_name}")
                await self.executors[device_name].initialize()
                return self.executors[device_name].is_ready()
            return False
        else:
            logger.info("Retrying initialization for all devices")
            for name, executor in self.executors.items():
                await executor.initialize()
            return all(e.is_ready() for e in self.executors.values())

health_service: Optional[HealthService] = None

def init_health_service(executors: Dict[str, Executor]) -> HealthService:
    global health_service
    health_service = HealthService(executors)
    return health_service

def get_health_service() -> HealthService:
    if health_service is None:
        raise RuntimeError("HealthService not initialized")
    return health_service
