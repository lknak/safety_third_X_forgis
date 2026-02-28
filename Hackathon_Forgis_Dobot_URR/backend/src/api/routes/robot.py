"""Direct robot control endpoints for manual operations."""

import logging
import math
from typing import Optional, TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from flow.manager import FlowManager
    from executors.base import Executor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/robot", tags=["robot"])

_flow_manager: Optional["FlowManager"] = None
_robot_executor: Optional["Executor"] = None
_io_robot_executor: Optional["Executor"] = None


def set_robot_control_dependencies(
    flow_manager: "FlowManager",
    robot_executor: "Executor",
    io_robot_executor: Optional["Executor"],
) -> None:
    """Inject dependencies used by direct robot control routes."""
    global _flow_manager, _robot_executor, _io_robot_executor
    _flow_manager = flow_manager
    _robot_executor = robot_executor
    _io_robot_executor = io_robot_executor


def _ensure_flow_manager():
    if _flow_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Flow manager not initialized",
        )
    return _flow_manager


def _ensure_robot_executor():
    if _robot_executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Robot executor not initialized",
        )
    return _robot_executor


def _ensure_no_flow_running() -> None:
    manager = _ensure_flow_manager()
    if manager.is_running():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A flow is currently running. Abort or finish it before manual robot control.",
        )


class MoveJointRequest(BaseModel):
    target_joints_deg: list[float] = Field(..., min_length=6, max_length=6)
    acceleration: float = Field(default=1.2, ge=0.1, le=2.0)
    velocity: float = Field(default=1.0, ge=0.1, le=2.0)
    tolerance_deg: float = Field(default=1.0, ge=0.1, le=10.0)
    timeout_ms: int = Field(default=45000, ge=1000, le=180000)


class MoveLinearRequest(BaseModel):
    pose: list[float] = Field(..., min_length=6, max_length=6,
                              description="Target pose [x,y,z,rx,ry,rz] in meters and radians")
    acceleration: float = Field(default=1.2, ge=0.01, le=3.0)
    velocity: float = Field(default=0.25, ge=0.01, le=1.0)
    timeout_ms: int = Field(default=45000, ge=1000, le=180000)


class SetDigitalOutputRequest(BaseModel):
    pin: int = Field(..., ge=0, le=7)
    value: bool


class RobotCommandResponse(BaseModel):
    success: bool
    message: str


@router.post("/jog-joint", response_model=RobotCommandResponse)
async def jog_joint(request: MoveJointRequest):
    """Jog to target via secondary script — does NOT interrupt External Control."""
    _ensure_no_flow_running()
    executor = _ensure_robot_executor()

    if not executor.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Robot is offline.",
        )

    target_rad = [math.radians(deg) for deg in request.target_joints_deg]
    success = await executor.jog_joint(
        target_rad=target_rad,
        acceleration=request.acceleration,
        velocity=request.velocity,
        tolerance_rad=math.radians(request.tolerance_deg),
        timeout=request.timeout_ms / 1000.0,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Jog did not reach target before timeout.",
        )

    return RobotCommandResponse(success=True, message="Jog completed")


@router.post("/move-joint", response_model=RobotCommandResponse)
async def move_joint(request: MoveJointRequest):
    """Execute a direct MoveJ command without creating a temporary flow."""
    _ensure_no_flow_running()
    executor = _ensure_robot_executor()

    if not executor.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Robot is offline. Wait for '/api/robot/state' to report connected=true and retry.",
        )

    target_rad = [math.radians(deg) for deg in request.target_joints_deg]
    success = await executor.move_joint(
        target_rad=target_rad,
        acceleration=request.acceleration,
        velocity=request.velocity,
        tolerance_rad=math.radians(request.tolerance_deg),
        timeout=request.timeout_ms / 1000.0,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "MoveJ did not complete before timeout. Check remote/external control mode, "
                "protective stop status, and that the External Control program is running."
            ),
        )

    return RobotCommandResponse(success=True, message="MoveJ completed")


@router.post("/move-linear", response_model=RobotCommandResponse)
async def move_linear(request: MoveLinearRequest):
    """Execute a direct MoveL (linear Cartesian) command."""
    _ensure_no_flow_running()
    executor = _ensure_robot_executor()

    if not executor.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Robot is offline. Wait for '/api/robot/state' to report connected=true and retry.",
        )

    success = await executor.move_linear(
        pose=request.pose,
        acceleration=request.acceleration,
        velocity=request.velocity,
        timeout=request.timeout_ms / 1000.0,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "MoveL did not complete before timeout. Check remote/external control mode, "
                "protective stop status, and that the External Control program is running."
            ),
        )

    return RobotCommandResponse(success=True, message="MoveL completed")


@router.post("/set-digital-output", response_model=RobotCommandResponse)
async def set_digital_output(request: SetDigitalOutputRequest):
    """Set robot digital output via direct I/O executor call."""
    _ensure_no_flow_running()
    _ensure_robot_executor()

    if _io_robot_executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Digital I/O executor is unavailable for the current robot type/configuration.",
        )
    if not _io_robot_executor.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Digital I/O executor is offline.",
        )

    await _io_robot_executor.set_digital_output(request.pin, request.value)
    return RobotCommandResponse(success=True, message=f"DO[{request.pin}] set to {request.value}")
