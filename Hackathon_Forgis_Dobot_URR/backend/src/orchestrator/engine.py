"""Always-on orchestrator engine with iterative skill-by-skill execution.

The engine now asks the planner for ONE step at a time, executes it, emits
the planner's reasoning to the frontend, and repeats — mirroring how Claude
Code selects one tool at a time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .gemini_client import GeminiClientError, OrchestratorGeminiClient
from .node_runner import NodeRunner
from .planner import OrchestratorPlanner
from .queue import OrchestratorTaskQueue
from .schemas import (
    CATCHY_PHRASES,
    SKILL_BY_NODE_TYPE,
    ClarificationAction,
    ClarificationDecision,
    ClarificationRequest,
    EngineStateSnapshot,
    FlowRunNodeRecord,
    FlowRunRecord,
    IterativePlanStep,
    NodePlan,
    NodeResultStatus,
    NodeType,
    OrchestratorState,
    OrchestratorTask,
    PlanResult,
    StepReasoning,
    TransitionRecord,
)
from .store import FlowRunStore

logger = logging.getLogger(__name__)


class OrchestratorEngine:
    """Deterministic always-on orchestrator supervisor with iterative planning."""

    def __init__(
        self,
        executors: dict[str, Any],
        ws_manager: Any,
        runs_dir: str,
        safe_z_config_path: str,
        queue_limit: int = 3,
        retention: int = 200,
    ):
        self._executors = executors
        self._ws = ws_manager

        self._state = OrchestratorState.BOOT
        self._last_error: Optional[str] = None

        self._queue = OrchestratorTaskQueue(max_size=queue_limit)
        self._store = FlowRunStore(runs_dir=runs_dir, retention=retention)

        self._gemini = OrchestratorGeminiClient()
        self._planner = OrchestratorPlanner(self._gemini)
        self._safe_z_config = self._load_safe_z_config(safe_z_config_path)
        self._runner = NodeRunner(
            executors=executors,
            gemini=self._gemini,
            planner=self._planner,
            safe_z_config=self._safe_z_config,
            emit=self._emit,
        )

        self._active_flow_id: Optional[str] = None
        self._active_run: Optional[FlowRunRecord] = None

        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        self._pending_decisions: dict[str, asyncio.Future[ClarificationDecision]] = {}
        self._goal_change_requests: dict[str, str] = {}

    @staticmethod
    def _load_safe_z_config(path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Safe Z config not found: {path}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "zones" not in data or "global_limits" not in data:
            raise ValueError("Safe Z config must include 'zones' and 'global_limits'")
        return data

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        await self._transition(OrchestratorState.CELL_CHECK, "boot complete")
        ok, reason = await self._run_cell_check()
        if not ok:
            self._last_error = reason
            await self._transition(OrchestratorState.ERROR, reason)
        else:
            await self._transition(OrchestratorState.READY, "cell check passed")

        if self._worker_task is None or self._worker_task.done():
            self._shutdown_event.clear()
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    # ── Public API ────────────────────────────────────────────

    async def enqueue_task(self, instruction: str) -> tuple[bool, str, Optional[OrchestratorTask], Optional[PlanResult]]:
        instruction = instruction.strip()
        if not instruction:
            return False, "Instruction must not be empty", None, None
        if self._state in {OrchestratorState.BOOT, OrchestratorState.CELL_CHECK, OrchestratorState.RECOVERY}:
            return False, f"Orchestrator is not ready yet (state={self._state.value})", None, None
        if self._state == OrchestratorState.ERROR:
            return False, f"Orchestrator is in ERROR state: {self._last_error or 'unknown'}", None, None

        task = OrchestratorTask(
            task_id=f"task_{uuid.uuid4().hex[:10]}",
            flow_id=f"flow_{uuid.uuid4().hex[:10]}",
            instruction=instruction,
        )

        try:
            preview = await self._planner.plan(
                instruction=instruction,
                cell_state=self._cell_state_snapshot(),
            )
        except ValueError as exc:
            return False, str(exc), None, None

        accepted, position = await self._queue.enqueue(task)
        if not accepted:
            return (
                False,
                f"Queue is full ({self._queue.max_size} pending max). Please retry later.",
                None,
                preview,
            )

        self._emit(
            "orchestrator_task_queued",
            {
                "task_id": task.task_id,
                "flow_id": task.flow_id,
                "instruction": task.instruction,
                "queue_position": position,
            },
        )
        return True, "Task queued", task, preview

    def is_actionable_task(self, instruction: str) -> bool:
        return OrchestratorPlanner.looks_like_robot_task(instruction)

    async def build_cell_manager_reply(self, query: str) -> str:
        context = await self._cell_manager_context()
        prompt = (
            "You are the Forgis cell manager. "
            "Answer conversationally and concisely, grounded strictly in the provided cell state. "
            "If a detail is unknown, say it is unknown. "
            "Do not invent hardware status. "
            "If user asks for action execution, ask for a concrete task command.\n\n"
            f"Cell state JSON:\n{json.dumps(context, ensure_ascii=True)}\n\n"
            f"User message: {query!r}"
        )
        try:
            return await self._gemini.generate_text(prompt, model=self._gemini.orchestrator_model)
        except Exception:
            snapshot = context.get("orchestrator", {})
            devices = context.get("devices", {})
            degraded = [name for name, state in devices.items() if not state.get("ready", False)]
            ready = [name for name, state in devices.items() if state.get("ready", False)]
            last_error = snapshot.get("last_error")
            state = snapshot.get("state", "UNKNOWN")
            queue_depth = snapshot.get("queue_depth", 0)
            queue_limit = snapshot.get("queue_limit", 0)

            parts = [
                f"Cell manager mode active. Orchestrator state is {state}.",
                f"Queue depth is {queue_depth}/{queue_limit}.",
                f"Ready devices: {', '.join(ready) if ready else 'none'}.",
                f"Unavailable devices: {', '.join(degraded) if degraded else 'none'}.",
            ]
            if last_error:
                parts.append(f"Last error: {last_error}.")
            parts.append("Send a concrete task command when you want execution, for example: pick box A and place it in Zone_A.")
            return " ".join(parts)

    async def get_state_snapshot(self) -> EngineStateSnapshot:
        return EngineStateSnapshot(
            state=self._state,
            queue_depth=await self._queue.depth(),
            queue_limit=self._queue.max_size,
            active_flow_id=self._active_flow_id,
            last_error=self._last_error,
        )

    async def list_queue(self) -> list[OrchestratorTask]:
        return await self._queue.list_pending()

    def list_runs(self, limit: int = 20, offset: int = 0) -> list[FlowRunRecord]:
        return self._store.list(limit=limit, offset=offset)

    def get_run(self, flow_id: str) -> Optional[FlowRunRecord]:
        return self._store.get(flow_id)

    async def submit_decision(self, flow_id: str, decision: ClarificationDecision) -> tuple[bool, str]:
        future = self._pending_decisions.get(flow_id)
        if future is None:
            return False, f"No pending clarification for flow {flow_id}"
        if future.done():
            return False, f"Clarification already resolved for flow {flow_id}"
        future.set_result(decision)
        self._emit("orchestrator_clarification_resolved", {
            "flow_id": flow_id,
            "action": decision.action.value,
            "note": decision.note,
        })
        return True, "Decision accepted"

    async def request_goal_change(self, flow_id: str, goal: str) -> tuple[bool, str]:
        if self._active_flow_id != flow_id:
            return False, f"Flow {flow_id} is not currently executing"
        self._goal_change_requests[flow_id] = goal
        self._emit("orchestrator_goal_change_requested", {
            "flow_id": flow_id,
            "goal": goal,
        })
        return True, "Goal change request registered"

    # ── Worker loop ───────────────────────────────────────────

    async def _worker_loop(self) -> None:
        while not self._shutdown_event.is_set():
            if self._state == OrchestratorState.ERROR:
                await self._transition(OrchestratorState.RECOVERY, "attempting recovery")
                ok, reason = await self._run_cell_check()
                if ok:
                    self._last_error = None
                    await self._transition(OrchestratorState.READY, "recovery successful")
                else:
                    self._last_error = reason
                    await self._transition(OrchestratorState.ERROR, reason)
                    await asyncio.sleep(2.0)
                    continue

            if self._state != OrchestratorState.READY:
                await asyncio.sleep(0.1)
                continue

            task = await self._queue.pop_next()
            if task is None:
                await asyncio.sleep(0.1)
                continue

            await self._transition(OrchestratorState.EXECUTING, f"executing {task.flow_id}")
            self._active_flow_id = task.flow_id
            run = await self._execute_task(task)
            self._store.save(run)
            self._active_run = None
            self._active_flow_id = None

            await self._transition(
                OrchestratorState.READY,
                f"run {task.flow_id} finished with {run.final_status}",
            )

    async def _run_cell_check(self) -> tuple[bool, str]:
        try:
            ok, reason = await self._gemini.health_check()
            if not ok:
                return False, f"Gemini check failed: {reason}"
        except GeminiClientError as exc:
            return False, f"Gemini config error: {exc}"
        except Exception as exc:
            return False, f"Gemini health check error: {exc}"
        return True, "ok"

    # ── Core execution — iterative skill-by-skill ─────────────

    async def _execute_task(self, task: OrchestratorTask) -> FlowRunRecord:
        """Execute a queued task using the iterative planner.

        Instead of building all nodes upfront, we ask the planner for
        one step at a time, execute it, evaluate, and repeat.
        """
        run = FlowRunRecord(
            flow_id=task.flow_id,
            instruction=task.instruction,
            started_at=time.time(),
        )
        self._active_run = run

        context: dict[str, Any] = {
            "flow_id": task.flow_id,
            "instruction": task.instruction,
            "executed_nodes": [],
            "deviations": [],
            "observations": [],
            "current_goal_index": 0,
        }

        # ── Phase 1: Static prefix (input + planner) ─────────
        static_prefix = [
            NodePlan(name="input", type=NodeType.INPUT_NODE, timeout_ms=30000, payload={}),
            NodePlan(name="planner", type=NodeType.ORCHESTRATOR_PLANNER_NODE, timeout_ms=30000, payload={}),
        ]

        for node in static_prefix:
            # Emit reasoning before each static node
            reasoning = self._planner.get_reasoning_for_node(node.type)
            skill = SKILL_BY_NODE_TYPE.get(node.type)
            skill_name = skill.name if skill else node.type.value

            self._emit("orchestrator_planning_thought", {
                "flow_id": task.flow_id,
                "thought": reasoning,
                "chosen_skill": skill_name,
                "phase": skill.phase if skill else "init",
                "catchy_phrase": CATCHY_PHRASES.get(skill_name, ["Working..."])[0],
                "node_name": node.name,
            })

            record = await self._execute_with_timeout(node, context)
            run.nodes.append(record)

            if record.status != NodeResultStatus.SUCCESS:
                await self._finalize_failed_run(run, record)
                return run

        # Detect special modes
        is_demo = self._planner.is_demo_command(task.instruction)
        is_jog = self._planner._is_jog_command(task.instruction)
        context["is_demo"] = is_demo
        context["is_jog"] = is_jog

        # Store jog payload if applicable
        if is_jog and not is_demo:
            plan_result: PlanResult = context.get("plan_result")
            if plan_result and plan_result.nodes:
                jog_node = next((n for n in plan_result.nodes if n.type == NodeType.JOG_JOINTS_NODE), None)
                if jog_node:
                    context["jog_payload"] = jog_node.payload

        # ── Phase 2: Iterative skill-by-skill execution ───────
        max_iterations = 50  # safety guard
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Check for mid-run goal change
            if task.flow_id in self._goal_change_requests:
                goal = self._goal_change_requests.pop(task.flow_id)
                proceed, new_plan = await self._handle_goal_change(run, task, goal, context)
                if not proceed:
                    run.final_status = "ABORTED"
                    run.completed_at = time.time()
                    return run
                # Reset goal index for replanned subgoals
                context["current_goal_index"] = 0
                continue

            # Ask planner for the next step (demo mode uses its own step planner)
            if context.get("is_demo"):
                step: IterativePlanStep = self._planner.plan_next_demo_step(context)
            else:
                step = await self._planner.plan_next_step(
                    instruction=task.instruction,
                    context=context,
                )

            # Emit the planner's reasoning to the frontend
            self._emit("orchestrator_planning_thought", {
                "flow_id": task.flow_id,
                "thought": step.reasoning.thought,
                "chosen_skill": step.reasoning.chosen_skill,
                "goal_index": step.reasoning.goal_index,
                "confidence": step.reasoning.confidence,
                "context_note": step.reasoning.context_note,
                "catchy_phrase": step.catchy_phrase,
                "is_complete": step.is_complete,
                "node_name": step.node.name if step.node else None,
            })

            # Task complete?
            if step.is_complete:
                run.final_status = "SUCCESS"
                run.completed_at = time.time()
                self._emit("orchestrator_run_completed", {
                    "flow_id": run.flow_id,
                    "final_status": run.final_status,
                    "catchy_phrase": step.catchy_phrase,
                })
                return run

            # Advance subgoal if the planner signals it
            if step.reasoning.chosen_skill == "advance_subgoal":
                context["current_goal_index"] = step.reasoning.goal_index
                continue

            # No node to execute (shouldn't happen, but guard)
            if step.node is None:
                continue

            node = step.node

            # ── Concurrent robot + live pair ──────────────────
            if node.type == NodeType.ROBOT_EXECUTION_NODE:
                # Peek ahead: plan the live node too
                live_step = await self._planner.plan_next_step(
                    instruction=task.instruction,
                    context={
                        **context,
                        # Pretend robot is done so planner picks narrate_live
                        "executed_nodes": context["executed_nodes"] + [
                            FlowRunNodeRecord(
                                name=node.name, type=node.type,
                                status=NodeResultStatus.SUCCESS,
                                start_time=time.time(), end_time=time.time(),
                                timeout_ms=node.timeout_ms,
                            )
                        ],
                    },
                )

                if live_step.node and live_step.node.type == NodeType.GEMINI_LIVE_COMMENTARY_NODE:
                    # Emit live node reasoning
                    self._emit("orchestrator_planning_thought", {
                        "flow_id": task.flow_id,
                        "thought": live_step.reasoning.thought,
                        "chosen_skill": live_step.reasoning.chosen_skill,
                        "catchy_phrase": live_step.catchy_phrase,
                        "node_name": live_step.node.name,
                    })

                    try:
                        robot_record, live_record = await asyncio.wait_for(
                            self._runner.execute_robot_and_live_pair(node, live_step.node, context),
                            timeout=max(node.timeout_ms, live_step.node.timeout_ms) / 1000.0,
                        )
                    except asyncio.TimeoutError:
                        robot_record = FlowRunNodeRecord(
                            name=node.name, type=node.type,
                            status=NodeResultStatus.TIMEOUT,
                            start_time=time.time(), end_time=time.time(),
                            timeout_ms=node.timeout_ms,
                            artifacts={"error": f"Node timed out after {node.timeout_ms}ms"},
                        )
                        live_record = FlowRunNodeRecord(
                            name=live_step.node.name, type=live_step.node.type,
                            status=NodeResultStatus.TIMEOUT,
                            start_time=time.time(), end_time=time.time(),
                            timeout_ms=live_step.node.timeout_ms,
                            artifacts={"error": f"Node timed out after {live_step.node.timeout_ms}ms"},
                        )

                    run.nodes.extend([robot_record, live_record])

                    if robot_record.status != NodeResultStatus.SUCCESS or live_record.status != NodeResultStatus.SUCCESS:
                        failed = robot_record if robot_record.status != NodeResultStatus.SUCCESS else live_record
                        proceed = await self._handle_failure_iterative(run, failed, task, context)
                        if not proceed:
                            run.completed_at = time.time()
                            return run
                    continue

            # ── Standard single-node execution ────────────────
            record = await self._execute_with_timeout(node, context)
            run.nodes.append(record)

            if record.status != NodeResultStatus.SUCCESS:
                proceed = await self._handle_failure_iterative(run, record, task, context)
                if not proceed:
                    run.completed_at = time.time()
                    return run

        # Exceeded max iterations
        run.final_status = "FAILURE"
        run.error_message = f"Exceeded maximum iterations ({max_iterations})"
        run.completed_at = time.time()
        return run

    # ── Execution helpers ─────────────────────────────────────

    async def _execute_with_timeout(
        self,
        node: NodePlan,
        context: dict[str, Any],
    ) -> FlowRunNodeRecord:
        try:
            return await asyncio.wait_for(
                self._runner.execute_node(node, context),
                timeout=node.timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            now = time.time()
            record = FlowRunNodeRecord(
                name=node.name,
                type=node.type,
                status=NodeResultStatus.TIMEOUT,
                start_time=now,
                end_time=now,
                timeout_ms=node.timeout_ms,
                artifacts={"error": f"Node timed out after {node.timeout_ms}ms"},
            )
            self._emit("orchestrator_node_finished", {
                "flow_id": context["flow_id"],
                "node_name": node.name,
                "node_type": node.type.value,
                "status": NodeResultStatus.TIMEOUT.value,
                "duration_ms": node.timeout_ms,
                "artifacts": record.artifacts,
            })
            return record

    # ── Failure handling (iterative mode) ─────────────────────

    async def _handle_failure_iterative(
        self,
        run: FlowRunRecord,
        failed_node: FlowRunNodeRecord,
        task: OrchestratorTask,
        context: dict[str, Any],
    ) -> bool:
        """Handle a failed node.  Returns True to continue, False to stop."""
        reason = failed_node.artifacts.get("error") or f"Node {failed_node.name} failed"

        decision = await self._request_clarification(
            flow_id=run.flow_id,
            node_name=failed_node.name,
            reason=reason,
        )

        if decision is None:
            run.final_status = "TIMEOUT"
            run.error_message = f"Clarification timeout after failure in {failed_node.name}"
            self._emit("orchestrator_clarification_timeout", {
                "flow_id": run.flow_id,
                "node_name": failed_node.name,
            })
            return False

        action = decision.action
        note = decision.note or ""

        if action == ClarificationAction.SAFE_STOP:
            run.final_status = "ABORTED"
            run.error_message = reason
            return False

        if action == ClarificationAction.RETRY:
            retry_plan = NodePlan(
                name=failed_node.name,
                type=failed_node.type,
                timeout_ms=failed_node.timeout_ms,
                payload=self._find_payload_for_node(context, failed_node.name),
            )

            self._emit("orchestrator_planning_thought", {
                "flow_id": run.flow_id,
                "thought": f"Retrying {failed_node.name} after operator approval...",
                "chosen_skill": "retry",
                "catchy_phrase": "Second time's the charm...",
                "node_name": failed_node.name,
            })

            retry_record = await self._execute_with_timeout(retry_plan, context)
            run.nodes.append(retry_record)
            if retry_record.status == NodeResultStatus.SUCCESS:
                return True
            run.final_status = "FAILURE"
            run.error_message = (
                retry_record.artifacts.get("error")
                or f"Retry failed for node {failed_node.name}"
            )
            return False

        # REPLAN or MODIFY_GOAL
        note = note or ("Operator requested replanning" if action == ClarificationAction.REPLAN else "")
        plan = await self._planner.replan(
            instruction=task.instruction,
            previous_subgoals=context.get("subgoals", []),
            note=note,
            cell_state=self._cell_state_snapshot(),
        )
        context["plan_result"] = plan
        context["plan_nodes"] = plan.nodes
        context["subgoals"] = plan.subgoals
        context["current_goal_index"] = 0
        # Clear executed nodes for the replanned subgoals (keep input + planner)
        context["executed_nodes"] = [
            n for n in context.get("executed_nodes", [])
            if hasattr(n, "type") and n.type in {NodeType.INPUT_NODE, NodeType.ORCHESTRATOR_PLANNER_NODE}
        ]

        self._emit("orchestrator_replanned", {
            "flow_id": run.flow_id,
            "reason": reason,
            "action": action.value,
            "subgoals": plan.subgoals,
        })

        self._emit("orchestrator_planning_thought", {
            "flow_id": run.flow_id,
            "thought": f"Replanned with {len(plan.subgoals)} new subgoals. Starting fresh.",
            "chosen_skill": "decompose_task",
            "catchy_phrase": "New plan, who dis?",
        })

        return True

    async def _handle_goal_change(
        self,
        run: FlowRunRecord,
        task: OrchestratorTask,
        goal: str,
        context: dict[str, Any],
    ) -> tuple[bool, list[NodePlan]]:
        decision = await self._request_clarification(
            flow_id=run.flow_id,
            node_name="goal_change",
            reason=f"Apply new goal: {goal}",
        )

        if decision is None or decision.action == ClarificationAction.SAFE_STOP:
            run.error_message = "Goal change was not approved"
            return False, []

        note = decision.note or goal
        plan = await self._planner.replan(
            instruction=goal,
            previous_subgoals=context.get("subgoals", []),
            note=note,
            cell_state=self._cell_state_snapshot(),
        )
        task.instruction = goal
        context["instruction"] = goal
        context["plan_result"] = plan
        context["plan_nodes"] = plan.nodes
        context["subgoals"] = plan.subgoals

        self._emit("orchestrator_goal_change_applied", {
            "flow_id": run.flow_id,
            "goal": goal,
        })

        return True, list(plan.nodes)

    # ── Clarification ─────────────────────────────────────────

    async def _request_clarification(
        self,
        flow_id: str,
        node_name: str,
        reason: str,
    ) -> Optional[ClarificationDecision]:
        req = ClarificationRequest(
            flow_id=flow_id,
            node_name=node_name,
            reason=reason,
        )
        future: asyncio.Future[ClarificationDecision] = asyncio.get_running_loop().create_future()
        self._pending_decisions[flow_id] = future

        self._emit("orchestrator_clarification_requested", {
            "flow_id": flow_id,
            "node_name": node_name,
            "reason": reason,
            "timeout_seconds": req.timeout_seconds,
            "choices": [choice.value for choice in req.choices],
        })

        try:
            decision = await asyncio.wait_for(future, timeout=req.timeout_seconds)
            return decision
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_decisions.pop(flow_id, None)

    def _find_payload_for_node(self, context: dict[str, Any], node_name: str) -> dict[str, Any]:
        for plan in context.get("plan_nodes", []):
            if plan.name == node_name:
                return dict(plan.payload)
        return {}

    async def _finalize_failed_run(self, run: FlowRunRecord, record: FlowRunNodeRecord) -> None:
        run.final_status = "FAILURE"
        run.error_message = record.artifacts.get("error") or f"Node {record.name} failed"
        run.completed_at = time.time()
        self._emit("orchestrator_run_completed", {
            "flow_id": run.flow_id,
            "final_status": run.final_status,
            "error": run.error_message,
        })

    # ── State helpers ─────────────────────────────────────────

    def _cell_state_snapshot(self) -> dict[str, Any]:
        return {
            name: {
                "ready": bool(executor.is_ready()) if hasattr(executor, "is_ready") else False,
            }
            for name, executor in self._executors.items()
        }

    async def _cell_manager_context(self) -> dict[str, Any]:
        snapshot = await self.get_state_snapshot()
        pending = await self.list_queue()
        latest_runs = self._store.list(limit=1, offset=0)
        latest_run = latest_runs[0] if latest_runs else None

        devices: dict[str, Any] = {}
        for name, executor in self._executors.items():
            entry: dict[str, Any] = {
                "ready": bool(executor.is_ready()) if hasattr(executor, "is_ready") else False,
                "executor_type": executor.__class__.__name__,
            }
            if hasattr(executor, "get_hand_status"):
                try:
                    entry["status"] = executor.get_hand_status()
                except Exception:
                    entry["status"] = None
            devices[name] = entry

        return {
            "orchestrator": snapshot.model_dump(),
            "devices": devices,
            "pending_tasks": [task.model_dump() for task in pending],
            "latest_run": latest_run.model_dump() if latest_run else None,
        }

    async def _transition(self, to_state: OrchestratorState, reason: str) -> None:
        from_state = self._state
        self._state = to_state
        self._emit("orchestrator_state_transition", {
            "from_state": from_state.value,
            "to_state": to_state.value,
            "reason": reason,
        })

        if self._active_run is not None:
            self._active_run.state_transitions.append(
                TransitionRecord(from_state=from_state, to_state=to_state, reason=reason)
            )

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._ws.broadcast(event_type, data))
        except RuntimeError:
            logger.debug("No running loop for orchestrator event %s", event_type)
