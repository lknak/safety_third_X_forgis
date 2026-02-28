import asyncio
import logging
from typing import Dict, Any, List, Optional
from executors.base import Executor
from ai_service import ai_service

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
        self._suggestions_cache: Dict[str, str] = {}

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
        """Use Gemini to get a diagnostic suggestion for a failed device."""
        if device_name in self._suggestions_cache:
            return self._suggestions_cache[device_name]
            
        prompt = f"""
        A hardware device in an industrial robot cell has failed/disconnected.
        Device: {device_name}
        Error: {error}
        
        Provide a concise (1-2 sentences) diagnostic suggestion for the operator to fix this. 
        Focus on common issues like power, emergency stops, or network connectivity.
        """
        
        try:
            suggestion = await ai_service.generate_text(prompt)
            self._suggestions_cache[device_name] = suggestion.strip()
            return self._suggestions_cache[device_name]
        except Exception as e:
            logger.error(f"Failed to generate diagnostic suggestion: {e}")
            return "Check power and network connections. Ensure the device is properly initialized in ROS 2."

    async def retry_initialization(self, device_name: str = None) -> bool:
        """Retry initialization for a specific device or all devices."""
        if device_name:
            if device_name in self.executors:
                logger.info(f"Retrying initialization for {device_name}")
                await self.executors[device_name].initialize()
                # Clear cache on retry
                if device_name in self._suggestions_cache:
                    del self._suggestions_cache[device_name]
                return self.executors[device_name].is_ready()
            return False
        else:
            logger.info("Retrying initialization for all devices")
            for name, executor in self.executors.items():
                await executor.initialize()
            self._suggestions_cache.clear()
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
