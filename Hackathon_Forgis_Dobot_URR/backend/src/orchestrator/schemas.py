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
    """Strict node taxonomy — 16 primitive skills + 3 meta-nodes."""

    # Meta-nodes (orchestrator infrastructure)
    INPUT_NODE = "INPUT_NODE"
    ORCHESTRATOR_PLANNER_NODE = "ORCHESTRATOR_PLANNER_NODE"
    SUMMARY_NODE = "SUMMARY_NODE"

    # Layer 1 — Perception
    CAPTURE_IMAGE = "CAPTURE_IMAGE"
    ANALYZE_SCENE = "ANALYZE_SCENE"
    ESTIMATE_GRASP_POSE = "ESTIMATE_GRASP_POSE"
    PLAN_TRAJECTORY = "PLAN_TRAJECTORY"
    DEPTH_ESTIMATION = "DEPTH_ESTIMATION"  # deprecated — kept for backward compat

    # Layer 2 — Reasoning / AI
    LLM_REASON = "LLM_REASON"
    LIVE_NARRATE = "LIVE_NARRATE"

    # Layer 3 — Motion
    MOVE_TO_POSE = "MOVE_TO_POSE"
    EXECUTE_XY_ACTION = "EXECUTE_XY_ACTION"
    MOVE_JOINTS = "MOVE_JOINTS"
    JOG_JOINTS = "JOG_JOINTS"
    GET_ROBOT_STATE = "GET_ROBOT_STATE"

    # Layer 4 — Actuation
    SUCTION_ON = "SUCTION_ON"
    SUCTION_OFF = "SUCTION_OFF"
    SET_DIGITAL_OUTPUT = "SET_DIGITAL_OUTPUT"
    WAIT_DIGITAL_INPUT = "WAIT_DIGITAL_INPUT"

    # Layer 5 — Flow Control
    WAIT = "WAIT"
    VERIFY_OUTCOME = "VERIFY_OUTCOME"

    # Compound skills
    POINT_TO_OBJECT = "POINT_TO_OBJECT"

    # Legacy aliases (for backward compatibility with existing flows)
    ER_1_5_ANALYSIS_NODE = "ER_1_5_ANALYSIS_NODE"
    DEPTH_ESTIMATION_NODE = "DEPTH_ESTIMATION_NODE"
    ROBOT_EXECUTION_NODE = "ROBOT_EXECUTION_NODE"
    GEMINI_LIVE_COMMENTARY_NODE = "GEMINI_LIVE_COMMENTARY_NODE"
    VERIFICATION_NODE = "VERIFICATION_NODE"
    JOG_JOINTS_NODE = "JOG_JOINTS_NODE"


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
    is_agentic: bool = Field(
        default=False,
        description="If True, engine uses the agentic observe-reason-act loop instead of static plan.",
    )


class MicroPlan(BaseModel):
    """Single iteration output from the agentic planner.

    Returned by plan_next_step(). Contains either one micro-task
    (a short skill sequence for one logical action) or a
    task_complete signal.
    """

    task_complete: bool = Field(
        default=False,
        description="True when the overall goal is achieved — engine exits loop.",
    )
    reasoning: str = Field(
        default="",
        description="Gemini's explanation of what it sees and why it chose this action.",
    )
    skills: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Ordered skill dicts for this micro-task: [{skill, params, description}].",
    )
    progress: dict[str, Any] = Field(
        default_factory=dict,
        description="Progress tracking: {completed, estimated_remaining, notes}.",
    )
    scene_summary: str = Field(
        default="",
        description="Short summary of the current scene state for logging.",
    )


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


# ── Skill catalog helpers ────────────────────────────────────

class SkillInfo(BaseModel):
    """Metadata for a single orchestrator skill."""

    name: str
    node_type: NodeType
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class IterativePlanStep(BaseModel):
    """A single step inside an iterative plan."""

    skill: str
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class StepReasoning(BaseModel):
    """Reasoning trace attached to a planning step."""

    thought: str = ""
    confidence: float = 1.0
    catchy_phrase: str = ""


# Pre-built indexes — populated at import time from NodeType enum.

SKILL_CATALOG: list[SkillInfo] = []

SKILL_BY_NAME: dict[str, SkillInfo] = {}

SKILL_BY_NODE_TYPE: dict[NodeType, SkillInfo] = {}

CATCHY_PHRASES: list[str] = [
    "Eyes on target",
    "Plotting the course",
    "Executing maneuver",
    "Checking results",
    "Mission accomplished",
]
