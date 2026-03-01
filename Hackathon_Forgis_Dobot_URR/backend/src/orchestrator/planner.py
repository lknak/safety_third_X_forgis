"""Iterative skill-aware planner for the orchestrator.

Plans one step at a time, evaluating results between steps — like Claude
deciding which tool to use next based on what it has already learned.
"""

from __future__ import annotations

import logging
import random
import re
from typing import Any

from .gemini_client import OrchestratorGeminiClient
from .schemas import (
    CATCHY_PHRASES,
    SKILL_BY_NAME,
    SKILL_BY_NODE_TYPE,
    SKILL_CATALOG,
    IterativePlanStep,
    NodePlan,
    NodeType,
    PlanResult,
    StepReasoning,
)

logger = logging.getLogger(__name__)

NON_ACTIONABLE_TASK_MESSAGE = (
    "No actionable robot task detected. Please provide an instruction such as "
    "'Pick box A from infeed and place it in Zone_A'."
)

ACTION_VERBS = (
    "pick", "place", "move", "transfer", "convey", "put", "grab",
    "stack", "sort", "load", "unload", "palletize", "label",
    "jog", "rotate", "nudge",
)
ACTION_VERB_PATTERN = re.compile(r"\b(" + "|".join(ACTION_VERBS) + r")\b")

_JOG_PATTERN = re.compile(
    r"\b(?:jog|rotate|nudge)\b.*\b(?:joint|axis|j[0-5]|degree|deg)\b"
    r"|\b(?:move|turn)\b.*\b(?:joint|axis|j[0-5])\b.*\b(?:degree|deg|°)\b"
    r"|\b(?:move|turn)\b.*\bevery\s+joint\b",
    re.IGNORECASE,
)

DEMO_INSTRUCTION = "__SKILL_DEMO__"

# ── Demo step definitions ─────────────────────────────────────
# Each entry: name, type, skill, thought, catchy, payload, timeout_ms
_DEMO_STEPS: list[dict[str, Any]] = [
    {
        "name": "demo_scene_analysis",
        "type": NodeType.ER_1_5_ANALYSIS_NODE,
        "skill": "analyze_scene",
        "thought": (
            "First, let me look through the camera and analyze the workspace. "
            "I'll use Gemini Robotics ER vision to detect objects and map the scene."
        ),
        "catchy": "Opening eyes on the factory floor...",
        "payload": {
            "subgoal": {"id": "demo_1", "object": "demo_target", "source_zone": "workspace", "target_zone": "workspace", "object_class": "demo"},
            "goal_index": 1, "goal_count": 1,
        },
        "timeout_ms": 30000,
    },
    {
        "name": "demo_depth_estimation",
        "type": NodeType.DEPTH_ESTIMATION_NODE,
        "skill": "estimate_depth",
        "thought": (
            "Good, I can see the workspace. Now I'll calculate safe approach "
            "heights and convert camera coordinates into real robot poses."
        ),
        "catchy": "Crunching the Z-heights...",
        "payload": {
            "subgoal": {"id": "demo_1", "object": "demo_target", "source_zone": "workspace", "target_zone": "workspace", "object_class": "demo"},
            "goal_index": 1, "goal_count": 1,
        },
        "timeout_ms": 15000,
    },
    {
        "name": "demo_jog_joints",
        "type": NodeType.JOG_JOINTS_NODE,
        "skill": "jog_joints",
        "thought": (
            "Watch the arm — I'm making a tiny 2-degree rotation on each joint "
            "to show manual joint control. Small enough to be safe, big enough to see."
        ),
        "catchy": "Doing a little wiggle...",
        "payload": {
            "instruction": "demo: jog all joints by 2 degrees",
            "offsets_deg": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
            "velocity": 0.3, "acceleration": 0.3,
        },
        "timeout_ms": 20000,
    },
    {
        "name": "demo_jog_return",
        "type": NodeType.JOG_JOINTS_NODE,
        "skill": "jog_joints",
        "thought": (
            "Now I'll jog back to the original position — negative 2 degrees "
            "on each joint. The arm should return right where it started."
        ),
        "catchy": "And back we go...",
        "payload": {
            "instruction": "demo: return joints by -2 degrees",
            "offsets_deg": [-2.0, -2.0, -2.0, -2.0, -2.0, -2.0],
            "velocity": 0.3, "acceleration": 0.3,
        },
        "timeout_ms": 20000,
    },
    {
        "name": "demo_live_commentary",
        "type": NodeType.GEMINI_LIVE_COMMENTARY_NODE,
        "skill": "narrate_live",
        "thought": (
            "Let me narrate what just happened using Gemini live commentary. "
            "This is how the system provides real-time audio feedback during actual tasks."
        ),
        "catchy": "Rolling live commentary...",
        "payload": {
            "subgoal": {"id": "demo_1", "object": "demo_target", "source_zone": "workspace", "target_zone": "workspace", "object_class": "demo"},
            "goal_index": 1, "goal_count": 1,
        },
        "timeout_ms": 20000,
    },
    {
        "name": "demo_verification",
        "type": NodeType.VERIFICATION_NODE,
        "skill": "verify_motion",
        "thought": (
            "Let me verify that all the demo motions completed successfully "
            "by checking the robot telemetry."
        ),
        "catchy": "Did everything land right?",
        "payload": {
            "subgoal": {"id": "demo_1", "object": "demo_target", "source_zone": "workspace", "target_zone": "workspace", "object_class": "demo"},
            "goal_index": 1, "goal_count": 1,
        },
        "timeout_ms": 15000,
    },
]

# ── Default skill pipeline per subgoal ────────────────────────
# This is the proven sequence for pick-and-place.  The iterative planner
# uses it as a backbone but can skip / re-order steps if needed.
_PICK_PLACE_PIPELINE = [
    "analyze_scene",
    "estimate_depth",
    "move_robot",
    "narrate_live",
    "verify_motion",
]


def _catchy(skill_name: str) -> str:
    """Pick a random catchy phrase for a given skill."""
    phrases = CATCHY_PHRASES.get(skill_name, ["Working on it..."])
    return random.choice(phrases)


class OrchestratorPlanner:
    """Skill-aware iterative planner with Claude-style reasoning."""

    def __init__(self, gemini: OrchestratorGeminiClient):
        self._gemini = gemini

    # ── Batch planning (preview + legacy) ─────────────────────

    async def plan(self, instruction: str, cell_state: dict[str, Any]) -> PlanResult:
        """Create initial plan from raw instruction — used for preview and queue."""
        if not self._looks_like_robot_task(instruction):
            raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)

        if self.is_demo_command(instruction):
            return self._build_demo_preview()

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

    # ── Iterative skill-by-skill planner (core algorithm) ─────

    async def plan_next_step(
        self,
        instruction: str,
        context: dict[str, Any],
    ) -> IterativePlanStep:
        """Decide the next single skill to invoke, Claude-style.

        Examines the execution history in *context* and returns the next
        skill with a reasoning explanation.  This is the heart of the
        node-by-node planner.
        """
        executed = context.get("executed_nodes", [])
        subgoals = context.get("subgoals", [])
        current_goal_idx = context.get("current_goal_index", 0)
        cell_state = context.get("cell_state", {})
        is_jog = context.get("is_jog", False)

        # ── Jog commands: simple two-step pipeline ────────────
        if is_jog:
            return self._plan_next_jog_step(context)

        # ── Finished all subgoals? Summarize and wrap up ──────
        if current_goal_idx >= len(subgoals):
            # Check if summary already executed
            summary_done = any(
                n.type == NodeType.SUMMARY_NODE
                for n in executed
                if hasattr(n, "type")
            )
            if summary_done:
                return IterativePlanStep(
                    reasoning=StepReasoning(
                        thought="Every subgoal is verified and the summary is filed. We're done here.",
                        chosen_skill="done",
                        goal_index=current_goal_idx,
                    ),
                    is_complete=True,
                    catchy_phrase=_catchy("done"),
                )
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought="All subgoals have been completed. Time to compile the execution summary.",
                    chosen_skill="summarize",
                    goal_index=current_goal_idx,
                ),
                node=NodePlan(
                    name="summary",
                    type=NodeType.SUMMARY_NODE,
                    payload={},
                    timeout_ms=30000,
                ),
                catchy_phrase=_catchy("summarize"),
            )

        subgoal = subgoals[current_goal_idx]
        goal_prefix = f"goal_{current_goal_idx + 1}"

        # Gather which pipeline skills have been executed for this subgoal
        goal_step_types: list[NodeType] = [
            n.type
            for n in executed
            if hasattr(n, "name") and n.name.startswith(goal_prefix)
        ]

        # Walk the deterministic pipeline to find the next unexecuted skill
        payload = {
            "subgoal": subgoal,
            "goal_index": current_goal_idx + 1,
            "goal_count": len(subgoals),
        }

        return self._next_pipeline_step(
            goal_step_types=goal_step_types,
            subgoal=subgoal,
            goal_prefix=goal_prefix,
            goal_index=current_goal_idx,
            payload=payload,
        )

    # ── Pipeline step logic ───────────────────────────────────

    def _next_pipeline_step(
        self,
        goal_step_types: list[NodeType],
        subgoal: dict[str, Any],
        goal_prefix: str,
        goal_index: int,
        payload: dict[str, Any],
    ) -> IterativePlanStep:
        """Walk the pick-place pipeline for a single subgoal and return the next step."""

        obj_name = subgoal.get("object", "the target")
        target_zone = subgoal.get("target_zone", "the target zone")
        source_zone = subgoal.get("source_zone", "current position")

        # 1. analyze_scene (ER)
        if NodeType.ER_1_5_ANALYSIS_NODE not in goal_step_types:
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought=(
                        f"I need to look at the workspace and locate '{obj_name}' "
                        f"near {source_zone}. Let me fire up the vision system."
                    ),
                    chosen_skill="analyze_scene",
                    goal_index=goal_index,
                    context_note=f"Locating {obj_name} for subgoal {goal_index + 1}",
                ),
                node=NodePlan(
                    name=f"{goal_prefix}_er_analysis",
                    type=NodeType.ER_1_5_ANALYSIS_NODE,
                    payload=payload,
                    timeout_ms=30000,
                ),
                catchy_phrase=_catchy("analyze_scene"),
            )

        # 2. estimate_depth
        if NodeType.DEPTH_ESTIMATION_NODE not in goal_step_types:
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought=(
                        f"Great, I can see '{obj_name}'. Now I need to figure out the "
                        f"safe approach heights and convert the vision coordinates into "
                        f"real-world robot poses for {target_zone}."
                    ),
                    chosen_skill="estimate_depth",
                    goal_index=goal_index,
                    context_note=f"Calculating poses → {target_zone}",
                ),
                node=NodePlan(
                    name=f"{goal_prefix}_depth_estimation",
                    type=NodeType.DEPTH_ESTIMATION_NODE,
                    payload=payload,
                    timeout_ms=30000,
                ),
                catchy_phrase=_catchy("estimate_depth"),
            )

        # 3. move_robot
        if NodeType.ROBOT_EXECUTION_NODE not in goal_step_types:
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought=(
                        f"Coordinates are locked in. Time to send the robot to pick "
                        f"'{obj_name}' and move it to {target_zone}."
                    ),
                    chosen_skill="move_robot",
                    goal_index=goal_index,
                    context_note="Executing robot motion",
                ),
                node=NodePlan(
                    name=f"{goal_prefix}_robot_execution",
                    type=NodeType.ROBOT_EXECUTION_NODE,
                    payload=payload,
                    timeout_ms=45000,
                ),
                catchy_phrase=_catchy("move_robot"),
            )

        # 4. narrate_live (runs concurrently with robot, but planned separately)
        if NodeType.GEMINI_LIVE_COMMENTARY_NODE not in goal_step_types:
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought="While the arm moves, let me narrate what's happening for the operator.",
                    chosen_skill="narrate_live",
                    goal_index=goal_index,
                    context_note="Live commentary during motion",
                ),
                node=NodePlan(
                    name=f"{goal_prefix}_live_commentary",
                    type=NodeType.GEMINI_LIVE_COMMENTARY_NODE,
                    payload=payload,
                    timeout_ms=45000,
                ),
                catchy_phrase=_catchy("narrate_live"),
            )

        # 5. verify_motion
        if NodeType.VERIFICATION_NODE not in goal_step_types:
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought=(
                        f"The robot moved. Let me verify the motion completed "
                        f"successfully before moving on."
                    ),
                    chosen_skill="verify_motion",
                    goal_index=goal_index,
                    context_note="Checking motion telemetry",
                ),
                node=NodePlan(
                    name=f"{goal_prefix}_verification",
                    type=NodeType.VERIFICATION_NODE,
                    payload=payload,
                    timeout_ms=30000,
                ),
                catchy_phrase=_catchy("verify_motion"),
            )

        # All steps for this subgoal are done — advance to next subgoal
        return IterativePlanStep(
            reasoning=StepReasoning(
                thought=(
                    f"Subgoal {goal_index + 1} ('{obj_name}' → {target_zone}) is "
                    f"complete. Moving on to the next one."
                ),
                chosen_skill="advance_subgoal",
                goal_index=goal_index + 1,
            ),
            is_complete=False,  # not fully done, just this subgoal
            catchy_phrase=f"Subgoal {goal_index + 1} done — next up!",
        )

    def _plan_next_jog_step(self, context: dict[str, Any]) -> IterativePlanStep:
        """Next step for a jog command (simple 2-step pipeline)."""
        executed = context.get("executed_nodes", [])
        exec_types = [n.type for n in executed if hasattr(n, "type")]

        if NodeType.JOG_JOINTS_NODE not in exec_types:
            jog_payload = context.get("jog_payload", {})
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought="Sending the jog command to the robot joints now.",
                    chosen_skill="jog_joints",
                ),
                node=NodePlan(
                    name="jog_joints",
                    type=NodeType.JOG_JOINTS_NODE,
                    payload=jog_payload,
                    timeout_ms=20000,
                ),
                catchy_phrase=_catchy("jog_joints"),
            )

        if NodeType.SUMMARY_NODE not in exec_types:
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought="Joint jog complete. Let me wrap up with a summary.",
                    chosen_skill="summarize",
                ),
                node=NodePlan(
                    name="summary",
                    type=NodeType.SUMMARY_NODE,
                    payload={},
                    timeout_ms=10000,
                ),
                catchy_phrase=_catchy("summarize"),
            )

        return IterativePlanStep(
            reasoning=StepReasoning(
                thought="Jog operation is done. All finished.",
                chosen_skill="done",
            ),
            is_complete=True,
            catchy_phrase=_catchy("done"),
        )

    # ── Skill catalog helpers ─────────────────────────────────

    @staticmethod
    def get_skill_catalog_prompt() -> str:
        """Format the skill catalog as a prompt snippet for Gemini."""
        lines = ["Available orchestrator skills:"]
        for skill in SKILL_CATALOG:
            lines.append(f"  - {skill.name} ({skill.phase}): {skill.description}")
        return "\n".join(lines)

    @staticmethod
    def get_reasoning_for_node(node_type: NodeType, subgoal: dict[str, Any] | None = None) -> str:
        """Generate a human-friendly reasoning string for a given node type."""
        skill = SKILL_BY_NODE_TYPE.get(node_type)
        if not skill:
            return "Executing next step..."

        obj = (subgoal or {}).get("object", "the target")
        target = (subgoal or {}).get("target_zone", "the target zone")

        reasoning_map: dict[NodeType, str] = {
            NodeType.INPUT_NODE: "Let me take a snapshot of the cell to understand what we're working with.",
            NodeType.ORCHESTRATOR_PLANNER_NODE: "Breaking down the instruction into concrete subgoals...",
            NodeType.ER_1_5_ANALYSIS_NODE: f"Looking at the workspace to locate '{obj}'...",
            NodeType.DEPTH_ESTIMATION_NODE: f"Calculating safe approach heights for {target}...",
            NodeType.ROBOT_EXECUTION_NODE: f"Sending the robot to handle '{obj}'...",
            NodeType.GEMINI_LIVE_COMMENTARY_NODE: "Narrating the robot motion in real time...",
            NodeType.VERIFICATION_NODE: "Checking if the motion completed successfully...",
            NodeType.JOG_JOINTS_NODE: "Moving the requested joints...",
            NodeType.SUMMARY_NODE: "Compiling the execution summary...",
        }
        return reasoning_map.get(node_type, f"Running {skill.name}...")

    # ── Demo planning ────────────────────────────────────────

    @staticmethod
    def is_demo_command(instruction: str) -> bool:
        """Check if the instruction is a skill demo trigger."""
        return instruction.strip() == DEMO_INSTRUCTION

    def plan_next_demo_step(self, context: dict[str, Any]) -> IterativePlanStep:
        """Return the next demo step based on what has already executed."""
        executed = context.get("executed_nodes", [])
        executed_names: set[str] = {
            n.name for n in executed if hasattr(n, "name")
        }

        for step_def in _DEMO_STEPS:
            if step_def["name"] not in executed_names:
                return IterativePlanStep(
                    reasoning=StepReasoning(
                        thought=step_def["thought"],
                        chosen_skill=step_def["skill"],
                        goal_index=0,
                        context_note=f"Demo step: {step_def['name']}",
                    ),
                    node=NodePlan(
                        name=step_def["name"],
                        type=step_def["type"],
                        payload=step_def["payload"],
                        timeout_ms=step_def.get("timeout_ms", 20000),
                    ),
                    catchy_phrase=step_def["catchy"],
                )

        # Check if summary is done
        if "demo_summary" not in executed_names:
            return IterativePlanStep(
                reasoning=StepReasoning(
                    thought="That's every skill demonstrated! Let me compile the full report.",
                    chosen_skill="summarize",
                    context_note="Demo summary",
                ),
                node=NodePlan(
                    name="demo_summary",
                    type=NodeType.SUMMARY_NODE,
                    payload={},
                    timeout_ms=15000,
                ),
                catchy_phrase="Wrapping up the grand tour...",
            )

        return IterativePlanStep(
            reasoning=StepReasoning(
                thought="All skills demonstrated successfully. The demo is complete!",
                chosen_skill="done",
            ),
            is_complete=True,
            catchy_phrase="Demo complete — every skill checked out!",
        )

    def _build_demo_preview(self) -> PlanResult:
        """Build a preview plan for the demo (all nodes listed up-front)."""
        nodes: list[NodePlan] = []
        for step_def in _DEMO_STEPS:
            nodes.append(NodePlan(
                name=step_def["name"],
                type=step_def["type"],
                payload=step_def["payload"],
                timeout_ms=step_def.get("timeout_ms", 20000),
            ))
        nodes.append(NodePlan(name="demo_summary", type=NodeType.SUMMARY_NODE, payload={}, timeout_ms=15000))
        return PlanResult(
            subgoals=[{"id": "demo", "type": "skill_demo", "description": "Demonstrate all orchestrator skills"}],
            assumptions=["Demo mode: tiny safe movements", "All joints jog ±2 deg"],
            nodes=nodes,
        )

    # ── Classification helpers ────────────────────────────────

    @staticmethod
    def _looks_like_robot_task(instruction: str) -> bool:
        lower = (instruction or "").lower()
        if instruction.strip() == DEMO_INSTRUCTION:
            return True
        return bool(ACTION_VERB_PATTERN.search(lower))

    @classmethod
    def looks_like_robot_task(cls, instruction: str) -> bool:
        return cls._looks_like_robot_task(instruction)

    @staticmethod
    def _is_jog_command(instruction: str) -> bool:
        return bool(_JOG_PATTERN.search(instruction or ""))

    # ── Jog planning ──────────────────────────────────────────

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
            NodePlan(name="jog_joints", type=NodeType.JOG_JOINTS_NODE, payload=payload, timeout_ms=20000),
            NodePlan(name="summary", type=NodeType.SUMMARY_NODE, payload={}, timeout_ms=10000),
        ]

        return PlanResult(
            subgoals=[{"id": "jog_1", "type": "jog_joints", "instruction": instruction}],
            assumptions=[f"Jog offsets: {offsets} deg"],
            nodes=nodes,
        )

    # ── Fallbacks ─────────────────────────────────────────────

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
            normalized.append({
                "id": str(goal.get("id") or f"goal_{idx}"),
                "object": str(goal.get("object") or "object"),
                "source_zone": str(goal.get("source_zone") or "current_zone"),
                "target_zone": str(goal.get("target_zone") or "target_zone"),
                "object_class": str(goal.get("object_class") or "object"),
            })
        return normalized

    def _build_nodes(self, subgoals: list[dict[str, Any]]) -> list[NodePlan]:
        """Build the full linear node list (used for preview)."""
        nodes: list[NodePlan] = []
        for idx, subgoal in enumerate(subgoals, start=1):
            name_prefix = f"goal_{idx}"
            payload = {
                "subgoal": subgoal,
                "goal_index": idx,
                "goal_count": len(subgoals),
            }
            nodes.append(NodePlan(name=f"{name_prefix}_er_analysis", type=NodeType.ER_1_5_ANALYSIS_NODE, payload=payload, timeout_ms=30000))
            nodes.append(NodePlan(name=f"{name_prefix}_depth_estimation", type=NodeType.DEPTH_ESTIMATION_NODE, payload=payload, timeout_ms=30000))
            nodes.append(NodePlan(name=f"{name_prefix}_robot_execution", type=NodeType.ROBOT_EXECUTION_NODE, payload=payload, timeout_ms=45000))
            nodes.append(NodePlan(name=f"{name_prefix}_live_commentary", type=NodeType.GEMINI_LIVE_COMMENTARY_NODE, payload=payload, timeout_ms=45000))
            nodes.append(NodePlan(name=f"{name_prefix}_verification", type=NodeType.VERIFICATION_NODE, payload=payload, timeout_ms=30000))

        nodes.append(NodePlan(name="summary", type=NodeType.SUMMARY_NODE, payload={}, timeout_ms=30000))
        return nodes
