"""Planner for converting natural language goals into primitive skill sequences.

Uses Gemini to decompose goals into ordered sequences of the 15 primitive skills.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .gemini_client import OrchestratorGeminiClient
from .schemas import NodePlan, NodeType, PlanResult

logger = logging.getLogger(__name__)

NON_ACTIONABLE_TASK_MESSAGE = (
    "No actionable task detected. Please provide an instruction such as "
    "'Pick the red box from Zone A and place it in Zone B' or 'What objects are on the table?'."
)

# ── Skill catalog for the Gemini prompt ──────────────────────────────────────
# Imported from the primitives package so the planner prompt always stays in sync.
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
    "home", "stow", "calibrate",
)
ACTION_VERB_PATTERN = re.compile(r"\b(" + "|".join(ACTION_VERBS) + r")\b", re.IGNORECASE)

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
    "llm_reason": NodeType.LLM_REASON,
    "live_narrate": NodeType.LIVE_NARRATE,
    "move_to_pose": NodeType.MOVE_TO_POSE,
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
        lines.append(
            f"  - {s['name']} [{s['layer']}]: {s['description']}  "
            f"Params: {params_str}  Returns: {s.get('returns', 'success')}"
        )
    return "\n".join(lines)


SKILL_CATALOG_TEXT = _build_skill_catalog_text()


class OrchestratorPlanner:
    """Gemini-backed planner that decomposes goals into primitive skill sequences."""

    def __init__(self, gemini: OrchestratorGeminiClient):
        self._gemini = gemini

    async def plan(self, instruction: str, cell_state: dict[str, Any]) -> PlanResult:
        """Create initial plan from raw instruction and current cell state."""
        if not self._looks_like_robot_task(instruction):
            raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)

        # Fast-path: jog commands
        if self._is_jog_command(instruction):
            return await self._plan_jog(instruction)

        prompt = f"""You are a robotics orchestrator planner. You must decompose a user goal into
an ordered sequence of PRIMITIVE SKILLS.

## Available Primitive Skills
{SKILL_CATALOG_TEXT}

## Rules
1. Return STRICT JSON with keys:
   - "assumptions": array of string assumptions you are making
   - "skills": array of objects, each with:
     - "skill": string (exact skill name from the list above)
     - "params": object (skill parameters — use sensible defaults when unknown)
     - "description": string (one-line explanation of what this step does)
2. Decompose the task into the minimum necessary skill calls.
3. For pick-and-place tasks, use this pattern:
   capture_image → analyze_scene → estimate_grasp_pose → move_to_pose (approach) →
   move_to_pose (grasp) → suction_on → move_to_pose (lift) → move_to_pose (target) →
   move_to_pose (place) → suction_off → move_to_pose (retract) → verify_outcome
4. For perception-only tasks (questions about the scene), use:
   capture_image → analyze_scene → llm_reason (summarize)
5. Always end manipulation tasks with verify_outcome.
6. Use move_to_pose with motion_type "joint" for large transit moves, "linear" for precise positioning.
7. Return JSON only — no markdown, no explanation.

## User Instruction
{instruction!r}

## Current Cell State
{json.dumps(cell_state, default=str)}
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception as exc:
            logger.warning("Gemini planning failed (%s), using fallback", exc)
            raw = self._fallback_plan(instruction)

        assumptions = raw.get("assumptions") or []
        skills = raw.get("skills") or []

        if not isinstance(skills, list) or len(skills) == 0:
            skills = self._fallback_plan(instruction).get("skills", [])

        nodes = self._skills_to_nodes(skills)
        subgoals = [
            {"id": f"step_{i+1}", "skill": s.get("skill"), "description": s.get("description", "")}
            for i, s in enumerate(skills)
        ]

        return PlanResult(subgoals=subgoals, assumptions=assumptions, nodes=nodes)

    async def replan(
        self,
        instruction: str,
        previous_subgoals: list[dict[str, Any]],
        note: str,
        cell_state: dict[str, Any],
    ) -> PlanResult:
        """Regenerate plan after clarification or goal change."""
        prompt = f"""You are replanning a robotics task after failure or goal modification.

## Available Primitive Skills
{SKILL_CATALOG_TEXT}

## Context
Original instruction: {instruction!r}
Operator note: {note!r}
Previous steps: {json.dumps(previous_subgoals, default=str)}
Current cell state: {json.dumps(cell_state, default=str)}

## Rules
- Return STRICT JSON with keys: "assumptions" (array), "skills" (array).
- Each skill object: {{"skill": str, "params": object, "description": str}}
- Produce an updated plan accounting for the operator note.
- Return JSON only.
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception as exc:
            logger.warning("Gemini replan failed (%s), using fallback", exc)
            raw = self._fallback_plan(instruction)

        assumptions = raw.get("assumptions") or []
        skills = raw.get("skills") or []

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

    # ── Intent detection ─────────────────────────────────────────────────────

    @staticmethod
    def _looks_like_robot_task(instruction: str) -> bool:
        lower = (instruction or "").lower()
        return bool(ACTION_VERB_PATTERN.search(lower))

    @classmethod
    def looks_like_robot_task(cls, instruction: str) -> bool:
        return cls._looks_like_robot_task(instruction)

    @staticmethod
    def _is_jog_command(instruction: str) -> bool:
        """Detect jog/rotate joint commands."""
        return bool(_JOG_PATTERN.search(instruction or ""))

    # ── Jog planning ─────────────────────────────────────────────────────────

    async def _plan_jog(self, instruction: str) -> PlanResult:
        """Plan a jog command by asking Gemini to extract joint offsets."""
        prompt = f"""You are a robotics joint-jog parser.
The robot has 6 joints: j0 (base), j1 (shoulder), j2 (elbow), j3 (wrist1), j4 (wrist2), j5 (wrist3).
Return STRICT JSON with keys:
- offsets_deg: array of 6 floats, the relative offset in degrees for each joint.
  Use 0 for joints that should not move.
- velocity: float 0.1-2.0 (default 0.5)
- acceleration: float 0.1-2.0 (default 0.5)

Instruction: {instruction!r}

Rules:
- "every joint" or "all joints" means all 6 joints get the same offset.
- Positive = counter-clockwise, negative = clockwise.
- Clamp each offset to [-45, 45] degrees for safety.
- Return only JSON.
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception:
            logger.warning("Gemini failed to parse jog command, using regex fallback")
            raw = self._fallback_jog_parse(instruction)

        offsets = raw.get("offsets_deg", [0, 0, 0, 0, 0, 0])
        if not isinstance(offsets, list) or len(offsets) != 6:
            offsets = [0, 0, 0, 0, 0, 0]
        offsets = [max(-45, min(45, float(o))) for o in offsets]

        velocity = float(raw.get("velocity", 0.5))
        acceleration = float(raw.get("acceleration", 0.5))

        skills = [
            {
                "skill": "jog_joints",
                "params": {
                    "offsets_deg": offsets,
                    "velocity": velocity,
                    "acceleration": acceleration,
                },
                "description": f"Jog joints: {instruction}",
            }
        ]

        nodes = self._skills_to_nodes(skills)
        return PlanResult(
            subgoals=[{"id": "jog_1", "skill": "jog_joints", "description": instruction}],
            assumptions=[f"Jog offsets: {offsets} deg"],
            nodes=nodes,
        )

    @staticmethod
    def _fallback_jog_parse(instruction: str) -> dict[str, Any]:
        """Regex fallback when Gemini is unavailable."""
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

    # ── Fallback planning ────────────────────────────────────────────────────

    @staticmethod
    def _fallback_plan(instruction: str) -> dict[str, Any]:
        """Deterministic fallback when Gemini is unavailable."""
        lower = (instruction or "").lower()

        # Pure perception / question
        if any(w in lower for w in ("what", "where", "how many", "describe", "check", "inspect", "scan", "look", "find", "detect", "count", "read", "identify")):
            return {
                "assumptions": ["Using fallback: perception-only task"],
                "skills": [
                    {"skill": "capture_image", "params": {}, "description": "Capture current scene"},
                    {"skill": "analyze_scene", "params": {"query": instruction}, "description": "Analyze scene with VLM"},
                    {"skill": "llm_reason", "params": {"prompt": f"Summarize the analysis for the operator. Original question: {instruction}", "response_format": "text"}, "description": "Summarize for operator"},
                ],
            }

        # Default: pick-and-place pattern
        target_zone = "target_zone"
        zone_match = re.search(r"\b(?:to|into|in|at)\s+([a-z0-9_ -]+)", lower)
        if zone_match:
            target_zone = zone_match.group(1).strip().replace(" ", "_")

        return {
            "assumptions": ["Using fallback: generic pick-and-place pattern"],
            "skills": [
                {"skill": "capture_image", "params": {}, "description": "Capture scene"},
                {"skill": "analyze_scene", "params": {"query": f"Locate the object for: {instruction}"}, "description": "Find target object"},
                {"skill": "estimate_grasp_pose", "params": {"bbox": {"x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1}, "object_class": "object"}, "description": "Estimate grasp pose"},
                {"skill": "move_to_pose", "params": {"pose": [0, 0, 0.3, 0, 3.14, 0], "motion_type": "joint", "velocity": 0.5, "acceleration": 1.0}, "description": "Move to approach"},
                {"skill": "suction_on", "params": {}, "description": "Activate suction"},
                {"skill": "move_to_pose", "params": {"pose": [0, 0, 0.15, 0, 3.14, 0], "motion_type": "linear", "velocity": 0.15, "acceleration": 0.5}, "description": "Move to place"},
                {"skill": "suction_off", "params": {}, "description": "Release suction"},
                {"skill": "verify_outcome", "params": {"expected_state": f"Task completed: {instruction}"}, "description": "Verify outcome"},
            ],
        }

    # ── Skill-to-node conversion ─────────────────────────────────────────────

    def _skills_to_nodes(self, skills: list[dict[str, Any]]) -> list[NodePlan]:
        """Convert skill dicts from Gemini into NodePlan objects."""
        nodes: list[NodePlan] = []

        for idx, skill_dict in enumerate(skills, start=1):
            skill_name = skill_dict.get("skill", "")
            node_type = SKILL_TO_NODE_TYPE.get(skill_name)

            if node_type is None:
                logger.warning("Unknown skill '%s' in plan, skipping", skill_name)
                continue

            # Determine timeout based on skill type
            timeout_ms = 30000
            if node_type in (NodeType.MOVE_TO_POSE, NodeType.MOVE_JOINTS):
                timeout_ms = 45000
            elif node_type in (NodeType.WAIT, NodeType.WAIT_DIGITAL_INPUT):
                timeout_ms = 60000
            elif node_type in (NodeType.CAPTURE_IMAGE, NodeType.GET_ROBOT_STATE,
                               NodeType.SUCTION_ON, NodeType.SUCTION_OFF):
                timeout_ms = 10000

            nodes.append(NodePlan(
                name=f"step_{idx}_{skill_name}",
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

        # Always append summary node
        nodes.append(NodePlan(
            name="summary",
            type=NodeType.SUMMARY_NODE,
            payload={},
            timeout_ms=10000,
        ))

        return nodes
