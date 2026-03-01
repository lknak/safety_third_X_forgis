"""FastAPI application factory."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .routes import (
    flows_router,
    skills_router,
    camera_router,
    config_router,
    health_router,
    cell_router,
    robot_router,
    orchestrator_router,
)
from .routes.flows import set_flow_manager
from .routes.camera import set_camera_executor
from .routes.robot import set_robot_control_dependencies
from .routes.orchestrator import set_orchestrator_engine
from .websocket import WebSocketManager

if TYPE_CHECKING:
    from executors.camera_executor import CameraExecutor
    from executors.hand_executor import HandExecutor
    from executors.io_executor import IOExecutor
    from executors.base import Executor
    from flow.manager import FlowManager
    from orchestrator.engine import OrchestratorEngine
    from nodes.ur_node import RobotNode

logger = logging.getLogger(__name__)


def create_app(
    flow_manager: "FlowManager",
    ws_manager: WebSocketManager,
    orchestrator_engine: "OrchestratorEngine",
    robot_node: "RobotNode",
    robot_executor: "Executor",
    camera_executor: "CameraExecutor" = None,
    io_robot_executor: "IOExecutor" = None,
    hand_executor: "HandExecutor" = None,
    physical_ai_executor=None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        flow_manager: FlowManager instance for flow operations.
        ws_manager: WebSocketManager instance for real-time events.
        robot_node: RobotNode for robot state queries.
        camera_executor: CameraExecutor for camera operations (optional).

    Returns:
        Configured FastAPI application.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan context manager."""
        logger.info("FastAPI application starting")
        # Inject flow manager into routes
        set_flow_manager(flow_manager)
        set_orchestrator_engine(orchestrator_engine)
        # Inject camera executor if available
        if camera_executor:
            set_camera_executor(camera_executor)
        set_robot_control_dependencies(flow_manager, robot_executor, io_robot_executor)

        # Initialize executors in the background (runs on uvicorn's event loop)
        async def _init_executors():
            await asyncio.sleep(1)  # Small delay to let API start
            try:
                await robot_executor.initialize()
                if io_robot_executor is not None:
                    await io_robot_executor.initialize()
                if camera_executor:
                    await camera_executor.initialize()
                if hand_executor:
                    await hand_executor.initialize()
                logger.info("All executors initialized")
            except Exception as e:
                logger.error(f"Executor initialization failed: {e}")

        init_task = asyncio.create_task(_init_executors())
        await orchestrator_engine.start()
        yield
        await orchestrator_engine.stop()
        init_task.cancel()
        logger.info("FastAPI application shutting down")

    app = FastAPI(
        title="Flow Execution System",
        description="REST API and WebSocket for industrial robot automation flows",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(flows_router)
    app.include_router(skills_router)
    app.include_router(camera_router)
    app.include_router(config_router)
    app.include_router(health_router)
    if cell_router is not None:
        app.include_router(cell_router)
    app.include_router(robot_router)
    app.include_router(orchestrator_router)

    # WebSocket endpoint
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time flow telemetry."""
        await ws_manager.connect(websocket)

        # Reset conveyor IO on frontend connect to prevent stale trigger
        if io_robot_executor and io_robot_executor.is_ready():
            try:
                await io_robot_executor.set_digital_output(4, False)
                logger.info("Reset conveyor DO[4] to False on client connect")
            except Exception as e:
                logger.warning(f"Failed to reset DO[4] on connect: {e}")

        try:
            while True:
                # Wait for messages (ping/pong or custom commands)
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text('{"type":"pong"}')
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning(f"WebSocket error: {e}")
        finally:
            await ws_manager.disconnect(websocket)

    # Custom robot state endpoint
    @app.get("/api/robot/state")
    async def get_robot_state():
        """Get current robot state."""
        return robot_node.get_state_summary()

    # Hand state endpoint
    @app.get("/api/hand/state")
    async def get_hand_state():
        """Get current COVVI hand state."""
        if not hand_executor or not hand_executor.is_ready():
            return {"connected": False, "fingers": None}
        return {"connected": True, "fingers": hand_executor.get_hand_state()}

    return app
