import pytest

from orchestrator.queue import OrchestratorTaskQueue
from orchestrator.schemas import OrchestratorTask


@pytest.mark.asyncio
async def test_queue_enforces_max_size_and_fifo_order():
    queue = OrchestratorTaskQueue(max_size=3)

    t1 = OrchestratorTask(task_id="t1", flow_id="f1", instruction="one")
    t2 = OrchestratorTask(task_id="t2", flow_id="f2", instruction="two")
    t3 = OrchestratorTask(task_id="t3", flow_id="f3", instruction="three")
    t4 = OrchestratorTask(task_id="t4", flow_id="f4", instruction="four")

    ok1, _ = await queue.enqueue(t1)
    ok2, _ = await queue.enqueue(t2)
    ok3, _ = await queue.enqueue(t3)
    ok4, depth = await queue.enqueue(t4)

    assert ok1 and ok2 and ok3
    assert not ok4
    assert depth == 3

    p1 = await queue.pop_next()
    p2 = await queue.pop_next()
    p3 = await queue.pop_next()

    assert p1 is not None and p1.task_id == "t1"
    assert p2 is not None and p2.task_id == "t2"
    assert p3 is not None and p3.task_id == "t3"
    assert await queue.pop_next() is None
