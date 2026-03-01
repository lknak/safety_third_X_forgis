"""API routes for flow execution system."""

from .flows import router as flows_router
from .skills import router as skills_router
from .camera import router as camera_router
from .config import router as config_router
from .health import router as health_router
from .robot import router as robot_router
from .orchestrator import router as orchestrator_router

try:
    from .cell import router as cell_router
except Exception:
    cell_router = None

__all__ = [
    "flows_router",
    "skills_router",
    "camera_router",
    "config_router",
    "health_router",
    "cell_router",
    "robot_router",
    "orchestrator_router",
]
