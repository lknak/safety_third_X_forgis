"""REST endpoints for flow management."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from flow import FlowSchema, FlowStatusResponse
from ai_service import ai_service
import json
import uuid

router = APIRouter(prefix="/api/flows", tags=["flows"])

# FlowManager will be injected via app state
_flow_manager = None


def set_flow_manager(manager) -> None:
    """Set the flow manager instance (called during app initialization)."""
    global _flow_manager
    _flow_manager = manager


def get_manager():
    """Get the flow manager, raising if not initialized."""
    if _flow_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Flow manager not initialized",
        )
    return _flow_manager


# --- Request/Response Models ---


class FlowListResponse(BaseModel):
    """Response for listing flows."""

    flows: list[str]


class FlowCreateResponse(BaseModel):
    """Response for creating/updating a flow."""

    success: bool
    message: str
    flow_id: Optional[str] = None


class FlowStartResponse(BaseModel):
    """Response for starting a flow."""

    success: bool
    message: str


class FlowAbortResponse(BaseModel):
    """Response for aborting a flow."""

    success: bool
    message: str


class FlowGenerateRequest(BaseModel):
    """Request for generating a flow from prompt."""

    prompt: str


class FlowStep(BaseModel):
    """Step within a state (aligned with backend naming)."""

    id: str
    skill: str
    executor: str
    params: Optional[dict[str, Any]] = None


class FlowNode(BaseModel):
    """Node in the frontend flow format (aligned with backend naming)."""

    id: str
    type: str  # "state", "start", "end"
    label: str
    steps: Optional[list[FlowStep]] = None  # For state nodes
    position: dict[str, float]
    style: Optional[dict[str, Any]] = None  # For sizing


class FlowEdge(BaseModel):
    """Edge in the frontend flow format."""

    id: str
    source: str
    target: str
    type: str = "transitionEdge"
    data: Optional[dict[str, Any]] = None


class FlowGenerateResponse(BaseModel):
    """Response with frontend-compatible flow format."""

    id: str
    name: str
    loop: bool = False
    nodes: list[FlowNode]
    edges: list[FlowEdge]


def convert_backend_to_frontend(flow: FlowSchema) -> FlowGenerateResponse:
    """
    Convert backend flow format to frontend node/edge format.

    Backend: states with steps, transitions between states
    Frontend: start node, state nodes (containing steps), end node, edges

    Uses actual transitions from the flow definition.
    """
    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []

    # Positions are set to (0,0) — the frontend's layoutFlow() computes real positions.

    # Add start node
    start_node_id = "start"
    nodes.append(FlowNode(
        id=start_node_id,
        type="start",
        label="Start",
        position={"x": 0, "y": 0},
    ))

    # Convert each state to a node with steps inside
    for state in flow.states:
        node_id = state.name

        steps = [
            FlowStep(
                id=step.id,
                skill=step.skill,
                executor=step.executor,
                params=step.params,
            )
            for step in state.steps
        ]

        nodes.append(FlowNode(
            id=node_id,
            type="state",
            label=state.name,
            steps=steps,
            position={"x": 0, "y": 0},
        ))

    # Add end node
    end_node_id = "end"
    nodes.append(FlowNode(
        id=end_node_id,
        type="end",
        label="End",
        position={"x": 0, "y": 0},
    ))

    # Edge from start to initial state
    edges.append(FlowEdge(
        id=f"e_{start_node_id}_{flow.initial_state}",
        source=start_node_id,
        target=flow.initial_state,
    ))

    # Convert actual transitions to edges
    for i, t in enumerate(flow.transitions):
        edge_data: dict[str, Any] = {"transitionType": t.type}
        if t.condition:
            edge_data["condition"] = t.condition

        edges.append(FlowEdge(
            id=f"e_{t.from_state}_{t.to_state}_{i}",
            source=t.from_state,
            target=t.to_state,
            data=edge_data,
        ))

    # Find terminal states (no outgoing transitions)
    states_with_outgoing = {t.from_state for t in flow.transitions}
    terminal_states = [s.name for s in flow.states if s.name not in states_with_outgoing]

    # Add loop-back and/or end edges for terminal states
    for state_name in terminal_states:
        if flow.loop:
            edges.append(FlowEdge(
                id=f"e_loop_{state_name}_{flow.initial_state}",
                source=state_name,
                target=flow.initial_state,
                data={"isLoop": True},
            ))
        edges.append(FlowEdge(
            id=f"e_{state_name}_{end_node_id}",
            source=state_name,
            target=end_node_id,
        ))

    return FlowGenerateResponse(
        id=flow.id,
        name=flow.name,
        loop=flow.loop,
        nodes=nodes,
        edges=edges,
    )


# --- Endpoints ---


@router.get("", response_model=FlowListResponse)
async def list_flows():
    """List all available flows."""
    manager = get_manager()
    return FlowListResponse(flows=manager.list_flows())


@router.get("/status", response_model=FlowStatusResponse)
async def get_status():
    """Get current execution status."""
    manager = get_manager()
    return manager.get_status()


@router.get("/{flow_id}", response_model=FlowSchema)
async def get_flow(flow_id: str):
    """Get a flow definition by ID."""
    manager = get_manager()
    flow = manager.get_flow(flow_id)
    if flow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Flow '{flow_id}' not found",
        )
    return flow


@router.post("", response_model=FlowCreateResponse)
async def create_flow(flow: FlowSchema):
    """Create or update a flow."""
    manager = get_manager()
    success, error = manager.save_flow(flow)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "Failed to save flow",
        )
    return FlowCreateResponse(
        success=True,
        message=f"Flow '{flow.id}' saved",
        flow_id=flow.id,
    )


@router.delete("/{flow_id}")
async def delete_flow(flow_id: str):
    """Delete a flow."""
    manager = get_manager()
    if not manager.delete_flow(flow_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Flow '{flow_id}' not found",
        )
    return {"success": True, "message": f"Flow '{flow_id}' deleted"}


@router.post("/{flow_id}/start", response_model=FlowStartResponse)
async def start_flow(flow_id: str):
    """Start executing a flow."""
    manager = get_manager()
    success, message = await manager.start_flow(flow_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT
            if "already running" in message.lower()
            else status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    return FlowStartResponse(success=True, message=message)


@router.post("/abort", response_model=FlowAbortResponse)
async def abort_flow():
    """Abort the currently running flow."""
    manager = get_manager()
    success, message = await manager.abort_flow()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    return FlowAbortResponse(success=True, message=message)


class FlowFinishResponse(BaseModel):
    """Response for finishing a flow."""

    success: bool
    message: str


class FlowPauseResponse(BaseModel):
    """Response for pausing a flow."""

    success: bool
    message: str


class FlowResumeResponse(BaseModel):
    """Response for resuming a flow."""

    success: bool
    message: str


@router.post("/finish", response_model=FlowFinishResponse)
async def finish_flow():
    """Request graceful finish — complete current loop cycle then stop."""
    manager = get_manager()
    success, message = await manager.finish_flow()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    return FlowFinishResponse(success=True, message=message)


@router.post("/pause", response_model=FlowPauseResponse)
async def pause_flow():
    """Pause the currently running flow."""
    manager = get_manager()
    success, message = await manager.pause_flow()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    return FlowPauseResponse(success=True, message=message)


@router.post("/resume", response_model=FlowResumeResponse)
async def resume_flow():
    """Resume a paused flow."""
    manager = get_manager()
    success, message = await manager.resume_flow()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
    return FlowResumeResponse(success=True, message=message)


# Default flow loaded when no AI generation is implemented.
# Hackathon challenge: replace this endpoint with real LLM-based flow generation.
_DEFAULT_FLOW_ID = "dobot_test_pick"


@router.post("/generate", response_model=FlowGenerateResponse)
async def generate_flow(request: FlowGenerateRequest):
    """
    Generate a robot automation flow from a natural language prompt.
    Includes a validation step to ensure intent feasibility.
    """
    logger.info("Generating flow for prompt: %r", request.prompt)
    
    # --- Step 1: Validation & Goal Mapping ---
    validation_prompt = f"""
    You are an industrial robotics expert. Validate the following instruction: "{request.prompt}"
    
    Available Executors and Skills:
    - robot: move_joint (params: target_joints_deg [list]), move_cartesian (params: target_pose [list]), set_tool_output (params: index, status), wait (params: duration_ms)
    - camera: detect_objects (params: class_name), read_label (params: prompt), check_quality (params: prompt), start_streaming, stop_streaming
    - hand: set_fingers (params: targets [list of 0-100])
    - io_robot: set_digital_output (params: index, status), get_digital_input (params: index)
    
    Instruction:
    1. Is the goal feasible with current hardware? (e.g., 'fly to Mars' is not)
    2. Can the instruction be mapped to the available skills?
    
    If FEASIBLE, respond with exactly "VALID".
    If NOT FEASIBLE, respond with "INVALID: [Detailed explanation of why and suggested alternatives]".
    """
    
    try:
        validation_result = await ai_service.generate_text(validation_prompt)
        if validation_result.startswith("INVALID:"):
            error_details = validation_result.replace("INVALID:", "").strip()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_details
            )
            
        # --- Step 2: Flow Generation ---
        system_prompt = """
        You are an industrial robotics expert. Generate a robot automation flow in JSON format based on the user's request.
        The response must be a valid JSON object conforming to the following structure (FlowSchema):
        {
          "id": "unique_id",
          "name": "Human Readable Name",
          "initial_state": "start_state_name",
          "loop": false,
          "variables": {},
          "states": [
            {
              "name": "state_name",
              "steps": [
                {
                  "id": "step_id",
                  "skill": "skill_name",
                  "executor": "robot|camera|io_robot|hand",
                  "params": {},
                  "timeout_ms": 30000
                }
              ]
            }
          ],
          "transitions": [
            {
              "type": "sequential|conditional",
              "from_state": "state_name",
              "to_state": "state_name",
              "condition": "optional_condition_string"
            }
          ]
        }
        
        Available Executors and Skills:
        - robot: move_joint (params: target_joints_deg [list]), move_cartesian (params: target_pose [list]), set_tool_output (params: index, status), wait (params: duration_ms)
        - camera: detect_objects (params: class_name), read_label (params: prompt), check_quality (params: prompt), start_streaming, stop_streaming
        - hand: set_fingers (params: targets [list of 0-100])
        - io_robot: set_digital_output (params: index, status), get_digital_input (params: index)
        
        Ensure the flow is logical, has a clear start, and follows industrial safety best practices.
        Return ONLY the JSON object, no other text.
        """
        
        response_text = await ai_service.generate_text(request.prompt, system_instruction=system_prompt)
        
        # Clean up response if it contains markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
            
        flow_data = json.loads(response_text)
        
        # Ensure ID and name are present
        if "id" not in flow_data or not flow_data["id"]:
            flow_data["id"] = f"gen_{uuid.uuid4().hex[:8]}"
        if "name" not in flow_data or not flow_data["name"]:
            flow_data["name"] = f"Generated Flow: {request.prompt[:30]}..."
            
        flow = FlowSchema.model_validate(flow_data)
        return convert_backend_to_frontend(flow)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Flow generation failed: {e}")
        # Fallback to default flow if generation fails completely
        manager = get_manager()
        flow = manager.get_flow(_DEFAULT_FLOW_ID)
        if flow is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Generation failed and default flow not found: {e}",
            )
        return convert_backend_to_frontend(flow)
