import time

from orchestrator.schemas import FlowRunNodeRecord, FlowRunRecord, NodeResultStatus, NodeType
from orchestrator.store import FlowRunStore


def _make_run(flow_id: str) -> FlowRunRecord:
    now = time.time()
    return FlowRunRecord(
        flow_id=flow_id,
        instruction=f"instruction {flow_id}",
        started_at=now,
        completed_at=now,
        final_status="SUCCESS",
        nodes=[
            FlowRunNodeRecord(
                name="input",
                type=NodeType.INPUT_NODE,
                status=NodeResultStatus.SUCCESS,
                start_time=now,
                end_time=now,
                artifacts={},
            )
        ],
    )


def test_run_store_prunes_to_retention(tmp_path):
    store = FlowRunStore(str(tmp_path), retention=2)

    store.save(_make_run("flow_1"))
    time.sleep(0.01)
    store.save(_make_run("flow_2"))
    time.sleep(0.01)
    store.save(_make_run("flow_3"))

    runs = store.list(limit=10, offset=0)
    ids = [run.flow_id for run in runs]

    assert len(ids) == 2
    assert "flow_3" in ids
    assert "flow_2" in ids
    assert store.get("flow_1") is None
