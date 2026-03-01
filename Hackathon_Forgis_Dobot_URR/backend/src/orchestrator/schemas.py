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


# ── Iterative skill-aware planner schemas ─────────────────────


class SkillInfo(BaseModel):
    """Description of an available orchestrator skill (node type)."""

    name: str
    node_type: NodeType
    description: str
    phase: str = ""  # e.g. "perception", "planning", "execution", "verification"


class StepReasoning(BaseModel):
    """Planner reasoning for a single step decision."""

    thought: str  # Why this skill was chosen (Claude-style thinking)
    chosen_skill: str  # Skill name from catalog
    goal_index: int = 0  # Which subgoal this serves
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    context_note: str = ""  # Optional context for the UI


class IterativePlanStep(BaseModel):
    """Result of a single iterative planning step."""

    reasoning: StepReasoning
    node: Optional[NodePlan] = None
    is_complete: bool = False
    catchy_phrase: str = ""  # Personality phrase for the UI


# ── Skill catalog ────────────────────────────────────────────

SKILL_CATALOG: list[SkillInfo] = [
    SkillInfo(
        name="capture_cell_state",
        node_type=NodeType.INPUT_NODE,
        description="Snapshot the current cell state – device readiness, sensor feeds, workspace layout",
        phase="perception",
    ),
    SkillInfo(
        name="decompose_task",
        node_type=NodeType.ORCHESTRATOR_PLANNER_NODE,
        description="Break the natural-language instruction into ordered subgoals with object, source, and target",
        phase="planning",
    ),
    SkillInfo(
        name="analyze_scene",
        node_type=NodeType.ER_1_5_ANALYSIS_NODE,
        description="Use Gemini Robotics ER vision to locate objects, assess feasibility, and compute waypoints",
        phase="perception",
    ),
    SkillInfo(
        name="estimate_depth",
        node_type=NodeType.DEPTH_ESTIMATION_NODE,
        description="Look up safe Z-heights and convert normalised vision coordinates into robot-frame poses",
        phase="planning",
    ),
    SkillInfo(
        name="move_robot",
        node_type=NodeType.ROBOT_EXECUTION_NODE,
        description="Send linear or joint motion commands to the robot arm",
        phase="execution",
    ),
    SkillInfo(
        name="narrate_live",
        node_type=NodeType.GEMINI_LIVE_COMMENTARY_NODE,
        description="Generate real-time audio commentary while the robot is moving",
        phase="execution",
    ),
    SkillInfo(
        name="verify_motion",
        node_type=NodeType.VERIFICATION_NODE,
        description="Confirm the robot completed its motion correctly by checking telemetry",
        phase="verification",
    ),
    SkillInfo(
        name="jog_joints",
        node_type=NodeType.JOG_JOINTS_NODE,
        description="Move specific robot joints by a relative degree offset",
        phase="execution",
    ),
    SkillInfo(
        name="summarize",
        node_type=NodeType.SUMMARY_NODE,
        description="Aggregate all step outcomes into a final execution report",
        phase="summary",
    ),
]

SKILL_BY_NAME: dict[str, SkillInfo] = {s.name: s for s in SKILL_CATALOG}
SKILL_BY_NODE_TYPE: dict[NodeType, SkillInfo] = {s.node_type: s for s in SKILL_CATALOG}


# ── Catchy phrases (Claude-style personality) ─────────────────

CATCHY_PHRASES: dict[str, list[str]] = {
    "capture_cell_state": [
        "Scanning the factory floor...",
        "Taking a look around the cell...",
        "Checking what we're working with...",
    ],
    "decompose_task": [
        "Breaking this down into steps...",
        "Let me think about how to approach this...",
        "Mapping out the game plan...",
    ],
    "analyze_scene": [
        "Eyes on the workspace...",
        "Looking for the target object...",
        "Getting a read on the scene...",
    ],
    "estimate_depth": [
        "Crunching the numbers for safe heights...",
        "Calculating approach vectors...",
        "Dialing in the coordinates...",
    ],
    "move_robot": [
        "Sending it! Robot in motion...",
        "Executing the move...",
        "Here we go — arm is moving...",
    ],
    "narrate_live": [
        "Narrating the action live...",
        "Commentating in real time...",
        "Play-by-play coming right up...",
    ],
    "verify_motion": [
        "Did we nail it? Checking...",
        "Verifying the motion result...",
        "Making sure everything landed right...",
    ],
    "jog_joints": [
        "Nudging the joints...",
        "Fine-tuning joint positions...",
        "Tweaking the arm angles...",
    ],
    "summarize": [
        "Wrapping it up...",
        "Here's how it all went down...",
        "Let me put a bow on this one...",
    ],
    "done": [
        "All done! Mission accomplished.",
        "That's a wrap — task complete.",
        "Nailed it. Everything checks out.",
    ],
}
