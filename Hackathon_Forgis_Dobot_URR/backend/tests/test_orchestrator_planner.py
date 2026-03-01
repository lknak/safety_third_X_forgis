import pytest

from orchestrator.planner import OrchestratorPlanner
from orchestrator.schemas import NodeType


class StaticGemini:
    async def generate_json(self, prompt: str, model=None):
        return {
            "assumptions": ["camera connected"],
            "skills": [
                {"skill": "capture_image", "params": {}, "description": "Capture scene"},
                {"skill": "analyze_scene", "params": {"query": "find target box"}, "description": "Analyze scene"},
                {"skill": "depth_estimation", "params": {"bbox": {"x": 0.5, "y": 0.5, "width": 0.2, "height": 0.2}, "object_class": "box"}, "description": "Estimate depth"},
                {"skill": "estimate_grasp_pose", "params": {"bbox": {"x": 0.5, "y": 0.5, "width": 0.2, "height": 0.2}, "object_class": "box"}, "description": "Estimate grasp"},
                {"skill": "suction_on", "params": {}, "description": "Pick"},
                {"skill": "suction_off", "params": {}, "description": "Release"},
                {"skill": "verify_outcome", "params": {"expected_state": "box moved"}, "description": "Verify"},
            ],
        }


class EmptyGemini:
    async def generate_json(self, prompt: str, model=None):
        return {"assumptions": [], "skills": []}


class MicroGemini:
    async def generate_json(self, prompt: str, model=None):
        return {
            "task_complete": False,
            "reasoning": "One chocolate bar remains near the center.",
            "scene_summary": "1 chocolate, 0 strawberry bars on table.",
            "progress": {"completed": 9, "estimated_remaining": 1, "notes": "continue"},
            "skills": [
                {"skill": "depth_estimation", "params": {"bbox": {"x": 0.4, "y": 0.4, "width": 0.1, "height": 0.1}, "object_class": "chocolate_bar"}, "description": "Estimate depth"},
                {"skill": "estimate_grasp_pose", "params": {"bbox": {"x": 0.4, "y": 0.4, "width": 0.1, "height": 0.1}, "object_class": "chocolate_bar"}, "description": "Estimate grasp"},
                {"skill": "suction_on", "params": {}, "description": "Pick"},
            ],
        }


class IntentGemini:
    async def generate_json(self, prompt: str, model=None):
        if "is the camera connected?" in prompt:
            return {"route": "CELL_MANAGER", "reason": "status query"}
        return {"route": "ORCHESTRATE", "reason": "execution request"}


@pytest.mark.asyncio
async def test_planner_builds_primitive_node_order_for_static_tasks():
    planner = OrchestratorPlanner(StaticGemini())
    result = await planner.plan("Pick one box and place it in Zone_A", {"robot": {"ready": True}})

    assert result.is_agentic is False
    assert result.nodes[0].type == NodeType.CAPTURE_IMAGE
    assert result.nodes[1].type == NodeType.ANALYZE_SCENE
    assert result.nodes[2].type == NodeType.DEPTH_ESTIMATION
    assert result.nodes[3].type == NodeType.ESTIMATE_GRASP_POSE
    assert result.nodes[-1].type == NodeType.SUMMARY_NODE


@pytest.mark.asyncio
async def test_planner_marks_dynamic_tasks_as_agentic():
    planner = OrchestratorPlanner(StaticGemini())
    result = await planner.plan(
        "Segregate chocolate and strawberry flavour bars into two boxes",
        {"robot": {"ready": True}},
    )

    assert result.is_agentic is True
    assert result.nodes == []
    assert result.subgoals[0]["id"] == "agentic_loop"


@pytest.mark.asyncio
async def test_planner_rejects_non_actionable_instruction():
    planner = OrchestratorPlanner(EmptyGemini())

    with pytest.raises(ValueError, match="No actionable task detected"):
        await planner.plan("hello", {"robot": {"ready": True}})


@pytest.mark.asyncio
async def test_planner_falls_back_when_model_returns_no_skills():
    planner = OrchestratorPlanner(EmptyGemini())
    result = await planner.plan("Pick a box and place it at zone a", {"robot": {"ready": True}})

    assert result.is_agentic is False
    assert result.subgoals
    assert result.nodes[0].type == NodeType.CAPTURE_IMAGE
    assert result.nodes[-1].type == NodeType.SUMMARY_NODE


@pytest.mark.asyncio
async def test_plan_next_step_returns_micro_plan_and_nodes():
    planner = OrchestratorPlanner(MicroGemini())
    micro = await planner.plan_next_step(
        goal="Sort all bars by flavor",
        scene_analysis={"objects": [{"label": "chocolate_bar"}]},
        history=[],
        cell_state={"robot": {"ready": True}},
        iteration=1,
    )

    assert micro.task_complete is False
    assert "chocolate" in micro.reasoning.lower()
    nodes = planner.micro_plan_to_nodes(micro, iteration=1)
    assert nodes[0].type == NodeType.DEPTH_ESTIMATION
    assert nodes[1].type == NodeType.ESTIMATE_GRASP_POSE
    assert nodes[2].type == NodeType.SUCTION_ON


@pytest.mark.asyncio
async def test_planner_uses_model_to_route_orchestrator_vs_cell_manager():
    planner = OrchestratorPlanner(IntentGemini())
    cell_state = {"robot": {"ready": True}, "camera": {"ready": True}}

    assert await planner.should_orchestrate("is the camera connected?", cell_state) is False
    assert await planner.should_orchestrate("pick the red box and place it in zone A", cell_state) is True
