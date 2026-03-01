"""Planner for converting natural language goals into primitive skill sequences.

Supports two modes:
  1. STATIC — simple tasks (jog, single pick, queries) get a one-shot plan.
  2. AGENTIC — multi-step/dynamic tasks (sort, segregate, clear) use
     an observe-reason-act loop where `plan_next_step()` returns one
     micro-task per iteration until the goal is achieved.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .gemini_client import OrchestratorGeminiClient
from .schemas import MicroPlan, NodePlan, NodeType, PlanResult

logger = logging.getLogger(__name__)

NON_ACTIONABLE_TASK_MESSAGE = (
    "No actionable task detected. Please provide an instruction such as "
    "'Pick the red box from Zone A and place it in Zone B' or 'What objects are on the table?'."
)

# ── Skill catalog for the Gemini prompt ──────────────────────────────────────
try:
    from skills.primitives import PRIMITIVE_SKILL_CATALOG
except ImportError:
    PRIMITIVE_SKILL_CATALOG = []

# ── Intent detection ─────────────────────────────────────────────────────────
ACTION_VERBS = (
    "pick", "place", "move", "transfer", "convey", "put", "grab", "stack",
    "sort", "load", "unload", "palletize", "label", "jog", "rotate", "nudge",
    "check", "inspect", "verify", "scan", "look", "find", "detect", "count",
    "read", "identify", "describe", "what", "where", "how", "is", "are",
    "open", "close", "grip", "release", "suction", "wait", "pause",
    "home", "stow", "calibrate", "segregate", "separate", "organize", "clear",
    "remove", "collect", "gather", "arrange", "distribute",
    "capture", "photograph", "picture", "snapshot", "image", "photo",
    "narrate", "commentary", "commentate", "stream", "live",
    "analyze", "analyse", "observe", "watch", "see", "show",
)
ACTION_VERB_PATTERN = re.compile(r"\b(" + "|".join(ACTION_VERBS) + r")\b", re.IGNORECASE)

# Words that indicate the task involves multiple objects / iterations / unknown count
AGENTIC_INDICATORS = re.compile(
    r"\b(?:all|every|each|segregat|separat|sort|organiz|clear|distribut|collect|gather"
    r"|arrang|batch|multiple|several|various|remaining|until|repeat|keep|continuous)\w*\b",
    re.IGNORECASE,
)

_JOG_PATTERN = re.compile(
    r"\b(?:jog|rotate|nudge)\b.*\b(?:joint|axis|j[0-5]|degree|deg)\b"
    r"|\b(?:move|turn)\b.*\b(?:joint|axis|j[0-5])\b.*\b(?:degree|deg|°)\b"
    r"|\b(?:move|turn)\b.*\bevery\s+joint\b",
    re.IGNORECASE,
)

# ── NodeType mapping ─────────────────────────────────────────────────────────
SKILL_TO_NODE_TYPE: dict[str, NodeType] = {
    "capture_image": NodeType.CAPTURE_IMAGE,
    "analyze_scene": NodeType.ANALYZE_SCENE,
    "estimate_grasp_pose": NodeType.ESTIMATE_GRASP_POSE,
    "plan_trajectory": NodeType.PLAN_TRAJECTORY,
    "llm_reason": NodeType.LLM_REASON,
    "live_narrate": NodeType.LIVE_NARRATE,
    "move_to_pose": NodeType.MOVE_TO_POSE,
    "execute_xy_action": NodeType.EXECUTE_XY_ACTION,
    "move_joints": NodeType.MOVE_JOINTS,
    "jog_joints": NodeType.JOG_JOINTS,
    "get_robot_state": NodeType.GET_ROBOT_STATE,
    "suction_on": NodeType.SUCTION_ON,
    "suction_off": NodeType.SUCTION_OFF,
    "set_digital_output": NodeType.SET_DIGITAL_OUTPUT,
    "wait_digital_input": NodeType.WAIT_DIGITAL_INPUT,
    "wait": NodeType.WAIT,
    "verify_outcome": NodeType.VERIFY_OUTCOME,
}


def _build_skill_catalog_text() -> str:
    """Format the skill catalog as a concise reference for the planning prompt."""
    lines: list[str] = []
    for s in PRIMITIVE_SKILL_CATALOG:
        params_str = json.dumps(s.get("params", {}))
        line = (
            f"  - {s['name']} [{s['layer']}]: {s['description']}  "
            f"Params: {params_str}  Returns: {s.get('returns', 'success')}"
        )
        use_when = s.get("use_when")
        avoid_when = s.get("avoid_when")
        if use_when:
            line += f"  Use when: {use_when}"
        if avoid_when:
            line += f"  Avoid when: {avoid_when}"
        lines.append(line)
    return "\n".join(lines)


SKILL_CATALOG_TEXT = _build_skill_catalog_text()
SKILL_NAMES = [s["name"] for s in PRIMITIVE_SKILL_CATALOG if isinstance(s.get("name"), str)]


class OrchestratorPlanner:
    """Gemini-backed planner — supports static one-shot and agentic iterative modes."""

    def __init__(self, gemini: OrchestratorGeminiClient):
        self._gemini = gemini

    # ═══════════════════════════════════════════════════════════════════════
    #  Static planning (one-shot for simple tasks)
    # ═══════════════════════════════════════════════════════════════════════

    async def plan(self, instruction: str, cell_state: dict[str, Any]) -> PlanResult:
        """Create initial plan.  Decides static vs agentic based on intent."""
        if not await self.should_orchestrate(instruction, cell_state):
            raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)

        # Fast-path: jog commands → always static
        if self._is_jog_command(instruction):
            return await self._plan_jog(instruction)

        # Decide mode
        is_agentic = self._needs_agentic_loop(instruction)

        if is_agentic:
            # For agentic tasks, the initial plan is lightweight —
            # just inform the engine to use the observe-reason-act loop.
            return PlanResult(
                subgoals=[{"id": "agentic_loop", "description": instruction}],
                assumptions=["Task requires dynamic multi-step execution (agentic loop)"],
                nodes=[],  # No static nodes — engine drives the loop
                is_agentic=True,
            )

        # Static plan via Gemini
        prompt = f"""You are a robotics orchestrator planner. Decompose the goal into
an ordered sequence of PRIMITIVE SKILLS.

## Available Primitive Skills
{SKILL_CATALOG_TEXT}

## Rules
1. Return STRICT JSON with keys:
   - "assumptions": array of string
   - "skills": array of {{"skill": str, "params": object, "description": str}}
   - Allowed skill names ONLY: {json.dumps(SKILL_NAMES)}
2. Use the minimum necessary skill calls.
3. For XY planar motion tasks, ALWAYS use Gemini ER for trajectory planning and
   execution via:
   capture_image -> analyze_scene -> plan_trajectory(task="<describe the motion>") ->
   execute_xy_action -> verify_outcome
   execute_xy_action must consume ER trajectory output and keeps Z fixed.
   The plan_trajectory skill uses Gemini Robotics-ER 1.5 to generate optimal trajectory
   waypoints overlaid on the camera image.  It returns an annotated image showing the
   planned path — this image is displayed to the operator.
4. For pick-and-place specifically:
   capture_image -> analyze_scene -> plan_trajectory(task="pick <object> and place at <target>") ->
   estimate_grasp_pose -> move_to_pose (approach) -> suction_on -> move_to_pose (lift) ->
   move_to_pose (transit) -> move_to_pose (place) -> suction_off -> verify_outcome
5. For perception-only queries: capture_image -> analyze_scene -> llm_reason
6. Always end manipulation tasks with verify_outcome.
7. After significant motion steps, add live_narrate for real-time commentary (engine
   runs them concurrently with the preceding motion).
8. plan_trajectory is the ONLY way to plan motion paths — it uses Gemini ER spatial
   reasoning to overlay trajectories on the image.  Do NOT hardcode poses.
9. For non-string params (bbox, pose arrays, booleans, numbers), provide concrete JSON values.
   Never emit template placeholders like "{{...}}".
10. Never call execute_xy_action before plan_trajectory in the same plan.
11. Return JSON only.

## Instruction
{instruction!r}

## Cell State
{json.dumps(cell_state, default=str)}
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception as exc:
            logger.warning("Gemini planning failed (%s), using fallback", exc)
            raw = self._fallback_plan(instruction)

        skills = raw.get("skills") or []
        assumptions = raw.get("assumptions") or []

        if not isinstance(skills, list) or len(skills) == 0:
            skills = self._fallback_plan(instruction).get("skills", [])

        nodes = self._skills_to_nodes(skills)
        subgoals = [
            {"id": f"step_{i+1}", "skill": s.get("skill"), "description": s.get("description", "")}
            for i, s in enumerate(skills)
        ]
        return PlanResult(subgoals=subgoals, assumptions=assumptions, nodes=nodes, is_agentic=False)

    # ═══════════════════════════════════════════════════════════════════════
    #  Agentic planning (one micro-task per call, looped by engine)
    # ═══════════════════════════════════════════════════════════════════════

    async def plan_next_step(
        self,
        goal: str,
        scene_analysis: dict[str, Any],
        history: list[dict[str, Any]],
        cell_state: dict[str, Any],
        iteration: int,
    ) -> MicroPlan:
        """Decide the NEXT single action given current scene and history.

        Called repeatedly by the engine in the observe-reason-act loop.
        Returns MicroPlan with either skills for one micro-task or task_complete=True.
        """
        history_summary = self._summarize_history(history)

        prompt = f"""You are an intelligent robotics agent executing a multi-step task.
You must decide the NEXT SINGLE ACTION based on the CURRENT scene and what you've already done.

## Goal
{goal!r}

## Current Scene Analysis (from camera + VLM, captured THIS iteration)
{json.dumps(scene_analysis, default=str)}

## Execution History (what has been done so far)
{history_summary}

## Cell State
{json.dumps(cell_state, default=str)}

## Iteration
{iteration}

## Available Primitive Skills
{SKILL_CATALOG_TEXT}

## Few-shot Patterns (guidance, not strict templates)
- Perception query:
  Goal: "Count blue boxes"
  Skills: capture_image -> analyze_scene(query="count blue boxes") -> llm_reason(prompt="answer count")

- One-object manipulation:
  Goal: "Pick red block and place in Bin A"
  Skills: plan_trajectory(task="pick up the red block and move it to Bin A", object_label="red block") ->
          estimate_grasp_pose(bbox from scene analysis) -> move_to_pose(approach) ->
          live_narrate(prompt="Approaching target") -> move_to_pose(descend) ->
          suction_on -> move_to_pose(lift) -> live_narrate(prompt="Lifting object") ->
          move_to_pose(target) -> live_narrate(prompt="Placing in bin") ->
          suction_off -> verify_outcome

- XY-only execution:
  Goal: "Move in a straight XY path from source to destination without changing height"
  Skills: capture_image -> plan_trajectory(task="<xy motion task>") -> execute_xy_action -> verify_outcome
  NOTE: execute_xy_action is XY only and keeps Z fixed.

- Trajectory visualization:
  Goal: "Show me how you would move the pen to the organizer"
  Skills: capture_image -> plan_trajectory(task="move the pen to the organizer", object_label="pen")
  NOTE: plan_trajectory returns an annotated image with trajectory overlaid — output this to the user.

- Failure-aware iteration:
  If previous grasp failed, choose another object or adjust approach height/grasp point before retrying.

## Rules
1. Return STRICT JSON with these keys:
   - "task_complete": bool — true ONLY if the ENTIRE goal is achieved (all objects handled, etc.)
   - "reasoning": string — explain what you see in the scene and why you chose this action
   - "scene_summary": string — brief description of current scene state
   - "progress": {{"completed": int, "estimated_remaining": int, "notes": string}}
   - "skills": array of {{"skill": str, "params": object, "description": str}}

2. If the task IS complete (nothing left to do), set "task_complete": true and "skills": []

3. If the task is NOT complete, plan EXACTLY ONE logical action (e.g., pick ONE object and place it).
   For manipulation, ALWAYS use plan_trajectory first to plan the motion via Gemini ER:
   plan_trajectory(task="<motion description>") -> estimate_grasp_pose ->
   move_to_pose (approach) -> move_to_pose (descend) ->
   suction_on -> move_to_pose (lift) -> move_to_pose (target) -> suction_off
   For XY-only planar moves, use:
   plan_trajectory(task="<xy motion description>") -> execute_xy_action -> verify_outcome
4. Use the CURRENT scene analysis for positions — do NOT reuse positions from history.

5. Choose the most efficient next action (nearest object, shortest path, etc.)

6. If a previous action failed, adapt: try a different object or approach.

7. The "params" must include actual values from the scene analysis (bounding boxes, positions).

8. Return JSON only — no markdown, no explanation outside the JSON.
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception as exc:
            logger.warning("Gemini plan_next_step failed (%s), using fallback", exc)
            return self._fallback_micro_plan(goal, scene_analysis, history, iteration)

        return MicroPlan(
            task_complete=bool(raw.get("task_complete", False)),
            reasoning=str(raw.get("reasoning", "")),
            skills=raw.get("skills") or [],
            progress=raw.get("progress") or {},
            scene_summary=str(raw.get("scene_summary", "")),
        )

    def micro_plan_to_nodes(self, micro_plan: MicroPlan, iteration: int) -> list[NodePlan]:
        """Convert a MicroPlan's skills into executable NodePlan objects."""
        return self._skills_to_nodes(micro_plan.skills, prefix=f"iter{iteration}")

    # ═══════════════════════════════════════════════════════════════════════
    #  Replanning
    # ═══════════════════════════════════════════════════════════════════════

    async def replan(
        self,
        instruction: str,
        previous_subgoals: list[dict[str, Any]],
        note: str,
        cell_state: dict[str, Any],
    ) -> PlanResult:
        """Regenerate plan after clarification or goal change."""
        prompt = f"""You are replanning a robotics task after failure or goal change.

## Available Primitive Skills
{SKILL_CATALOG_TEXT}

## Context
Original instruction: {instruction!r}
Operator note: {note!r}
Previous steps: {json.dumps(previous_subgoals, default=str)}
Cell state: {json.dumps(cell_state, default=str)}

## Rules
- Return STRICT JSON: {{"assumptions": [], "skills": []}}
- Each skill: {{"skill": str, "params": object, "description": str}}
- Return JSON only.
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception as exc:
            logger.warning("Gemini replan failed (%s), using fallback", exc)
            raw = self._fallback_plan(instruction)

        skills = raw.get("skills") or []
        assumptions = raw.get("assumptions") or []
        if not isinstance(skills, list) or len(skills) == 0:
            if not self._looks_like_robot_task(instruction):
                raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)
            skills = self._fallback_plan(instruction).get("skills", [])

        nodes = self._skills_to_nodes(skills)
        subgoals = [
            {"id": f"step_{i+1}", "skill": s.get("skill"), "description": s.get("description", "")}
            for i, s in enumerate(skills)
        ]
        return PlanResult(subgoals=subgoals, assumptions=assumptions, nodes=nodes)

    # ═══════════════════════════════════════════════════════════════════════
    #  Intent detection
    # ═══════════════════════════════════════════════════════════════════════

    async def should_orchestrate(self, instruction: str, cell_state: dict[str, Any]) -> bool:
        """Model-based intent router: decide if this message should trigger orchestration."""
        text = (instruction or "").strip()
        if not text:
            return False

        prompt = f"""You are an intent router for a robotics control UI.
Decide whether the message should trigger robot orchestration or be answered conversationally by the cell manager.

Return STRICT JSON only:
{{"route": "ORCHESTRATE" | "CELL_MANAGER", "reason": "short reason"}}

Routing rules:
- ORCHESTRATE: The user asks for ANY of these:
  * Physical robot action (pick, place, move, jog)
  * Perception tasks (capture image, take a picture, analyze scene, detect objects)
  * Live commentary or narration of the cell/workspace (uses Gemini Live + camera)
  * Visual questions about what's in the scene
  * Any task that involves the camera, robot, or AI skills
- CELL_MANAGER: The user asks ONLY about:
  * System status, diagnostics, health checks
  * Connectivity or configuration issues
  * General conversation unrelated to robot/camera tasks

IMPORTANT: "live commentary", "narrate", "describe the cell", "what do you see",
"take a picture", "capture image", "stream", "observe" are ALL orchestration tasks.

User message: {text!r}
Cell state: {json.dumps(cell_state, default=str)}
"""
        try:
            raw = await self._gemini.generate_json(prompt)
            route = str(raw.get("route", "")).strip().upper()
            if route == "ORCHESTRATE":
                return True
            if route == "CELL_MANAGER":
                return False
        except Exception as exc:
            logger.warning("Gemini intent routing failed (%s), using heuristic fallback", exc)

        # Conservative fallback if the classifier is unavailable.
        return self._looks_like_robot_task(text)

    @staticmethod
    def _looks_like_robot_task(instruction: str) -> bool:
        return bool(ACTION_VERB_PATTERN.search((instruction or "").lower()))

    @classmethod
    def looks_like_robot_task(cls, instruction: str) -> bool:
        return cls._looks_like_robot_task(instruction)

    @staticmethod
    def _is_jog_command(instruction: str) -> bool:
        return bool(_JOG_PATTERN.search(instruction or ""))

    @staticmethod
    def _needs_agentic_loop(instruction: str) -> bool:
        """Detect tasks that require dynamic multi-step iteration."""
        return bool(AGENTIC_INDICATORS.search(instruction or ""))

    # ═══════════════════════════════════════════════════════════════════════
    #  Jog planning
    # ═══════════════════════════════════════════════════════════════════════

    async def _plan_jog(self, instruction: str) -> PlanResult:
        prompt = f"""You are a robotics joint-jog parser.
The robot has 6 joints: j0 (base), j1 (shoulder), j2 (elbow), j3 (wrist1), j4 (wrist2), j5 (wrist3).
Return STRICT JSON: {{"offsets_deg": [6 floats], "velocity": float 0.1-2.0, "acceleration": float 0.1-2.0}}
Instruction: {instruction!r}
Clamp offsets to [-45, 45]. Return JSON only.
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception:
            raw = self._fallback_jog_parse(instruction)

        offsets = raw.get("offsets_deg", [0, 0, 0, 0, 0, 0])
        if not isinstance(offsets, list) or len(offsets) != 6:
            offsets = [0, 0, 0, 0, 0, 0]
        offsets = [max(-45, min(45, float(o))) for o in offsets]

        velocity = float(raw.get("velocity", 0.5))
        acceleration = float(raw.get("acceleration", 0.5))

        skills = [{"skill": "jog_joints", "params": {"offsets_deg": offsets, "velocity": velocity, "acceleration": acceleration}, "description": instruction}]
        nodes = self._skills_to_nodes(skills)
        return PlanResult(
            subgoals=[{"id": "jog_1", "skill": "jog_joints", "description": instruction}],
            assumptions=[f"Jog offsets: {offsets} deg"],
            nodes=nodes,
        )

    @staticmethod
    def _fallback_jog_parse(instruction: str) -> dict[str, Any]:
        lower = instruction.lower()
        deg_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:degree|deg|°)", lower)
        deg_val = float(deg_match.group(1)) if deg_match else 5.0
        deg_val = max(-45, min(45, deg_val))

        if re.search(r"\b(?:every|all)\s+joint", lower):
            return {"offsets_deg": [deg_val] * 6, "velocity": 0.5, "acceleration": 0.5}

        offsets = [0.0] * 6
        for m in re.finditer(r"\bj(?:oint)?\s*(\d)", lower):
            idx = int(m.group(1))
            if 0 <= idx <= 5:
                offsets[idx] = deg_val

        if all(o == 0 for o in offsets):
            offsets = [deg_val] * 6
        return {"offsets_deg": offsets, "velocity": 0.5, "acceleration": 0.5}

    # ═══════════════════════════════════════════════════════════════════════
    #  Fallbacks
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _fallback_plan(instruction: str) -> dict[str, Any]:
        lower = (instruction or "").lower()
        # Live commentary / narration
        if any(w in lower for w in ("commentary", "commentat", "narrat", "live", "stream")):
            return {
                "assumptions": ["Fallback: live commentary task"],
                "skills": [
                    {"skill": "capture_image", "params": {}, "description": "Capture current scene"},
                    {"skill": "analyze_scene", "params": {"query": "Describe everything visible in the robotic cell workspace"}, "description": "Analyze scene for commentary context"},
                    {"skill": "live_narrate", "params": {"prompt": instruction, "include_scene_context": True}, "description": "Generate live commentary"},
                ],
            }
        if any(w in lower for w in ("what", "where", "how many", "describe", "check", "inspect", "scan", "look", "find", "detect", "count", "read", "identify")):
            return {
                "assumptions": ["Fallback: perception-only task"],
                "skills": [
                    {"skill": "capture_image", "params": {}, "description": "Capture scene"},
                    {"skill": "analyze_scene", "params": {"query": instruction}, "description": "Analyze with VLM"},
                    {"skill": "llm_reason", "params": {"prompt": f"Summarize: {instruction}", "response_format": "text"}, "description": "Summarize"},
                ],
            }
        return {
            "assumptions": ["Fallback: generic pick-and-place"],
            "skills": [
                {"skill": "capture_image", "params": {}, "description": "Capture scene"},
                {"skill": "analyze_scene", "params": {"query": f"Locate object for: {instruction}"}, "description": "Find target"},
                {"skill": "plan_trajectory", "params": {"task": instruction, "num_points": 15}, "description": "Plan trajectory with Gemini ER"},
                {"skill": "estimate_grasp_pose", "params": {"bbox": {"x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1}, "object_class": "object"}, "description": "Estimate grasp"},
                {"skill": "move_to_pose", "params": {"pose": [0, 0, 0.3, 0, 3.14, 0], "motion_type": "joint"}, "description": "Approach"},
                {"skill": "suction_on", "params": {}, "description": "Grasp"},
                {"skill": "move_to_pose", "params": {"pose": [0, 0, 0.15, 0, 3.14, 0], "motion_type": "linear"}, "description": "Place"},
                {"skill": "suction_off", "params": {}, "description": "Release"},
                {"skill": "verify_outcome", "params": {"expected_state": instruction}, "description": "Verify"},
            ],
        }

    @staticmethod
    def _fallback_micro_plan(
        goal: str,
        scene_analysis: dict[str, Any],
        history: list[dict[str, Any]],
        iteration: int,
    ) -> MicroPlan:
        """Deterministic fallback when Gemini fails during agentic loop."""
        if iteration > 20:
            return MicroPlan(
                task_complete=True,
                reasoning="Safety limit: exceeded 20 iterations, stopping.",
                progress={"completed": iteration, "estimated_remaining": 0, "notes": "safety stop"},
            )

        objects = scene_analysis.get("objects", [])
        if not isinstance(objects, list):
            objects = []
        if not objects:
            return MicroPlan(
                task_complete=True,
                reasoning="No objects detected in current scene. Assuming task is complete.",
                scene_summary="No objects detected.",
                progress={"completed": iteration - 1, "estimated_remaining": 0, "notes": "fallback completion"},
            )

        first_obj = objects[0] if isinstance(objects[0], dict) else {}
        bbox = first_obj.get("bbox")
        if not isinstance(bbox, dict):
            bbox = {"x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1}
        object_label = str(first_obj.get("label", "object"))

        return MicroPlan(
            task_complete=False,
            reasoning=f"Gemini unavailable — fallback pick attempt (iteration {iteration})",
            skills=[
                {"skill": "plan_trajectory", "params": {"task": f"pick {object_label} and move to target", "object_label": object_label, "num_points": 15}, "description": f"Plan trajectory for {object_label} with Gemini ER"},
                {"skill": "estimate_grasp_pose", "params": {"bbox": bbox, "object_class": object_label}, "description": f"Estimate grasp for {object_label}"},
                {"skill": "move_to_pose", "params": {"pose": [0.0, 0.0, 0.25, 0.0, 3.14, 0.0], "motion_type": "joint"}, "description": "Approach target"},
                {"skill": "move_to_pose", "params": {"pose": [0.0, 0.0, 0.12, 0.0, 3.14, 0.0], "motion_type": "linear"}, "description": "Descend to grasp height"},
                {"skill": "suction_on", "params": {}, "description": "Pick object"},
                {"skill": "move_to_pose", "params": {"pose": [0.0, 0.0, 0.25, 0.0, 3.14, 0.0], "motion_type": "linear"}, "description": "Lift object"},
                {"skill": "suction_off", "params": {}, "description": "Release object"},
            ],
            progress={"completed": iteration - 1, "estimated_remaining": -1, "notes": "fallback mode"},
            scene_summary=str(scene_analysis.get("answer", "")),
        )

    @staticmethod
    def _summarize_history(history: list[dict[str, Any]]) -> str:
        """Build a concise text summary of execution history for the Gemini prompt."""
        if not history:
            return "No actions taken yet."

        lines: list[str] = []
        for i, entry in enumerate(history[-10:], start=1):  # Last 10 entries max
            status = entry.get("status", "UNKNOWN")
            desc = entry.get("description", entry.get("name", f"step_{i}"))
            error = entry.get("error")
            if isinstance(error, str) and error:
                lines.append(f"  {i}. [{status}] {desc} (error={error})")
            else:
                lines.append(f"  {i}. [{status}] {desc}")

        total = len(history)
        if total > 10:
            lines.insert(0, f"  (showing last 10 of {total} actions)")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════════════
    #  Skill → NodePlan conversion
    # ═══════════════════════════════════════════════════════════════════════

    def _skills_to_nodes(self, skills: list[dict[str, Any]], prefix: str = "step") -> list[NodePlan]:
        nodes: list[NodePlan] = []
        for idx, skill_dict in enumerate(skills, start=1):
            skill_name = skill_dict.get("skill", "")
            node_type = SKILL_TO_NODE_TYPE.get(skill_name)
            if node_type is None:
                logger.warning("Unknown skill '%s' in plan, skipping", skill_name)
                continue

            timeout_ms = 30000
            if node_type in (NodeType.MOVE_TO_POSE, NodeType.EXECUTE_XY_ACTION, NodeType.MOVE_JOINTS):
                timeout_ms = 45000
            elif node_type in (NodeType.WAIT, NodeType.WAIT_DIGITAL_INPUT):
                timeout_ms = 60000
            elif node_type == NodeType.PLAN_TRAJECTORY:
                timeout_ms = 60000  # ER trajectory planning can take a while
            elif node_type in (NodeType.CAPTURE_IMAGE, NodeType.GET_ROBOT_STATE,
                               NodeType.SUCTION_ON, NodeType.SUCTION_OFF):
                timeout_ms = 10000

            nodes.append(NodePlan(
                name=f"{prefix}_{idx}_{skill_name}",
                type=node_type,
                payload={
                    "skill_name": skill_name,
                    "params": skill_dict.get("params", {}),
                    "description": skill_dict.get("description", ""),
                    "step_index": idx,
                    "step_count": len(skills),
                },
                timeout_ms=timeout_ms,
            ))

        # Append summary for static plans only (agentic loop adds summary at the end)
        if prefix == "step":
            nodes.append(NodePlan(name="summary", type=NodeType.SUMMARY_NODE, payload={}, timeout_ms=10000))

        return nodes

