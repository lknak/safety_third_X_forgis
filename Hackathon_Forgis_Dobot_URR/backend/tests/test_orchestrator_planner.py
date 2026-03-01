import pytest

from orchestrator.planner import OrchestratorPlanner
from orchestrator.schemas import NodeType


class FakeGemini:
    async def generate_json(self, prompt: str, model=None):
        return {
            "subgoals": [
                {
                    "id": "g1",
                    "object": "box A",
                    "source_zone": "infeed",
                    "target_zone": "Zone_A",
                    "object_class": "box",
                },
                {
                    "id": "g2",
                    "object": "box B",
                    "source_zone": "infeed",
                    "target_zone": "Zone_B",
                    "object_class": "box",
                },
            ],
            "assumptions": ["camera connected"],
        }


class EmptyGemini:
    async def generate_json(self, prompt: str, model=None):
        return {"subgoals": [], "assumptions": []}


@pytest.mark.asyncio
async def test_planner_builds_expected_node_order():
    planner = OrchestratorPlanner(FakeGemini())
    result = await planner.plan("Pick A then B", {"robot": {"ready": True}})

    assert result.nodes[0].type == NodeType.ER_1_5_ANALYSIS_NODE
    assert result.nodes[1].type == NodeType.DEPTH_ESTIMATION_NODE
    assert result.nodes[2].type == NodeType.ROBOT_EXECUTION_NODE
    assert result.nodes[3].type == NodeType.GEMINI_LIVE_COMMENTARY_NODE
    assert result.nodes[4].type == NodeType.VERIFICATION_NODE
    assert result.nodes[-1].type == NodeType.SUMMARY_NODE


@pytest.mark.asyncio
async def test_planner_rejects_non_actionable_instruction():
    planner = OrchestratorPlanner(EmptyGemini())

    with pytest.raises(ValueError, match="No actionable robot task detected"):
        await planner.plan("hello", {"robot": {"ready": True}})


@pytest.mark.asyncio
async def test_planner_falls_back_when_model_returns_no_subgoals_for_actionable_task():
    planner = OrchestratorPlanner(EmptyGemini())
    result = await planner.plan("Pick a box and place it at zone a", {"robot": {"ready": True}})

    assert result.subgoals
    assert result.subgoals[0]["id"] == "goal_1"
    assert result.subgoals[0]["source_zone"] == "current_zone"
    assert result.subgoals[0]["target_zone"] in {"zone_a", "target_zone"}
    assert result.nodes[0].type == NodeType.ER_1_5_ANALYSIS_NODE
    assert result.nodes[-1].type == NodeType.SUMMARY_NODE
