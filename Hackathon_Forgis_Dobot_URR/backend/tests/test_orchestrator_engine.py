import asyncio
import json
import time

import pytest

from orchestrator.engine import OrchestratorEngine
from orchestrator.schemas import (
    ClarificationDecision,
    NodePlan,
    NodeResultStatus,
    NodeType,
    PlanResult,
    FlowRunNodeRecord,
)


class FakeWS:
    def __init__(self):
        self.events = []

    async def broadcast(self, event_type: str, data: dict):
        self.events.append((event_type, data))


class FakeExecutor:
    def is_ready(self):
        return True

    async def move_linear(self, pose, acceleration=0.5, velocity=0.1, timeout=30.0):
        return True


@pytest.fixture
def safe_config(tmp_path):
    config_path = tmp_path / "safe_z_config.json"
    config_path.write_text(
        json.dumps(
            {
                "global_limits": {"min_z": 0.05, "max_z": 0.4},
                "robot": {"safety_margin_z": 0.03},
                "workspace": {"x_min": -0.2, "x_max": 0.2, "y_min": -0.3, "y_max": 0.3},
                "zones": {
                    "default": {
                        "grasp_z": 0.12,
                        "place_z": 0.16,
                        "default": {"grasp_z": 0.12, "place_z": 0.16},
                        "objects": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return str(config_path)


@pytest.mark.asyncio
async def test_engine_processes_queued_task_with_mocked_runner(tmp_path, safe_config):
    ws = FakeWS()
    executors = {
        "robot": FakeExecutor(),
        "camera": FakeExecutor(),
    }

    engine = OrchestratorEngine(
        executors=executors,
        ws_manager=ws,
        runs_dir=str(tmp_path / "runs"),
        safe_z_config_path=safe_config,
        queue_limit=3,
        retention=200,
    )

    async def fake_health_check():
        return True, "OK"

    async def fake_plan(instruction: str, cell_state: dict):
        return PlanResult(
            subgoals=[{"id": "g1", "object": "box", "target_zone": "default", "object_class": "box"}],
            assumptions=[],
            nodes=[NodePlan(name="summary", type=NodeType.SUMMARY_NODE, payload={}, timeout_ms=30000)],
        )

    async def fake_execute_node(node: NodePlan, context: dict):
        now = time.time()
        if node.type == NodeType.ORCHESTRATOR_PLANNER_NODE:
            context["plan_result"] = await fake_plan(context["instruction"], context.get("cell_state", {}))
            context["plan_nodes"] = list(context["plan_result"].nodes)
        return FlowRunNodeRecord(
            name=node.name,
            type=node.type,
            status=NodeResultStatus.SUCCESS,
            start_time=now,
            end_time=now,
            timeout_ms=node.timeout_ms,
            artifacts={},
        )

    engine._gemini.health_check = fake_health_check  # type: ignore[attr-defined]
    engine._planner.plan = fake_plan  # type: ignore[assignment]
    engine._runner.execute_node = fake_execute_node  # type: ignore[assignment]

    await engine.start()
    accepted, message, task, _preview = await engine.enqueue_task("pick one box")

    assert accepted
    assert task is not None
    assert "queued" in message.lower()

    # Wait for worker to process.
    deadline = time.time() + 3
    while time.time() < deadline:
        runs = engine.list_runs(limit=10)
        if runs:
            break
        await asyncio.sleep(0.05)

    runs = engine.list_runs(limit=10)
    assert len(runs) >= 1
    assert runs[0].final_status == "SUCCESS"

    ok, decision_message = await engine.submit_decision(
        task.flow_id,
        ClarificationDecision(action="safe_stop", note="unused"),
    )
    assert not ok
    assert "No pending clarification" in decision_message

    await engine.stop()
