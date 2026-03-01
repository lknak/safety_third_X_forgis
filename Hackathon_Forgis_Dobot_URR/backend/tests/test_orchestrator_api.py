from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.orchestrator import router, set_orchestrator_engine
from orchestrator.schemas import ClarificationDecision, EngineStateSnapshot, OrchestratorState, OrchestratorTask, PlanResult, NodePlan, NodeType


class FakeEngine:
    async def enqueue_task(self, instruction: str):
        task = OrchestratorTask(task_id="task_1", flow_id="flow_1", instruction=instruction)
        preview = PlanResult(
            subgoals=[{"id": "g1"}],
            assumptions=[],
            nodes=[NodePlan(name="summary", type=NodeType.SUMMARY_NODE, payload={}, timeout_ms=30000)],
        )
        return True, "Task queued", task, preview

    async def get_state_snapshot(self):
        return EngineStateSnapshot(
            state=OrchestratorState.READY,
            queue_depth=1,
            queue_limit=3,
            active_flow_id=None,
            last_error=None,
        )

    async def list_queue(self):
        return [OrchestratorTask(task_id="task_1", flow_id="flow_1", instruction="do x")]

    def list_runs(self, limit: int = 20, offset: int = 0):
        return []

    def get_run(self, flow_id: str):
        return None

    async def submit_decision(self, flow_id: str, decision: ClarificationDecision):
        return True, "Decision accepted"

    async def request_goal_change(self, flow_id: str, goal: str):
        return True, "Goal change request registered"


class RejectingEngine(FakeEngine):
    def is_actionable_task(self, instruction: str) -> bool:
        return True

    async def build_cell_manager_reply(self, query: str):
        return "Cell manager reply"

    async def enqueue_task(self, instruction: str):
        return False, "No actionable robot task detected.", None, None


class CellManagerEngine(FakeEngine):
    def is_actionable_task(self, instruction: str) -> bool:
        return False

    async def build_cell_manager_reply(self, query: str):
        return "Cell is healthy and ready for a task."


class ActionableEngine(FakeEngine):
    def is_actionable_task(self, instruction: str) -> bool:
        return True

    async def build_cell_manager_reply(self, query: str):
        return "unused"


def test_task_endpoint_returns_preview_flow():
    app = FastAPI()
    app.include_router(router)
    set_orchestrator_engine(ActionableEngine())

    client = TestClient(app)
    response = client.post("/api/orchestrator/tasks", json={"instruction": "pick box"})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["mode"] == "orchestrator"
    assert body["flow_id"] == "flow_1"
    assert body["preview_flow"]["nodes"][0]["id"] == "start"


def test_task_endpoint_returns_non_accepted_payload_without_http_error():
    app = FastAPI()
    app.include_router(router)
    set_orchestrator_engine(RejectingEngine())

    client = TestClient(app)
    response = client.post("/api/orchestrator/tasks", json={"instruction": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["mode"] == "orchestrator"
    assert "No actionable robot task" in body["message"]


def test_task_endpoint_uses_cell_manager_mode_for_non_actionable_input():
    app = FastAPI()
    app.include_router(router)
    set_orchestrator_engine(CellManagerEngine())

    client = TestClient(app)
    response = client.post("/api/orchestrator/tasks", json={"instruction": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["mode"] == "cell_manager"
    assert "ready for a task" in body["message"]


def test_decision_endpoint_accepts_payload():
    app = FastAPI()
    app.include_router(router)
    set_orchestrator_engine(FakeEngine())

    client = TestClient(app)
    response = client.post(
        "/api/orchestrator/runs/flow_1/decision",
        json={"action": "retry", "note": "try once"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
