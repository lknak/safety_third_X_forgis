"""Planner for converting natural language goals into strict orchestrator node plans."""

from __future__ import annotations

import logging
import re
from typing import Any

from .gemini_client import OrchestratorGeminiClient
from .schemas import NodePlan, NodeType, PlanResult

logger = logging.getLogger(__name__)

NON_ACTIONABLE_TASK_MESSAGE = (
    "No actionable robot task detected. Please provide an instruction such as "
    "'Pick box A from infeed and place it in Zone_A'."
)

ACTION_VERBS = (
    "pick",
    "place",
    "move",
    "transfer",
    "convey",
    "put",
    "grab",
    "stack",
    "sort",
    "load",
    "unload",
    "palletize",
    "label",
    "jog",
    "rotate",
    "nudge",
)
ACTION_VERB_PATTERN = re.compile(r"\b(" + "|".join(ACTION_VERBS) + r")\b")

# Detect jog / rotate joint commands (separate from pick-place pipeline)
_JOG_PATTERN = re.compile(
    r"\b(?:jog|rotate|nudge)\b.*\b(?:joint|axis|j[0-5]|degree|deg)\b"
    r"|\b(?:move|turn)\b.*\b(?:joint|axis|j[0-5])\b.*\b(?:degree|deg|°)\b"
    r"|\b(?:move|turn)\b.*\bevery\s+joint\b",
    re.IGNORECASE,
)


class OrchestratorPlanner:
    """Gemini-backed planner that produces strict linear node sequences."""

    def __init__(self, gemini: OrchestratorGeminiClient):
        self._gemini = gemini

    async def plan(self, instruction: str, cell_state: dict[str, Any]) -> PlanResult:
        """Create initial plan from raw instruction and current cell state."""
        if not self._looks_like_robot_task(instruction):
            raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)

        # Fast-path: jog / rotate joint commands skip the full vision pipeline.
        if self._is_jog_command(instruction):
            return await self._plan_jog(instruction)

        prompt = f"""
You are a robotics orchestrator planner.
Return STRICT JSON with keys: subgoals (array), assumptions (array).
Each subgoal must include:
- id (string)
- object (string)
- source_zone (string)
- target_zone (string)
- object_class (string)

Instruction: {instruction!r}
Cell state JSON: {cell_state}

Rules:
- Decompose task into ordered subgoals.
- If instruction is simple, emit one subgoal.
- Keep fields concise and deterministic.
- Return only JSON.
"""
        raw = await self._gemini.generate_json(prompt)
        subgoals = raw.get("subgoals") or []
        assumptions = raw.get("assumptions") or []

        if not isinstance(subgoals, list):
            subgoals = []

        if len(subgoals) == 0:
            # Deterministic fallback for transient model schema misses.
            subgoals = [self._fallback_subgoal(instruction)]

        subgoals = self._normalize_subgoals(subgoals)

        nodes = self._build_nodes(subgoals)
        return PlanResult(subgoals=subgoals, assumptions=assumptions, nodes=nodes)

    async def replan(
        self,
        instruction: str,
        previous_subgoals: list[dict[str, Any]],
        note: str,
        cell_state: dict[str, Any],
    ) -> PlanResult:
        """Regenerate downstream plan after clarification or goal change."""
        prompt = f"""
You are replanning a robotics task after failure or goal modification.
Return STRICT JSON with keys: subgoals (array), assumptions (array).

Original instruction: {instruction!r}
Operator note: {note!r}
Previous subgoals: {previous_subgoals}
Current cell state: {cell_state}

Rules:
- Produce an updated ordered subgoal list.
- Keep schema identical to initial planning.
- Return only JSON.
"""
        raw = await self._gemini.generate_json(prompt)
        subgoals = raw.get("subgoals") or []
        assumptions = raw.get("assumptions") or []

        if not isinstance(subgoals, list):
            subgoals = []

        if len(subgoals) == 0:
            if not self._looks_like_robot_task(instruction):
                raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)
            subgoals = [self._fallback_subgoal(instruction)]

        subgoals = self._normalize_subgoals(subgoals)

        nodes = self._build_nodes(subgoals)
        return PlanResult(subgoals=subgoals, assumptions=assumptions, nodes=nodes)

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

    async def _plan_jog(self, instruction: str) -> PlanResult:
        """Plan a jog command by asking Gemini to extract joint offsets."""
        prompt = f"""
You are a robotics joint-jog parser.
The robot has 6 joints: j0 (base), j1 (shoulder), j2 (elbow), j3 (wrist1), j4 (wrist2), j5 (wrist3).
Return STRICT JSON with keys:
- offsets_deg: array of 6 floats, the relative offset in degrees for each joint.
  Use 0 for joints that should not move.
- velocity: float 0.1-2.0 (default 0.5)
- acceleration: float 0.1-2.0 (default 0.5)

Instruction: {instruction!r}

Rules:
- Parse the instruction to determine which joints to move and by how much.
- "every joint" or "all joints" means all 6 joints get the same offset.
- Positive = counter-clockwise, negative = clockwise.
- Clamp each offset to [-45, 45] degrees for safety.
- Return only JSON, no explanation.

Examples:
- "move every joint by 5 degrees" -> {{"offsets_deg": [5,5,5,5,5,5], "velocity": 0.5, "acceleration": 0.5}}
- "rotate joint 3 by -10 degrees" -> {{"offsets_deg": [0,0,0,-10,0,0], "velocity": 0.5, "acceleration": 0.5}}
- "jog j0 and j1 by 15 deg" -> {{"offsets_deg": [15,15,0,0,0,0], "velocity": 0.5, "acceleration": 0.5}}
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception:
            logger.warning("Gemini failed to parse jog command, using regex fallback")
            raw = self._fallback_jog_parse(instruction)

        offsets = raw.get("offsets_deg", [0, 0, 0, 0, 0, 0])
        if not isinstance(offsets, list) or len(offsets) != 6:
            offsets = [0, 0, 0, 0, 0, 0]

        # Clamp safety
        offsets = [max(-45, min(45, float(o))) for o in offsets]

        velocity = float(raw.get("velocity", 0.5))
        acceleration = float(raw.get("acceleration", 0.5))

        payload = {
            "instruction": instruction,
            "offsets_deg": offsets,
            "velocity": velocity,
            "acceleration": acceleration,
        }

        nodes = [
            NodePlan(
                name="jog_joints",
                type=NodeType.JOG_JOINTS_NODE,
                payload=payload,
                timeout_ms=20000,
            ),
            NodePlan(
                name="summary",
                type=NodeType.SUMMARY_NODE,
                payload={},
                timeout_ms=10000,
            ),
        ]

        return PlanResult(
            subgoals=[{"id": "jog_1", "type": "jog_joints", "instruction": instruction}],
            assumptions=[f"Jog offsets: {offsets} deg"],
            nodes=nodes,
        )

    @staticmethod
    def _fallback_jog_parse(instruction: str) -> dict[str, Any]:
        """Regex fallback when Gemini is unavailable."""
        lower = instruction.lower()

        # Extract degree value
        deg_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:degree|deg|°)", lower)
        deg_val = float(deg_match.group(1)) if deg_match else 5.0
        deg_val = max(-45, min(45, deg_val))

        # Check for "every" / "all" joints
        if re.search(r"\b(?:every|all)\s+joint", lower):
            return {"offsets_deg": [deg_val] * 6, "velocity": 0.5, "acceleration": 0.5}

        # Check for specific joint references
        offsets = [0.0] * 6
        for m in re.finditer(r"\bj(?:oint)?\s*(\d)", lower):
            idx = int(m.group(1))
            if 0 <= idx <= 5:
                offsets[idx] = deg_val

        # If no specific joints matched, apply to all
        if all(o == 0 for o in offsets):
            offsets = [deg_val] * 6

        return {"offsets_deg": offsets, "velocity": 0.5, "acceleration": 0.5}

    @staticmethod
    def _fallback_subgoal(instruction: str) -> dict[str, Any]:
        lower = (instruction or "").lower()
        target_zone = "target_zone"
        zone_match = re.search(r"\b(?:to|into|in|at)\s+([a-z0-9_ -]+)", lower)
        if zone_match:
            target_zone = zone_match.group(1).strip().replace(" ", "_")

        obj = "object"
        obj_match = re.search(r"\b(?:pick|grab|move|transfer|label|sort|stack|put)\s+([a-z0-9_ -]+)", lower)
        if obj_match:
            obj = obj_match.group(1).strip()

        return {
            "id": "goal_1",
            "object": obj,
            "source_zone": "current_zone",
            "target_zone": target_zone,
            "object_class": "object",
        }

    @staticmethod
    def _normalize_subgoals(subgoals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for idx, raw_goal in enumerate(subgoals, start=1):
            goal = raw_goal if isinstance(raw_goal, dict) else {}
            normalized.append(
                {
                    "id": str(goal.get("id") or f"goal_{idx}"),
                    "object": str(goal.get("object") or "object"),
                    "source_zone": str(goal.get("source_zone") or "current_zone"),
                    "target_zone": str(goal.get("target_zone") or "target_zone"),
                    "object_class": str(goal.get("object_class") or "object"),
                }
            )
        return normalized

    def _build_nodes(self, subgoals: list[dict[str, Any]]) -> list[NodePlan]:
        nodes: list[NodePlan] = []

        for idx, subgoal in enumerate(subgoals, start=1):
            name_prefix = f"goal_{idx}"
            payload = {
                "subgoal": subgoal,
                "goal_index": idx,
                "goal_count": len(subgoals),
            }

            nodes.append(
                NodePlan(
                    name=f"{name_prefix}_er_analysis",
                    type=NodeType.ER_1_5_ANALYSIS_NODE,
                    payload=payload,
                    timeout_ms=30000,
                )
            )
            nodes.append(
                NodePlan(
                    name=f"{name_prefix}_depth_estimation",
                    type=NodeType.DEPTH_ESTIMATION_NODE,
                    payload=payload,
                    timeout_ms=30000,
                )
            )
            nodes.append(
                NodePlan(
                    name=f"{name_prefix}_robot_execution",
                    type=NodeType.ROBOT_EXECUTION_NODE,
                    payload=payload,
                    timeout_ms=45000,
                )
            )
            nodes.append(
                NodePlan(
                    name=f"{name_prefix}_live_commentary",
                    type=NodeType.GEMINI_LIVE_COMMENTARY_NODE,
                    payload=payload,
                    timeout_ms=45000,
                )
            )
            nodes.append(
                NodePlan(
                    name=f"{name_prefix}_verification",
                    type=NodeType.VERIFICATION_NODE,
                    payload=payload,
                    timeout_ms=30000,
                )
            )

        nodes.append(
            NodePlan(
                name="summary",
                type=NodeType.SUMMARY_NODE,
                payload={},
                timeout_ms=30000,
            )
        )
        return nodes
