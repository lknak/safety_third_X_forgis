"""REST endpoints for always-on orchestrator tasking and run history."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from orchestrator import ClarificationDecision, GoalChangeRequest
from orchestrator.engine import OrchestratorEngine
from orchestrator.schemas import PlanResult

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])

_engine: Optional[OrchestratorEngine] = None


def set_orchestrator_engine(engine: OrchestratorEngine) -> None:
    """Inject orchestrator engine from app initialization."""
    global _engine
    _engine = engine


def _get_engine() -> OrchestratorEngine:
    if _engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator engine not initialized",
        )
    return _engine


class OrchestratorTaskRequest(BaseModel):
    instruction: str = Field(..., min_length=1)


class PreviewFlowStep(BaseModel):
    id: str
    skill: str
    executor: str
    params: dict[str, Any] = Field(default_factory=dict)


class PreviewFlowNode(BaseModel):
    id: str
    type: str
    label: str
    steps: list[PreviewFlowStep] = Field(default_factory=list)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class PreviewFlowEdge(BaseModel):
    id: str
    source: str
    target: str


class PreviewFlow(BaseModel):
    id: str
    name: str
    loop: bool = False
    nodes: list[PreviewFlowNode]
    edges: list[PreviewFlowEdge]


class PlannerPreviewStep(BaseModel):
    skill: str
    description: str = ""


class PlannerPreview(BaseModel):
    is_agentic: bool = False
    reasoning: str = ""
    steps: list[PlannerPreviewStep] = Field(default_factory=list)


class OrchestratorTaskResponse(BaseModel):
    mode: str = "orchestrator"
    accepted: bool
    message: str
    task_id: Optional[str] = None
    flow_id: Optional[str] = None
    queue_depth: Optional[int] = None
    plan: Optional[PlannerPreview] = None
    preview_flow: Optional[PreviewFlow] = None


class OrchestratorQueueItem(BaseModel):
    task_id: str
    flow_id: str
    instruction: str
    created_at: float


class OrchestratorQueueResponse(BaseModel):
    items: list[OrchestratorQueueItem]


class OrchestratorRunsResponse(BaseModel):
    runs: list[dict[str, Any]]


class DecisionResponse(BaseModel):
    success: bool
    message: str


def _plan_preview_to_flow(flow_id: str, instruction: str, plan: PlanResult) -> PreviewFlow:
    nodes: list[PreviewFlowNode] = [
        PreviewFlowNode(id="start", type="start", label="Start", steps=[]),
    ]

    for idx, node in enumerate(plan.nodes, start=1):
        nodes.append(
            PreviewFlowNode(
                id=node.name,
                type="state",
                label=node.type.value,
                steps=[
                    PreviewFlowStep(
                        id=f"preview_{idx}",
                        skill=node.type.value,
                        executor="orchestrator",
                        params=node.payload,
                    )
                ],
            )
        )

    nodes.append(PreviewFlowNode(id="end", type="end", label="End", steps=[]))

    edges: list[PreviewFlowEdge] = []
    if len(nodes) >= 2:
        edges.append(PreviewFlowEdge(id="e_start", source="start", target=nodes[1].id))

    for i in range(1, len(nodes) - 2):
        edges.append(
            PreviewFlowEdge(
                id=f"e_{nodes[i].id}_{nodes[i + 1].id}",
                source=nodes[i].id,
                target=nodes[i + 1].id,
            )
        )

    if len(nodes) >= 2:
        edges.append(
            PreviewFlowEdge(
                id=f"e_{nodes[-2].id}_end",
                source=nodes[-2].id,
                target="end",
            )
        )

    return PreviewFlow(
        id=flow_id,
        name=f"Orchestrator Preview: {instruction[:40]}",
        loop=False,
        nodes=nodes,
        edges=edges,
    )


def _plan_result_preview(plan: PlanResult) -> PlannerPreview:
    steps: list[PlannerPreviewStep] = []
    for node in plan.nodes:
        payload = node.payload if isinstance(node.payload, dict) else {}
        params = payload.get("params", {})
        if not isinstance(params, dict):
            params = {}
        skill = str(payload.get("skill_name") or node.name)
        description = str(payload.get("description") or "")
        if node.type.value == "SUMMARY_NODE":
            continue
        steps.append(PlannerPreviewStep(skill=skill, description=description))

    reasoning = "; ".join(plan.assumptions) if plan.assumptions else ""
    return PlannerPreview(
        is_agentic=plan.is_agentic,
        reasoning=reasoning,
        steps=steps,
    )


@router.post("/tasks", response_model=OrchestratorTaskResponse)
async def create_task(request: OrchestratorTaskRequest):
    """Queue a new orchestrator task from natural language input."""
    engine = _get_engine()
    instruction = request.instruction.strip()

    if hasattr(engine, "should_orchestrate_task"):
        actionable = await engine.should_orchestrate_task(instruction)  # type: ignore[attr-defined]
    else:
        actionable = engine.is_actionable_task(instruction)

    if not actionable:
        queue_depth = (await engine.get_state_snapshot()).queue_depth
        reply = await engine.build_cell_manager_reply(instruction)
        return OrchestratorTaskResponse(
            mode="cell_manager",
            accepted=False,
            message=reply,
            queue_depth=queue_depth,
        )

    try:
        accepted, message, task, preview = await engine.enqueue_task(instruction)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    queue_depth = (await engine.get_state_snapshot()).queue_depth
    preview_flow_id = task.flow_id if task else f"preview_{instruction[:24].strip().replace(' ', '_')}"
    flow_preview = _plan_preview_to_flow(preview_flow_id, instruction, preview) if preview else None
    plan_preview = _plan_result_preview(preview) if preview else None

    if not accepted:
        return OrchestratorTaskResponse(
            mode="orchestrator",
            accepted=False,
            message=message,
            queue_depth=queue_depth,
            plan=plan_preview,
            preview_flow=flow_preview,
        )

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Task accepted but no task metadata returned",
        )

    return OrchestratorTaskResponse(
        mode="orchestrator",
        accepted=True,
        message=message,
        task_id=task.task_id,
        flow_id=task.flow_id,
        queue_depth=queue_depth,
        plan=plan_preview,
        preview_flow=flow_preview,
    )


@router.get("/state")
async def get_state():
    """Get orchestrator supervisor state and queue stats."""
    engine = _get_engine()
    return await engine.get_state_snapshot()


@router.get("/queue", response_model=OrchestratorQueueResponse)
async def get_queue():
    """List queued tasks."""
    engine = _get_engine()
    items = await engine.list_queue()
    return OrchestratorQueueResponse(items=[OrchestratorQueueItem(**item.model_dump()) for item in items])


@router.get("/runs", response_model=OrchestratorRunsResponse)
async def list_runs(limit: int = 20, offset: int = 0):
    """List persisted run history."""
    engine = _get_engine()
    runs = engine.list_runs(limit=limit, offset=offset)
    return OrchestratorRunsResponse(runs=[run.model_dump() for run in runs])


@router.get("/runs/{flow_id}")
async def get_run(flow_id: str):
    """Get full run record by flow id."""
    engine = _get_engine()
    run = engine.get_run(flow_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{flow_id}' not found")
    return run


@router.post("/runs/{flow_id}/decision", response_model=DecisionResponse)
async def post_decision(flow_id: str, decision: ClarificationDecision):
    """Submit operator clarification response for active flow."""
    engine = _get_engine()
    success, message = await engine.submit_decision(flow_id, decision)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return DecisionResponse(success=success, message=message)


@router.post("/runs/{flow_id}/goal", response_model=DecisionResponse)
async def update_goal(flow_id: str, request: GoalChangeRequest):
    """Request mid-run goal update and downstream replan."""
    engine = _get_engine()
    success, message = await engine.request_goal_change(flow_id, request.goal)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return DecisionResponse(success=success, message=message)
