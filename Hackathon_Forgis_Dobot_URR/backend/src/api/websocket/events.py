"""WebSocket event type definitions."""

import time
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """WebSocket event types."""

    # Flow lifecycle events
    FLOW_STARTED = "flow_started"
    FLOW_COMPLETED = "flow_completed"
    FLOW_PAUSED = "flow_paused"
    FLOW_RESUMED = "flow_resumed"
    FLOW_ABORTED = "flow_aborted"
    FLOW_ERROR = "flow_error"

    # State events
    STATE_ENTERED = "state_entered"
    STATE_COMPLETED = "state_completed"
    WAITING_CONDITION = "waiting_condition"

    # Step events
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_ERROR = "step_error"
    STEP_RETRY = "step_retry"
    STEP_SKIPPED = "step_skipped"

    # Telemetry events
    ROBOT_STATE = "robot_state"

    # Camera events
    CAMERA_FRAME = "camera_frame"

    # Connection events
    CONNECTED = "connected"
    PING = "ping"
    PONG = "pong"

    # Orchestrator supervisor events
    ORCHESTRATOR_STATE_TRANSITION = "orchestrator_state_transition"
    ORCHESTRATOR_TASK_QUEUED = "orchestrator_task_queued"
    ORCHESTRATOR_RUN_COMPLETED = "orchestrator_run_completed"
    ORCHESTRATOR_REPLANNED = "orchestrator_replanned"
    ORCHESTRATOR_GOAL_CHANGE_REQUESTED = "orchestrator_goal_change_requested"
    ORCHESTRATOR_GOAL_CHANGE_APPLIED = "orchestrator_goal_change_applied"

    # Orchestrator node events
    ORCHESTRATOR_NODE_STARTED = "orchestrator_node_started"
    ORCHESTRATOR_NODE_FINISHED = "orchestrator_node_finished"
    ORCHESTRATOR_TILE_FOCUS = "orchestrator_tile_focus"

    # Clarification events
    ORCHESTRATOR_CLARIFICATION_REQUESTED = "orchestrator_clarification_requested"
    ORCHESTRATOR_CLARIFICATION_RESOLVED = "orchestrator_clarification_resolved"
    ORCHESTRATOR_CLARIFICATION_TIMEOUT = "orchestrator_clarification_timeout"
    ORCHESTRATOR_AGENTIC_MICRO_PLAN = "orchestrator_agentic_micro_plan"

    # Live commentary events
    ORCHESTRATOR_LIVE_CHUNK = "orchestrator_live_chunk"


def create_event(event_type: str | EventType, data: dict[str, Any]) -> dict[str, Any]:
    """
    Create a WebSocket event payload.

    Args:
        event_type: Type of event.
        data: Event-specific data.

    Returns:
        Complete event dict ready for JSON serialization.
    """
    if isinstance(event_type, EventType):
        event_type = event_type.value

    return {
        "type": event_type,
        "timestamp": time.time(),
        **data,
    }
