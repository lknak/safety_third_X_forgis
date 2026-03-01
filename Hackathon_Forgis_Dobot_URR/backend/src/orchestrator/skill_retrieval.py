"""Semantic skill retrieval and task-type classification for the planner.

Implements Tool Retrieval Augmented Planning (TRAP):
  1. Classify the user's instruction into a TaskType
  2. Retrieve only the K most relevant skills (not the full catalog)
  3. Boost skills that belong to the canonical chain for that task type

This replaces the naive approach of injecting ALL skills into every prompt,
reducing token usage and dramatically improving plan quality by surfacing the
right tools for each class of task.

Inspired by:
  - Voyager (Wang et al., 2023)  — skill library with retrieval
  - ToolBench (Qin et al., 2023) — tool retrieval for LLM agents
  - ReAct (Yao et al., 2022)     — structured reason + act planning
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Task taxonomy ─────────────────────────────────────────────────────────────

class TaskType(str, Enum):
    PERCEPTION = "perception"
    PICK_AND_PLACE = "pick_and_place"
    XY_MOTION = "xy_motion"
    SORTING = "sorting"
    IO_CONTROL = "io_control"
    NARRATION = "narration"
    JOG = "jog"
    COMPOSITE = "composite"


# Ordered by specificity — first match wins.
_TASK_PATTERNS: list[tuple[TaskType, re.Pattern]] = [
    (
        TaskType.JOG,
        re.compile(
            r"\bjog\b|\bnudge\b"
            r"|\b(rotate|turn|move)\b.{0,30}\b(joint|axis|j[0-5]|degree|deg)\b",
            re.I,
        ),
    ),
    (
        TaskType.SORTING,
        re.compile(
            r"\b(sort|segregat|separat|organiz|distribut|batch|remaining|"
            r"all\s+(?:the\s+)?(?:\w+\s+)?(box|item|object|piece|bin)|"
            r"every\s+(?:\w+\s+)?(box|item|object)|clear\s+(?:the\s+)?\w+)\b",
            re.I,
        ),
    ),
    (
        TaskType.IO_CONTROL,
        re.compile(
            r"\b(suction\s+on|suction\s+off|set\s+pin|digital\s+output"
            r"|wait\s+for\s+(input|signal)|io\s+pin|gripper)\b",
            re.I,
        ),
    ),
    (
        TaskType.NARRATION,
        re.compile(
            r"\b(narrat|commentat|commentary|live\s+(stream|view)|observe"
            r"|describe\s+(the\s+)?(scene|cell|workspace)|what\s+do\s+you\s+see"
            r"|stream\s+live|give\s+me\s+a\s+rundown)\b",
            re.I,
        ),
    ),
    (
        TaskType.XY_MOTION,
        re.compile(
            r"\b(trace|draw|sweep|drag|slide|push\s+along)\b"
            r"|\b(move|go|navigate)\b.{0,25}\b(path|route|along|trajectory|line)\b",
            re.I,
        ),
    ),
    (
        TaskType.PERCEPTION,
        re.compile(
            r"\b(what|where|how\s+many|count|detect|identify|inspect|scan"
            r"|read|find|look\s+at|is\s+there|are\s+there|show\s+me|tell\s+me"
            r"|capture\s+image|take\s+a\s+photo|photograph|picture)\b",
            re.I,
        ),
    ),
    (
        TaskType.PICK_AND_PLACE,
        re.compile(
            r"\b(pick|place|move|transfer|put|grab|stack|load|unload|take"
            r"|carry|bring|deliver|relocat|pick\s+up|lift)\b",
            re.I,
        ),
    ),
]


# ── Canonical skill chains per task type ─────────────────────────────────────
# These represent validated, safe orderings for each task class.

SKILL_GROUPS: dict[TaskType, list[str]] = {
    TaskType.PERCEPTION: [
        "capture_image",
        "analyze_scene",
        "llm_reason",
    ],
    TaskType.PICK_AND_PLACE: [
        "capture_image",
        "analyze_scene",
        "plan_trajectory",
        "estimate_grasp_pose",
        "move_to_pose",
        "suction_on",
        "move_to_pose",
        "suction_off",
        "live_narrate",
        "verify_outcome",
    ],
    TaskType.XY_MOTION: [
        "capture_image",
        "plan_trajectory",
        "execute_xy_action",
        "live_narrate",
        "verify_outcome",
    ],
    TaskType.SORTING: [],  # Fully agentic — skills selected dynamically per iteration
    TaskType.IO_CONTROL: [
        "get_robot_state",
        "suction_on",
        "suction_off",
        "set_digital_output",
        "wait_digital_input",
    ],
    TaskType.NARRATION: [
        "capture_image",
        "analyze_scene",
        "live_narrate",
    ],
    TaskType.JOG: ["jog_joints"],
    TaskType.COMPOSITE: [],  # Planner has full latitude
}

# Skill ordering constraints used for plan validation
SKILL_CONSTRAINTS: list[tuple[str, str, str | None]] = [
    # (skill, constraint_type, related_skill)
    ("execute_xy_action", "requires_preceding", "plan_trajectory"),
    ("estimate_grasp_pose", "should_follow", "analyze_scene"),
    ("suction_on", "must_pair_with", "suction_off"),
    ("suction_off", "must_pair_with", "suction_on"),
    ("verify_outcome", "should_be_near_end", None),
]

# Keyword associations for relevance scoring
_SKILL_KEYWORDS: dict[str, frozenset[str]] = {
    "capture_image": frozenset({
        "image", "photo", "picture", "capture", "snapshot", "camera",
        "frame", "view", "see", "show",
    }),
    "analyze_scene": frozenset({
        "analyze", "detect", "count", "find", "what", "where", "scene",
        "objects", "identify", "inspect", "look", "check", "see", "how", "many",
        "read", "label", "describe",
    }),
    "estimate_grasp_pose": frozenset({
        "grasp", "pose", "grip", "pick", "approach", "3d", "position",
        "location", "coordinate",
    }),
    "plan_trajectory": frozenset({
        "trajectory", "path", "route", "motion", "plan", "move", "navigate",
        "waypoint", "er", "trace",
    }),
    "llm_reason": frozenset({
        "reason", "think", "decide", "summarize", "explain", "answer",
        "interpret", "classify", "infer", "conclude",
    }),
    "live_narrate": frozenset({
        "narrate", "commentary", "live", "describe", "tell", "speak",
        "voice", "comment", "observe",
    }),
    "move_to_pose": frozenset({
        "move", "cartesian", "pose", "position", "xyz", "linear",
        "tcp", "approach", "place", "reach",
    }),
    "execute_xy_action": frozenset({
        "xy", "planar", "horizontal", "sweep", "execute", "2d", "flat",
    }),
    "move_joints": frozenset({
        "joint", "degrees", "angle", "joints", "configuration",
    }),
    "jog_joints": frozenset({
        "jog", "nudge", "offset", "rotate", "axis",
        "j0", "j1", "j2", "j3", "j4", "j5", "deg",
    }),
    "get_robot_state": frozenset({
        "state", "status", "position", "current", "read", "pose", "joints",
        "where", "is",
    }),
    "suction_on": frozenset({
        "suction", "grip", "grasp", "pick", "attach", "on", "activate", "grab",
    }),
    "suction_off": frozenset({
        "release", "drop", "place", "off", "detach", "deactivate", "let",
    }),
    "set_digital_output": frozenset({
        "digital", "output", "pin", "signal", "set", "io", "high", "low",
    }),
    "wait_digital_input": frozenset({
        "wait", "input", "signal", "sensor", "trigger", "ready", "until",
    }),
    "wait": frozenset({
        "wait", "pause", "delay", "sleep", "hold", "condition",
        "seconds", "milliseconds",
    }),
    "verify_outcome": frozenset({
        "verify", "check", "confirm", "validate", "success",
        "outcome", "result", "done",
    }),
    "point_to_object": frozenset({
        "point", "aim", "direct", "locate", "target", "go to", "move to",
    }),
}

# Human-readable labels for task types used in prompts
TASK_TYPE_LABELS: dict[TaskType, str] = {
    TaskType.PERCEPTION: "PERCEPTION — vision query, detection, counting, reading",
    TaskType.PICK_AND_PLACE: "PICK_AND_PLACE — grasp one object and place it somewhere",
    TaskType.XY_MOTION: "XY_MOTION — planar 2D motion along a path (Z locked)",
    TaskType.SORTING: "SORTING — multi-object, variable-count, adaptive loop",
    TaskType.IO_CONTROL: "IO_CONTROL — direct actuator / IO pin control",
    TaskType.NARRATION: "NARRATION — live visual commentary of the workspace",
    TaskType.JOG: "JOG — relative joint offset command",
    TaskType.COMPOSITE: "COMPOSITE — mixed or unclassified task",
}


# ── SkillInfo dataclass ───────────────────────────────────────────────────────

@dataclass
class SkillInfo:
    name: str
    layer: str
    description: str
    params: dict
    returns: str
    use_when: str = ""
    avoid_when: str = ""
    relevance_score: float = 0.0


# ── SkillRetriever ────────────────────────────────────────────────────────────

class SkillRetriever:
    """Retrieves contextually relevant skills using keyword overlap + task taxonomy.

    At planning time, instead of injecting all N skills into the prompt,
    this retriever scores each skill against the instruction and returns
    the top-K most relevant ones — dramatically reducing prompt noise.
    """

    def __init__(self, skill_catalog: list[dict[str, Any]]) -> None:
        self._catalog: dict[str, dict[str, Any]] = {
            s["name"]: s for s in skill_catalog
        }

    # ── Task classification ───────────────────────────────────────────────

    def classify_task_type(self, instruction: str) -> TaskType:
        """Classify an instruction into the dominant task type."""
        for task_type, pattern in _TASK_PATTERNS:
            if pattern.search(instruction):
                return task_type
        return TaskType.COMPOSITE

    # ── Skill retrieval ───────────────────────────────────────────────────

    def get_relevant_skills(
        self, instruction: str, top_k: int = 12
    ) -> list[SkillInfo]:
        """Return up to top_k skills ranked by relevance to the instruction.

        Scoring:
          - Base score: fraction of skill's keywords that appear in the instruction
          - Group boost (+2.5): skill belongs to the canonical chain for this task type
          - Always include a small set of core utility skills (capture_image, verify_outcome)
        """
        words = frozenset(re.findall(r"\b\w+\b", instruction.lower()))
        task_type = self.classify_task_type(instruction)
        group_set = frozenset(SKILL_GROUPS.get(task_type, []))

        # Core skills always included as scaffolding
        always_include = frozenset({"capture_image", "verify_outcome", "llm_reason"})

        scored: list[tuple[float, SkillInfo]] = []
        for name, skill in self._catalog.items():
            kw = _SKILL_KEYWORDS.get(name, frozenset())
            overlap = len(words & kw)
            score = overlap / max(len(kw), 1)

            if name in group_set:
                score += 2.5
            if name in always_include:
                score += 0.5

            info = SkillInfo(
                name=name,
                layer=skill.get("layer", ""),
                description=skill.get("description", ""),
                params=skill.get("params", {}),
                returns=skill.get("returns", ""),
                use_when=skill.get("use_when", ""),
                avoid_when=skill.get("avoid_when", ""),
                relevance_score=score,
            )
            scored.append((score, info))

        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:top_k]]

    # ── Formatting ────────────────────────────────────────────────────────

    def format_skills_for_prompt(self, skills: list[SkillInfo]) -> str:
        """Format retrieved skills as a concise catalog for LLM prompts."""
        lines: list[str] = []
        for s in skills:
            params_str = json.dumps(s.params)
            line = f"  - {s.name} [{s.layer}]: {s.description}"
            line += f"  Params: {params_str}"
            line += f"  Returns: {s.returns}"
            if s.use_when:
                line += f"  USE WHEN: {s.use_when}"
            if s.avoid_when:
                line += f"  AVOID WHEN: {s.avoid_when}"
            lines.append(line)
        return "\n".join(lines)

    def get_canonical_chain(self, task_type: TaskType) -> str:
        """Return the canonical ordered skill chain for a task type."""
        group = SKILL_GROUPS.get(task_type, [])
        if not group:
            return "(no fixed chain — planner determines sequence)"
        return " → ".join(dict.fromkeys(group))  # deduplicate while preserving order

    def get_all_skill_names(self) -> list[str]:
        """Return all skill names from the catalog."""
        return list(self._catalog.keys())

    # ── Plan validation ───────────────────────────────────────────────────

    def validate_plan(
        self, skills: list[dict[str, Any]]
    ) -> tuple[bool, list[str]]:
        """Validate a skill sequence against ordering constraints.

        Returns (is_valid, list_of_issues).
        """
        names = [s.get("skill", "") for s in skills]
        issues: list[str] = []

        # execute_xy_action must follow plan_trajectory
        if "execute_xy_action" in names:
            traj_idx = next(
                (i for i, n in enumerate(names) if n == "plan_trajectory"), -1
            )
            xy_idx = names.index("execute_xy_action")
            if traj_idx == -1:
                issues.append(
                    "execute_xy_action requires plan_trajectory earlier in the plan"
                )
            elif traj_idx >= xy_idx:
                issues.append(
                    "execute_xy_action must come AFTER plan_trajectory"
                )

        # suction_on must be paired with suction_off
        on_count = names.count("suction_on")
        off_count = names.count("suction_off")
        if on_count != off_count:
            issues.append(
                f"suction_on ({on_count}×) must be paired with "
                f"suction_off ({off_count}×)"
            )

        # verify_outcome should not be the first skill
        if names and names[0] == "verify_outcome":
            issues.append("verify_outcome should not be the first skill")

        # Unknown skills
        unknown = [n for n in names if n and n not in self._catalog]
        if unknown:
            issues.append(f"Unknown skills in plan: {unknown}")

        return len(issues) == 0, issues
