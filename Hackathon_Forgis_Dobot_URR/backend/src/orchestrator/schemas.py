"""Schemas for the always-on orchestrator subsystem."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class OrchestratorState(str, Enum):
    """Supervisor lifecycle states."""

    BOOT = "BOOT"
    CELL_CHECK = "CELL_CHECK"
    READY = "READY"
    EXECUTING = "EXECUTING"
    ERROR = "ERROR"
    RECOVERY = "RECOVERY"


class NodeType(str, Enum):
    """Strict node taxonomy required by the orchestrator contract."""

    INPUT_NODE = "INPUT_NODE"
    ORCHESTRATOR_PLANNER_NODE = "ORCHESTRATOR_PLANNER_NODE"
    ER_1_5_ANALYSIS_NODE = "ER_1_5_ANALYSIS_NODE"
    DEPTH_ESTIMATION_NODE = "DEPTH_ESTIMATION_NODE"
    ROBOT_EXECUTION_NODE = "ROBOT_EXECUTION_NODE"
    GEMINI_LIVE_COMMENTARY_NODE = "GEMINI_LIVE_COMMENTARY_NODE"
    VERIFICATION_NODE = "VERIFICATION_NODE"
    SUMMARY_NODE = "SUMMARY_NODE"


class NodeResultStatus(str, Enum):
    """Finite node terminal statuses."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"


class TransitionRecord(BaseModel):
    """State transition telemetry."""

    from_state: OrchestratorState
    to_state: OrchestratorState
    timestamp: float = Field(default_factory=time.time)
    reason: str = ""


class FlowRunNodeRecord(BaseModel):
    """Execution record for a single node."""

    name: str
    type: NodeType
    status: NodeResultStatus
    start_time: float
    end_time: float
    artifacts: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = 30000


class FlowRunRecord(BaseModel):
    """Persisted run record (required external JSON shape + metadata)."""

    flow_id: str
    state_transitions: list[TransitionRecord] = Field(default_factory=list)
    nodes: list[FlowRunNodeRecord] = Field(default_factory=list)
    final_status: Literal["SUCCESS", "FAILURE", "TIMEOUT", "ABORTED", "PARTIAL"] = "PARTIAL"
    instruction: str = ""
    started_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
    error_message: Optional[str] = None


class ClarificationAction(str, Enum):
    """Operator decision actions."""

    RETRY = "retry"
    REPLAN = "replan"
    MODIFY_GOAL = "modify_goal"
    SAFE_STOP = "safe_stop"


class ClarificationRequest(BaseModel):
    """Clarification request emitted when infeasible/failure conditions occur."""

    flow_id: str
    node_name: str
    reason: str
    created_at: float = Field(default_factory=time.time)
    timeout_seconds: int = 45
    choices: list[ClarificationAction] = Field(
        default_factory=lambda: [
            ClarificationAction.RETRY,
            ClarificationAction.REPLAN,
            ClarificationAction.MODIFY_GOAL,
            ClarificationAction.SAFE_STOP,
        ]
    )


class ClarificationDecision(BaseModel):
    """Operator response payload."""

    action: ClarificationAction
    note: Optional[str] = None


class OrchestratorTask(BaseModel):
    """Queued task envelope."""

    task_id: str
    flow_id: str
    instruction: str
    created_at: float = Field(default_factory=time.time)


class NodePlan(BaseModel):
    """Planner-produced node descriptor."""

    name: str
    type: NodeType
    timeout_ms: int = Field(default=30000, ge=100, le=600000)
    payload: dict[str, Any] = Field(default_factory=dict)


class PlanResult(BaseModel):
    """Planner output with assumptions/subgoals and executable nodes."""

    subgoals: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    nodes: list[NodePlan] = Field(default_factory=list)


class EngineStateSnapshot(BaseModel):
    """Runtime status response."""

    state: OrchestratorState
    queue_depth: int
    queue_limit: int
    active_flow_id: Optional[str] = None
    last_error: Optional[str] = None


class GoalChangeRequest(BaseModel):
    """Request to modify goal during execution."""

    goal: str = Field(..., min_length=1)
