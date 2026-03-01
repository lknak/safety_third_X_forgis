"""Node execution runtime for orchestrator FlowRuns.

Dispatches each NodePlan to the matching primitive skill via the skill registry,
while keeping legacy node handlers for backward compatibility.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any, Callable, Optional

from .gemini_client import OrchestratorGeminiClient
from .planner import OrchestratorPlanner
from .schemas import (
    FlowRunNodeRecord,
    NodePlan,
    NodeResultStatus,
    NodeType,
    PlanResult,
)

logger = logging.getLogger(__name__)

EventEmitter = Callable[[str, dict[str, Any]], None]

# Map NodeType → primitive skill name
_NODE_TO_SKILL: dict[NodeType, str] = {
    NodeType.CAPTURE_IMAGE: "capture_image",
    NodeType.ANALYZE_SCENE: "analyze_scene",
    NodeType.ESTIMATE_GRASP_POSE: "estimate_grasp_pose",
    NodeType.LLM_REASON: "llm_reason",
    NodeType.LIVE_NARRATE: "live_narrate",
    NodeType.MOVE_TO_POSE: "move_to_pose",
    NodeType.MOVE_JOINTS: "move_joints",
    NodeType.JOG_JOINTS: "jog_joints_primitive",
    NodeType.GET_ROBOT_STATE: "get_robot_state",
    NodeType.SUCTION_ON: "suction_on",
    NodeType.SUCTION_OFF: "suction_off",
    NodeType.SET_DIGITAL_OUTPUT: "set_digital_output",
    NodeType.WAIT_DIGITAL_INPUT: "wait_digital_input",
    NodeType.WAIT: "wait",
    NodeType.VERIFY_OUTCOME: "verify_outcome",
}


class NodeRunner:
    """Executes strict node plan elements with finite outcomes."""

    def __init__(
        self,
        executors: dict[str, Any],
        gemini: OrchestratorGeminiClient,
        planner: OrchestratorPlanner,
        safe_z_config: dict[str, Any],
        emit: Optional[EventEmitter] = None,
    ):
        self._executors = executors
        self._gemini = gemini
        self._planner = planner
        self._safe_z = safe_z_config
        self._emit = emit or (lambda _t, _d: None)

    async def execute_node(
        self,
        plan: NodePlan,
        context: dict[str, Any],
    ) -> FlowRunNodeRecord:
        """Execute a node and return run record entry."""
        start = time.time()
        self._emit(
            "orchestrator_node_started",
            {
                "flow_id": context["flow_id"],
                "node_name": plan.name,
                "node_type": plan.type.value,
            },
        )

        try:
            status = NodeResultStatus.SUCCESS
            artifacts: dict[str, Any] = {}

            # Meta-nodes handled directly
            if plan.type == NodeType.INPUT_NODE:
                artifacts = await self._run_input_node(context)
            elif plan.type == NodeType.ORCHESTRATOR_PLANNER_NODE:
                artifacts = await self._run_planner_node(context)
            elif plan.type == NodeType.SUMMARY_NODE:
                artifacts = await self._run_summary_node(context)

            # Legacy node types (backward compatibility)
            elif plan.type == NodeType.ER_1_5_ANALYSIS_NODE:
                artifacts, status = await self._run_er_node(plan, context)
            elif plan.type == NodeType.DEPTH_ESTIMATION_NODE:
                artifacts, status = await self._run_depth_node(plan, context)
            elif plan.type == NodeType.ROBOT_EXECUTION_NODE:
                artifacts, status = await self._run_robot_node(plan, context)
            elif plan.type == NodeType.GEMINI_LIVE_COMMENTARY_NODE:
                artifacts, status = await self._run_live_node(plan, context)
            elif plan.type == NodeType.VERIFICATION_NODE:
                artifacts, status = await self._run_verification_node(plan, context)
            elif plan.type == NodeType.JOG_JOINTS_NODE:
                artifacts, status = await self._run_jog_joints_node(plan, context)

            # ── Primitive skill dispatch ─────────────────────────────────
            elif plan.type in _NODE_TO_SKILL:
                artifacts, status = await self._run_primitive_skill(plan, context)

            else:
                status = NodeResultStatus.FAILURE
                artifacts = {"error": f"Unsupported node type: {plan.type.value}"}

        except Exception as exc:
            status = NodeResultStatus.FAILURE
            artifacts = {"error": str(exc)}
            logger.exception("Node %s failed", plan.name)

        end = time.time()
        record = FlowRunNodeRecord(
            name=plan.name,
            type=plan.type,
            status=status,
            start_time=start,
            end_time=end,
            artifacts=artifacts,
            timeout_ms=plan.timeout_ms,
        )

        context.setdefault("executed_nodes", []).append(record)
        self._emit(
            "orchestrator_node_finished",
            {
                "flow_id": context["flow_id"],
                "node_name": plan.name,
                "node_type": plan.type.value,
                "status": status.value,
                "duration_ms": int((end - start) * 1000),
                "artifacts": artifacts,
            },
        )

        return record

    # ── Primitive skill execution ────────────────────────────────────────────

    async def _run_primitive_skill(
        self,
        plan: NodePlan,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], NodeResultStatus]:
        """Execute a primitive skill by name from the skill registry."""
        from skills.base import ExecutionContext
        from skills.registry import get_skill

        skill_name = _NODE_TO_SKILL.get(plan.type)
        if not skill_name:
            return {"error": f"No skill mapped for {plan.type.value}"}, NodeResultStatus.FAILURE

        try:
            skill = get_skill(skill_name)
        except KeyError:
            return {"error": f"Skill '{skill_name}' not registered"}, NodeResultStatus.FAILURE

        # Build execution context
        params_dict = plan.payload.get("params", {})
        exec_context = ExecutionContext(
            flow_id=context["flow_id"],
            step_id=plan.name,
            state_name=plan.name,
            executor_type=skill.executor_type,
            executors=self._executors,
            variables=context.setdefault("variables", {}),
        )

        # Parse and validate params
        try:
            params = skill.parse_params(params_dict)
        except Exception as exc:
            return {"error": f"Invalid params for '{skill_name}': {exc}"}, NodeResultStatus.FAILURE

        valid, err_msg = await skill.validate(params)
        if not valid:
            return {"error": f"Validation failed for '{skill_name}': {err_msg}"}, NodeResultStatus.FAILURE

        # Execute
        result = await skill.execute(params, exec_context)

        # Propagate variables back to context
        context["variables"] = exec_context.variables

        artifacts = {
            "skill_name": skill_name,
            "description": plan.payload.get("description", ""),
            "result": result.data,
        }
        if result.error:
            artifacts["error"] = result.error

        status = NodeResultStatus.SUCCESS if result.success else NodeResultStatus.FAILURE
        return artifacts, status

    # ── Concurrent robot + live commentary ───────────────────────────────────

    async def execute_robot_and_live_pair(
        self,
        robot_plan: NodePlan,
        live_plan: NodePlan,
        context: dict[str, Any],
    ) -> tuple[FlowRunNodeRecord, FlowRunNodeRecord]:
        """Execute robot and live nodes concurrently."""
        self._emit(
            "orchestrator_tile_focus",
            {
                "flow_id": context["flow_id"],
                "active_node": live_plan.name,
                "primary_tile": "live",
            },
        )

        robot_start = time.time()
        self._emit(
            "orchestrator_node_started",
            {
                "flow_id": context["flow_id"],
                "node_name": robot_plan.name,
                "node_type": robot_plan.type.value,
            },
        )

        robot_task = asyncio.create_task(self._run_primitive_skill(robot_plan, context))

        live_record_task = asyncio.create_task(
            self._run_live_during_robot(live_plan, context, robot_task)
        )

        try:
            robot_artifacts, robot_status = await robot_task
        except Exception as exc:
            robot_artifacts = {"error": str(exc)}
            robot_status = NodeResultStatus.FAILURE

        robot_end = time.time()
        robot_record = FlowRunNodeRecord(
            name=robot_plan.name,
            type=robot_plan.type,
            status=robot_status,
            start_time=robot_start,
            end_time=robot_end,
            artifacts=robot_artifacts,
            timeout_ms=robot_plan.timeout_ms,
        )

        self._emit(
            "orchestrator_node_finished",
            {
                "flow_id": context["flow_id"],
                "node_name": robot_plan.name,
                "node_type": robot_plan.type.value,
                "status": robot_status.value,
                "duration_ms": int((robot_end - robot_start) * 1000),
                "artifacts": robot_artifacts,
            },
        )

        live_record = await live_record_task

        context.setdefault("executed_nodes", []).append(robot_record)
        context.setdefault("executed_nodes", []).append(live_record)
        return robot_record, live_record

    # ── Meta-node handlers ───────────────────────────────────────────────────

    async def _run_input_node(self, context: dict[str, Any]) -> dict[str, Any]:
        cell_state = {
            name: {
                "ready": bool(executor.is_ready()) if hasattr(executor, "is_ready") else False,
            }
            for name, executor in self._executors.items()
        }
        context["cell_state"] = cell_state
        return {
            "raw_instruction": context["instruction"],
            "timestamp": time.time(),
            "cell_state": cell_state,
        }

    async def _run_planner_node(self, context: dict[str, Any]) -> dict[str, Any]:
        result: PlanResult = await self._planner.plan(
            instruction=context["instruction"],
            cell_state=context.get("cell_state", {}),
        )
        context["plan_result"] = result
        context["plan_nodes"] = result.nodes
        context["subgoals"] = result.subgoals
        return {
            "subgoals": result.subgoals,
            "assumptions": result.assumptions,
            "ordered_node_list": [
                {
                    "name": node.name,
                    "type": node.type.value,
                    "timeout_ms": node.timeout_ms,
                }
                for node in result.nodes
            ],
        }

    async def _run_summary_node(self, context: dict[str, Any]) -> dict[str, Any]:
        executed: list[FlowRunNodeRecord] = context.get("executed_nodes", [])
        return {
            "requested_task": context.get("instruction", ""),
            "planned_steps": [p.name for p in context.get("plan_nodes", [])],
            "step_outcomes": [
                {
                    "name": node.name,
                    "type": node.type.value,
                    "status": node.status.value,
                }
                for node in executed
            ],
            "deviations": context.get("deviations", []),
            "observations": context.get("observations", []),
        }

    # ── Legacy node handlers (backward compatibility) ────────────────────────

    async def _run_er_node(
        self, plan: NodePlan, context: dict[str, Any],
    ) -> tuple[dict[str, Any], NodeResultStatus]:
        camera = self._executors.get("camera")
        image_bytes = None
        if camera and hasattr(camera, "get_snapshot_jpeg"):
            image_bytes = camera.get_snapshot_jpeg(quality=70)

        subgoal = plan.payload.get("subgoal", {})
        prompt = f"""You are Gemini Robotics ER.
Return STRICT JSON with keys:
- feasibility: "SUCCESS" | "FAILURE"
- reasoning: short string
- object_localization: object with x,y,width,height,confidence (pixel coords)
- focus_regions: array of objects with x,y,width,height,label
- xy_waypoints: array of [x,y] points in normalized 0..1 coordinates

Subgoal: {subgoal}
Current context: {context.get('cell_state', {})}
Return JSON only.
"""
        response = await self._gemini.analyze_er(prompt=prompt, image_bytes=image_bytes)

        feasibility = str(response.get("feasibility", "FAILURE")).upper()
        bbox = response.get("object_localization") or {}
        waypoints = response.get("xy_waypoints") or []
        focus_regions = response.get("focus_regions") or []

        artifacts: dict[str, Any] = {
            "feasibility": feasibility,
            "reasoning": response.get("reasoning", ""),
            "object_localization": bbox,
            "focus_regions": focus_regions,
            "xy_waypoints": waypoints,
            "annotated_image": None,
        }

        if image_bytes:
            artifacts["annotated_image"] = base64.b64encode(image_bytes).decode("utf-8")

        goal_idx = plan.payload.get("goal_index")
        context.setdefault("er_results", {})[goal_idx] = artifacts

        if feasibility != "SUCCESS":
            return artifacts, NodeResultStatus.FAILURE
        return artifacts, NodeResultStatus.SUCCESS

    async def _run_depth_node(
        self, plan: NodePlan, context: dict[str, Any],
    ) -> tuple[dict[str, Any], NodeResultStatus]:
        subgoal = plan.payload.get("subgoal", {})
        target_zone = str(subgoal.get("target_zone") or "default")
        object_class = str(subgoal.get("object_class") or "default")

        zones = self._safe_z.get("zones", {})
        default_zone = zones.get("default", {})
        zone_cfg = zones.get(target_zone, default_zone)
        class_cfg = (zone_cfg.get("objects") or {}).get(object_class, zone_cfg.get("default", {}))

        min_z = float(self._safe_z.get("global_limits", {}).get("min_z", 0.05))
        max_z = float(self._safe_z.get("global_limits", {}).get("max_z", 0.45))
        margin = float(self._safe_z.get("robot", {}).get("safety_margin_z", 0.03))

        grasp_z = float(class_cfg.get("grasp_z", zone_cfg.get("grasp_z", 0.12)))
        place_z = float(class_cfg.get("place_z", zone_cfg.get("place_z", 0.16)))
        grasp_z = min(max(grasp_z, min_z), max_z)
        place_z = min(max(place_z, min_z), max_z)

        er_result = context.get("er_results", {}).get(plan.payload.get("goal_index"), {})
        xy_waypoints = er_result.get("xy_waypoints") or [[0.5, 0.5]]
        x_norm, y_norm = xy_waypoints[0]

        workspace = self._safe_z.get("workspace", {})
        x_min = float(workspace.get("x_min", -0.25))
        x_max = float(workspace.get("x_max", 0.25))
        y_min = float(workspace.get("y_min", -0.35))
        y_max = float(workspace.get("y_max", 0.35))

        x = x_min + (x_max - x_min) * float(x_norm)
        y = y_min + (y_max - y_min) * float(y_norm)

        grasp_pose = [x, y, grasp_z, 0.0, 3.14, 0.0]
        place_pose = [x, y, place_z, 0.0, 3.14, 0.0]
        approach_pose = [x, y, min(place_z + margin, max_z), 0.0, 3.14, 0.0]

        artifacts = {
            "mode": "dummy_safe_z_table",
            "target_zone": target_zone,
            "object_class": object_class,
            "grasp_pose": grasp_pose,
            "place_pose": place_pose,
            "approach_pose": approach_pose,
            "z_clamp": {"min": min_z, "max": max_z},
        }

        context.setdefault("depth_results", {})[plan.payload.get("goal_index")] = artifacts
        return artifacts, NodeResultStatus.SUCCESS

    async def _run_robot_node(
        self, plan: NodePlan, context: dict[str, Any],
    ) -> tuple[dict[str, Any], NodeResultStatus]:
        robot = self._executors.get("robot")
        if robot is None or not hasattr(robot, "is_ready"):
            return {"error": "Robot executor unavailable"}, NodeResultStatus.FAILURE

        if not robot.is_ready():
            return {"error": "Robot executor not ready"}, NodeResultStatus.FAILURE

        goal_idx = plan.payload.get("goal_index")
        depth = context.get("depth_results", {}).get(goal_idx)
        if not depth:
            return {"error": "Missing depth pose for execution"}, NodeResultStatus.FAILURE

        target_pose = depth.get("approach_pose") or depth.get("place_pose")

        if not hasattr(robot, "move_linear"):
            return {"error": "Robot executor missing move_linear"}, NodeResultStatus.FAILURE

        success = await robot.move_linear(
            pose=target_pose,
            acceleration=0.5,
            velocity=0.15,
            timeout=30.0,
        )

        artifacts = {
            "target_pose": target_pose,
            "motion_status": "completed" if success else "failed",
        }
        context.setdefault("robot_results", {})[goal_idx] = artifacts

        if success:
            return artifacts, NodeResultStatus.SUCCESS
        return artifacts, NodeResultStatus.FAILURE

    async def _run_live_node(
        self, plan: NodePlan, context: dict[str, Any],
    ) -> tuple[dict[str, Any], NodeResultStatus]:
        """Standalone live node execution."""
        prompt = (
            "Provide concise real-time robotic action commentary (<= 2 lines) and mention any anomalies."
        )
        text = await self._gemini.live_commentary(prompt)
        audio_b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        artifacts = {
            "commentary": text,
            "audio_chunk": audio_b64,
            "focus_regions": context.get("er_results", {}).get(plan.payload.get("goal_index"), {}).get("focus_regions", []),
        }
        self._emit(
            "orchestrator_live_chunk",
            {
                "flow_id": context["flow_id"],
                "node_name": plan.name,
                "text": text,
                "audio_chunk": audio_b64,
                "focus_regions": artifacts["focus_regions"],
            },
        )
        return artifacts, NodeResultStatus.SUCCESS

    async def _run_live_during_robot(
        self,
        live_plan: NodePlan,
        context: dict[str, Any],
        robot_task: "asyncio.Task[tuple[dict[str, Any], NodeResultStatus]]",
    ) -> FlowRunNodeRecord:
        start = time.time()
        self._emit(
            "orchestrator_node_started",
            {
                "flow_id": context["flow_id"],
                "node_name": live_plan.name,
                "node_type": live_plan.type.value,
            },
        )

        snippets: list[dict[str, Any]] = []
        focus_regions = context.get("er_results", {}).get(live_plan.payload.get("goal_index"), {}).get("focus_regions", [])

        while not robot_task.done():
            prompt = (
                "You are narrating a live factory robot motion. "
                "Highlight expected behavior and anomalies in one short sentence."
            )
            try:
                text = await self._gemini.live_commentary(prompt)
            except Exception as exc:
                text = f"Live commentary error: {exc}"

            audio_b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
            snippet = {
                "timestamp": time.time(),
                "text": text,
                "audio_chunk": audio_b64,
                "focus_regions": focus_regions,
            }
            snippets.append(snippet)
            self._emit(
                "orchestrator_live_chunk",
                {
                    "flow_id": context["flow_id"],
                    "node_name": live_plan.name,
                    **snippet,
                },
            )
            await asyncio.sleep(1.0)

        robot_artifacts, robot_status = await robot_task
        final_note = "Motion completed successfully." if robot_status == NodeResultStatus.SUCCESS else "Motion ended with failure."
        final_audio = base64.b64encode(final_note.encode("utf-8")).decode("utf-8")
        snippets.append(
            {
                "timestamp": time.time(),
                "text": final_note,
                "audio_chunk": final_audio,
                "focus_regions": focus_regions,
            }
        )
        self._emit(
            "orchestrator_live_chunk",
            {
                "flow_id": context["flow_id"],
                "node_name": live_plan.name,
                "timestamp": time.time(),
                "text": final_note,
                "audio_chunk": final_audio,
                "focus_regions": focus_regions,
            },
        )

        end = time.time()
        status = NodeResultStatus.SUCCESS if robot_status == NodeResultStatus.SUCCESS else NodeResultStatus.FAILURE
        record = FlowRunNodeRecord(
            name=live_plan.name,
            type=live_plan.type,
            status=status,
            start_time=start,
            end_time=end,
            timeout_ms=live_plan.timeout_ms,
            artifacts={
                "snippets": snippets,
                "linked_robot_status": robot_status.value,
                "focus_regions": focus_regions,
            },
        )

        self._emit(
            "orchestrator_node_finished",
            {
                "flow_id": context["flow_id"],
                "node_name": live_plan.name,
                "node_type": live_plan.type.value,
                "status": status.value,
                "duration_ms": int((end - start) * 1000),
                "artifacts": record.artifacts,
            },
        )
        return record

    async def _run_jog_joints_node(
        self, plan: NodePlan, context: dict[str, Any],
    ) -> tuple[dict[str, Any], NodeResultStatus]:
        """Execute a legacy jog-joints command."""
        import math

        robot = self._executors.get("robot")
        if robot is None or not hasattr(robot, "is_ready"):
            return {"error": "Robot executor unavailable"}, NodeResultStatus.FAILURE
        if not robot.is_ready():
            return {"error": "Robot executor not ready"}, NodeResultStatus.FAILURE

        offsets_deg = plan.payload.get("offsets_deg", [0, 0, 0, 0, 0, 0])
        velocity = float(plan.payload.get("velocity", 0.5))
        acceleration = float(plan.payload.get("acceleration", 0.5))

        current_deg = robot.get_joint_positions_deg()
        if current_deg is None:
            return {"error": "Cannot read current joint positions"}, NodeResultStatus.FAILURE

        target_deg = [cur + off for cur, off in zip(current_deg, offsets_deg)]

        for i, d in enumerate(target_deg):
            if not -360.0 <= d <= 360.0:
                return {
                    "error": f"Joint {i} target {d:.1f} deg outside [-360, 360]",
                }, NodeResultStatus.FAILURE

        target_rad = [math.radians(d) for d in target_deg]
        tolerance_rad = math.radians(1.0)

        success = await robot.jog_joint(
            target_rad=target_rad,
            acceleration=acceleration,
            velocity=velocity,
            tolerance_rad=tolerance_rad,
        )

        artifacts = {
            "instruction": plan.payload.get("instruction", ""),
            "previous_deg": [round(d, 2) for d in current_deg],
            "offsets_deg": offsets_deg,
            "target_deg": [round(d, 2) for d in target_deg],
            "motion_status": "completed" if success else "failed",
        }

        context.setdefault("robot_results", {})["jog"] = artifacts

        if success:
            return artifacts, NodeResultStatus.SUCCESS
        return artifacts, NodeResultStatus.FAILURE

    async def _run_verification_node(
        self, plan: NodePlan, context: dict[str, Any],
    ) -> tuple[dict[str, Any], NodeResultStatus]:
        goal_idx = plan.payload.get("goal_index")
        robot_result = context.get("robot_results", {}).get(goal_idx, {})
        motion_status = robot_result.get("motion_status")

        if motion_status == "completed":
            status = "SUCCESS"
            node_status = NodeResultStatus.SUCCESS
        elif motion_status == "failed":
            status = "FAILURE"
            node_status = NodeResultStatus.FAILURE
        else:
            status = "PARTIAL"
            node_status = NodeResultStatus.FAILURE

        artifacts = {
            "classification": status,
            "reasoning": "Verification inferred from robot completion telemetry in v1.",
            "goal_index": goal_idx,
        }
        return artifacts, node_status
