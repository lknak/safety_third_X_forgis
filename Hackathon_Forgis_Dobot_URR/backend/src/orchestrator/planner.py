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
)
ACTION_VERB_PATTERN = re.compile(r"\b(" + "|".join(ACTION_VERBS) + r")\b")


class OrchestratorPlanner:
    """Gemini-backed planner that produces strict linear node sequences."""

    def __init__(self, gemini: OrchestratorGeminiClient):
        self._gemini = gemini

    async def plan(self, instruction: str, cell_state: dict[str, Any]) -> PlanResult:
        """Create initial plan from raw instruction and current cell state."""
        if not self._looks_like_robot_task(instruction):
            raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)

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
