"""Skill-focused orchestrator planner.

Converts natural language goals into executable primitive skill sequences.

## Architecture

### Planning modes
  STATIC   — one-shot plan for simple, bounded tasks (jog, single pick, queries)
  AGENTIC  — observe-reason-act loop for variable-count / dynamic tasks

### SOTA techniques applied

1. Tool Retrieval Augmented Planning (TRAP) [Voyager, ToolBench]
   - Task type is classified first (PERCEPTION, PICK_AND_PLACE, XY_MOTION, …)
   - Only the K most relevant skills are injected into the planning prompt
   - Reduces token noise and steers the LLM towards the right skill subset

2. Canonical Skill Chains [SayCan, Code-as-Policies]
   - Each task type has a validated canonical ordering (capture → analyze → …)
   - The planner is shown this chain as a structural anchor

3. In-Context Exemplar Learning [GPT-3 ICL, Liu et al. 2022]
   - Successful past plans are retrieved (Jaccard similarity) and injected
     as few-shot examples — no fine-tuning required

4. Structured Chain-of-Thought Output [ReAct, Yao et al. 2022]
   - LLM output includes explicit "reasoning" key before emitting skills
   - Task type is declared in output for logging and downstream routing

5. Plan Constraint Validation
   - Generated plans are checked against skill dependency rules
   - Violations are logged; LLM is asked to fix them in edge cases
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .exemplar_store import ExemplarStore
from .gemini_client import OrchestratorGeminiClient
from .schemas import MicroPlan, NodePlan, NodeType, PlanResult
from .skill_retrieval import SKILL_GROUPS, TASK_TYPE_LABELS, SkillRetriever, TaskType

logger = logging.getLogger(__name__)

NON_ACTIONABLE_TASK_MESSAGE = (
    "No actionable task detected. Please provide an instruction such as "
    "'Pick the red box from Zone A and place it in Zone B' or "
    "'What objects are on the table?'."
)

# ── Skill catalog ──────────────────────────────────────────────────────────────
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
    "point", "locate", "go", "touch", "reach", "approach", "grasp", "lift",
    "lower", "raise", "navigate", "target", "bring", "carry", "transport",
    "tell", "can", "could", "please", "which",
)
ACTION_VERB_PATTERN = re.compile(
    r"\b(" + "|".join(ACTION_VERBS) + r")\b", re.IGNORECASE
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
    "point_to_object": NodeType.POINT_TO_OBJECT,
}


class OrchestratorPlanner:
    """Skill-focused planner — static one-shot and agentic iterative modes.

    Initialisation:
        planner = OrchestratorPlanner(gemini_client, runs_dir="…/runs")

    The `runs_dir` is used to bootstrap the ExemplarStore with historical
    successful plans for few-shot in-context learning.
    """

    def __init__(
        self,
        gemini: OrchestratorGeminiClient,
        runs_dir: str = "",
    ) -> None:
        self._gemini = gemini
        self._retriever = SkillRetriever(PRIMITIVE_SKILL_CATALOG)
        self._exemplars = ExemplarStore(runs_dir=runs_dir)

    # ═══════════════════════════════════════════════════════════════════════
    #  Public API
    # ═══════════════════════════════════════════════════════════════════════

    async def plan(self, instruction: str, cell_state: dict[str, Any]) -> PlanResult:
        """Create an initial plan for the given instruction.

        Routing:
          JOG        → fast-path jog parser (no perception needed)
          SORTING    → agentic loop (variable object count, unknown termination)
          everything → static skill sequence via task-type-aware Gemini prompt
        """
        if not await self.should_orchestrate(instruction, cell_state):
            raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)

        # Fast-path: jog commands
        if self._is_jog_command(instruction):
            return await self._plan_jog(instruction)

        # Classify task type first — drives everything downstream
        task_type = self._retriever.classify_task_type(instruction)

        # Sorting / variable-count tasks → always agentic
        if task_type == TaskType.SORTING or self._needs_agentic_loop(instruction):
            return PlanResult(
                subgoals=[{"id": "agentic_loop", "description": instruction}],
                assumptions=[
                    f"Task classified as {task_type.value} — "
                    "requires dynamic observe-reason-act loop"
                ],
                nodes=[],
                is_agentic=True,
            )

        # Build a richer static plan prompt
        prompt = self._build_static_prompt(instruction, task_type, cell_state)

        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception as exc:
            logger.warning("Gemini static planning failed (%s), using fallback", exc)
            raw = self._fallback_plan(instruction, task_type)

        skills = raw.get("skills") or []
        assumptions = raw.get("assumptions") or []

        if not isinstance(skills, list) or len(skills) == 0:
            skills = self._fallback_plan(instruction, task_type).get("skills", [])

        # Enforce ER pipeline: inject capture_image → analyze_scene → plan_trajectory
        # before any robot motion skill when they are absent.
        skills = self._enforce_er_pipeline(skills, instruction)

        # Validate plan constraints and log any issues
        valid, issues = self._retriever.validate_plan(skills)
        if not valid:
            logger.warning(
                "Plan validation issues for %r: %s", instruction, issues
            )
            assumptions = list(assumptions) + [f"⚠ Constraint issue: {i}" for i in issues]

        nodes = self._skills_to_nodes(skills)
        subgoals = [
            {
                "id": f"step_{i + 1}",
                "skill": s.get("skill"),
                "description": s.get("description", ""),
            }
            for i, s in enumerate(skills)
        ]
        return PlanResult(
            subgoals=subgoals,
            assumptions=assumptions,
            nodes=nodes,
            is_agentic=False,
        )

    async def plan_next_step(
        self,
        goal: str,
        scene_analysis: dict[str, Any],
        history: list[dict[str, Any]],
        cell_state: dict[str, Any],
        iteration: int,
    ) -> MicroPlan:
        """Decide the NEXT single action for the agentic observe-reason-act loop.

        Called repeatedly by the engine until task_complete=True.
        Returns a MicroPlan with either skills for one micro-task OR task_complete.
        """
        prompt = self._build_agentic_step_prompt(
            goal=goal,
            scene_analysis=scene_analysis,
            history=history,
            cell_state=cell_state,
            iteration=iteration,
        )

        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception as exc:
            logger.warning("Gemini plan_next_step failed (%s), using fallback", exc)
            return self._fallback_micro_plan(goal, scene_analysis, history, iteration)

        skills = raw.get("skills") or []
        skills = self._enforce_er_pipeline(skills, goal)
        return MicroPlan(
            task_complete=bool(raw.get("task_complete", False)),
            reasoning=str(raw.get("reasoning", "")),
            skills=skills,
            progress=raw.get("progress") or {},
            scene_summary=str(raw.get("scene_summary", "")),
        )

    def micro_plan_to_nodes(
        self, micro_plan: MicroPlan, iteration: int
    ) -> list[NodePlan]:
        """Convert a MicroPlan's skills into executable NodePlan objects."""
        return self._skills_to_nodes(micro_plan.skills, prefix=f"iter{iteration}")

    async def replan(
        self,
        instruction: str,
        previous_subgoals: list[dict[str, Any]],
        note: str,
        cell_state: dict[str, Any],
    ) -> PlanResult:
        """Regenerate plan after failure, clarification, or goal change."""
        task_type = self._retriever.classify_task_type(instruction)
        skills_text = self._retriever.format_skills_for_prompt(
            self._retriever.get_relevant_skills(instruction, top_k=12)
        )
        all_names = json.dumps(self._retriever.get_all_skill_names())

        prompt = f"""You are replanning a robotics task after a failure or goal change.

## Available Skills (most relevant)
{skills_text}

## Context
Original instruction: {instruction!r}
Operator note: {note!r}
Previous steps attempted: {json.dumps(previous_subgoals, default=str)}
Cell state: {json.dumps(cell_state, default=str)}
Task type detected: {TASK_TYPE_LABELS.get(task_type, task_type.value)}

## Rules
- Adapt based on the failure reason in the operator note
- Return STRICT JSON: {{"reasoning": str, "assumptions": [], "skills": []}}
- Each skill: {{"skill": str, "params": object, "description": str}}
- Allowed skill names: {all_names}
- Return JSON only.
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception as exc:
            logger.warning("Gemini replan failed (%s), using fallback", exc)
            raw = self._fallback_plan(instruction, task_type)

        skills = raw.get("skills") or []
        assumptions = raw.get("assumptions") or []
        if not isinstance(skills, list) or len(skills) == 0:
            if not self._looks_like_robot_task(instruction):
                raise ValueError(NON_ACTIONABLE_TASK_MESSAGE)
            skills = self._fallback_plan(instruction, task_type).get("skills", [])

        nodes = self._skills_to_nodes(skills)
        subgoals = [
            {
                "id": f"step_{i + 1}",
                "skill": s.get("skill"),
                "description": s.get("description", ""),
            }
            for i, s in enumerate(skills)
        ]
        return PlanResult(subgoals=subgoals, assumptions=assumptions, nodes=nodes)

    # ── Exemplar store public API ────────────────────────────────────────

    def add_exemplar(
        self,
        instruction: str,
        skill_sequence: list[dict[str, Any]],
        run_id: str = "",
    ) -> None:
        """Store a successful plan as a few-shot exemplar for future planning."""
        task_type = self._retriever.classify_task_type(instruction)
        self._exemplars.add(
            instruction=instruction,
            skill_sequence=skill_sequence,
            run_id=run_id,
            task_type=task_type.value,
        )

    # ═══════════════════════════════════════════════════════════════════════
    #  Intent detection
    # ═══════════════════════════════════════════════════════════════════════

    async def should_orchestrate(
        self, instruction: str, cell_state: dict[str, Any]
    ) -> bool:
        """Heuristic intent router: ORCHESTRATE vs CELL_MANAGER.

        Uses keyword matching only — no LLM call — so routing is instant and
        never times out regardless of Gemini availability.
        """
        text = (instruction or "").strip()
        if not text:
            return False

        # Explicit cell-manager-only patterns (status / health queries)
        cell_manager_kw = re.compile(
            r"\b(?:status|health|diagnostic|connectivity|connection|ping|"
            r"uptime|version|config(?:uration)?|setting)\b",
            re.IGNORECASE,
        )
        # If the message ONLY contains cell-manager keywords and no action verbs, don't orchestrate
        if cell_manager_kw.search(text) and not ACTION_VERB_PATTERN.search(text):
            return False

        return self._looks_like_robot_task(text)

    # ── ER pipeline enforcement ──────────────────────────────────────────────

    _MOTION_SKILLS = {"move_to_pose", "execute_xy_action", "move_joints"}
    _ER_PERCEPTION_SKILLS = {"capture_image", "analyze_scene", "plan_trajectory"}

    @classmethod
    def _enforce_er_pipeline(
        cls, skills: list[dict], instruction: str
    ) -> list[dict]:
        """Guarantee that any plan containing robot motion uses the ER model.

        Rules enforced (in order):
        1. If the plan has motion skills (move_to_pose / execute_xy_action /
           move_joints) but no plan_trajectory → inject the full ER pipeline
           (capture_image → analyze_scene → plan_trajectory) before the first
           motion skill.
        2. If plan_trajectory is present but analyze_scene is absent → inject
           capture_image + analyze_scene before plan_trajectory.
        3. If analyze_scene is present but capture_image is absent → inject
           capture_image before analyze_scene.

        This ensures the ER model (gemini-robotics-er-1.5-preview) is always
        called for any spatial or manipulation task.
        """
        skill_names = [s.get("skill", "") for s in skills]

        has_motion = any(n in cls._MOTION_SKILLS for n in skill_names)
        has_plan_traj = "plan_trajectory" in skill_names
        has_analyze = "analyze_scene" in skill_names
        has_capture = "capture_image" in skill_names

        if not has_motion:
            # No robot motion — only enforce capture_image before analyze_scene
            if has_analyze and not has_capture:
                idx = next(i for i, s in enumerate(skills) if s.get("skill") == "analyze_scene")
                skills.insert(idx, {
                    "skill": "capture_image",
                    "params": {},
                    "description": "Capture current scene (injected for ER)",
                })
                logger.info("ER enforcement: injected capture_image before analyze_scene")
            return skills

        # Motion task — full ER pipeline required
        if not has_plan_traj:
            # Find insertion point: before the first motion skill
            first_motion = next(
                i for i, s in enumerate(skills) if s.get("skill") in cls._MOTION_SKILLS
            )
            er_prefix: list[dict] = []
            if not has_capture:
                er_prefix.append({
                    "skill": "capture_image",
                    "params": {},
                    "description": "Capture scene for ER analysis",
                })
            if not has_analyze:
                er_prefix.append({
                    "skill": "analyze_scene",
                    "params": {"query": f"Locate all objects relevant to: {instruction}"},
                    "description": "Analyze scene with ER model",
                })
            er_prefix.append({
                "skill": "plan_trajectory",
                "params": {
                    "task": instruction,
                    "num_points": 15,
                },
                "description": "Plan robot trajectory using Gemini ER 1.5",
            })
            for item in reversed(er_prefix):
                skills.insert(first_motion, item)
            logger.info(
                "ER enforcement: injected %s before first motion skill",
                [e["skill"] for e in er_prefix],
            )
        else:
            # plan_trajectory present — ensure capture_image and analyze_scene precede it
            pt_idx = next(i for i, s in enumerate(skills) if s.get("skill") == "plan_trajectory")
            pre_pt = [s.get("skill") for s in skills[:pt_idx]]
            if "analyze_scene" not in pre_pt:
                skills.insert(pt_idx, {
                    "skill": "analyze_scene",
                    "params": {"query": f"Locate all objects relevant to: {instruction}"},
                    "description": "Analyze scene with ER model",
                })
                pt_idx += 1
                logger.info("ER enforcement: injected analyze_scene before plan_trajectory")
            if "capture_image" not in [s.get("skill") for s in skills[:pt_idx]]:
                ci_idx = next(
                    (i for i, s in enumerate(skills) if s.get("skill") == "analyze_scene"),
                    pt_idx,
                )
                skills.insert(ci_idx, {
                    "skill": "capture_image",
                    "params": {},
                    "description": "Capture scene for ER analysis",
                })
                logger.info("ER enforcement: injected capture_image before analyze_scene")

        return skills

    @staticmethod
    def _looks_like_robot_task(instruction: str) -> bool:
        return bool(ACTION_VERB_PATTERN.search((instruction or "").lower()))

    @classmethod
    def looks_like_robot_task(cls, instruction: str) -> bool:
        return cls._looks_like_robot_task(instruction)

    @staticmethod
    def _is_jog_command(instruction: str) -> bool:
        return bool(_JOG_PATTERN.search(instruction or ""))

    def _needs_agentic_loop(self, instruction: str) -> bool:
        """True when instruction implies variable-count / adaptive iteration."""
        task_type = self._retriever.classify_task_type(instruction)
        if task_type == TaskType.SORTING:
            return True
        # Also catch explicit agentic keywords for COMPOSITE tasks
        agentic_kw = re.compile(
            r"\b(?:all|every|each|remaining|until|repeat|keep|continuous|batch"
            r"|multiple|several|various)\w*\b",
            re.IGNORECASE,
        )
        return bool(agentic_kw.search(instruction or ""))

    # ═══════════════════════════════════════════════════════════════════════
    #  Prompt construction (task-type-aware)
    # ═══════════════════════════════════════════════════════════════════════

    def _build_static_prompt(
        self,
        instruction: str,
        task_type: TaskType,
        cell_state: dict[str, Any],
    ) -> str:
        """Build the task-type-aware static planning prompt."""

        # Retrieve only the most relevant skills (not all of them)
        relevant_skills = self._retriever.get_relevant_skills(instruction, top_k=12)
        skills_text = self._retriever.format_skills_for_prompt(relevant_skills)
        skill_names = json.dumps([s.name for s in relevant_skills])

        # Canonical chain for this task type
        canonical_chain = self._retriever.get_canonical_chain(task_type)
        task_label = TASK_TYPE_LABELS.get(task_type, task_type.value)

        # Retrieve similar past plans for few-shot injection
        exemplars = self._exemplars.retrieve(instruction, top_k=3)
        exemplars_text = self._exemplars.format_for_prompt(exemplars)
        exemplars_block = (
            f"\n## Similar Past Plans (Few-Shot Examples)\n{exemplars_text}"
            if exemplars_text
            else ""
        )

        # Task-type-specific guidance block
        type_guidance = _STATIC_GUIDANCE.get(task_type, _STATIC_GUIDANCE[TaskType.COMPOSITE])

        return f"""You are a precision robotics skill planner. \
Decompose the goal into a minimal, ordered sequence of PRIMITIVE SKILLS.

## Task Analysis
Instruction: {instruction!r}
Detected task type: {task_label}
Canonical skill chain for this type: {canonical_chain}
Cell state: {json.dumps(cell_state, default=str)}
{exemplars_block}
## Available Skills (most relevant for this task type)
{skills_text}

## Task-Type Guidance
{type_guidance}

## Universal Constraints (ALWAYS enforce)
- plan_trajectory is the ONLY way to plan robot motion paths — never hardcode Cartesian poses
- execute_xy_action MUST follow plan_trajectory in the same plan
- suction_on MUST be paired with suction_off
- Always end manipulation tasks with verify_outcome
- Never emit template placeholders like "{{{{...}}}}"
- For non-string params (arrays, booleans, numbers), provide concrete JSON values

## Output Format
Return STRICT JSON with exactly these keys:
{{
  "task_type": "{task_type.value}",
  "reasoning": "<1-2 sentences: what you plan to do and why>",
  "assumptions": ["<assumption>", ...],
  "skills": [
    {{"skill": "<name>", "params": {{}}, "description": "<what this step achieves>"}},
    ...
  ]
}}
Allowed skill names: {skill_names}
Return JSON only — no markdown, no explanation outside the JSON.
"""

    def _build_agentic_step_prompt(
        self,
        goal: str,
        scene_analysis: dict[str, Any],
        history: list[dict[str, Any]],
        cell_state: dict[str, Any],
        iteration: int,
    ) -> str:
        """Build the agentic single-step prompt with skill retrieval + exemplars."""

        relevant_skills = self._retriever.get_relevant_skills(goal, top_k=14)
        skills_text = self._retriever.format_skills_for_prompt(relevant_skills)
        skill_names = json.dumps([s.name for s in relevant_skills])

        history_summary = self._summarize_history(history)

        # Retrieve similar exemplars for few-shot guidance
        exemplars = self._exemplars.retrieve(goal, top_k=2)
        exemplars_text = self._exemplars.format_for_prompt(exemplars)
        exemplars_block = (
            f"\n## Similar Past Executions\n{exemplars_text}"
            if exemplars_text
            else ""
        )

        return f"""You are an intelligent robotics agent executing a multi-step task \
using an observe-reason-act loop. Decide the NEXT SINGLE ACTION based on the \
current scene and what has already been done.

## Goal
{goal!r}

## Current Scene (captured THIS iteration — use this, not history)
{json.dumps(scene_analysis, default=str)}

## Execution History (last 10 actions)
{history_summary}

## Cell State
{json.dumps(cell_state, default=str)}

## Iteration
{iteration}
{exemplars_block}
## Available Skills (most relevant for this goal)
{skills_text}

## Skill Patterns (guidance, not templates)
- Perception only → capture_image → analyze_scene → llm_reason
- Single pick → plan_trajectory → estimate_grasp_pose → move_to_pose (approach)
  → move_to_pose (descend) → suction_on → move_to_pose (lift)
  → move_to_pose (target) → suction_off → verify_outcome
- XY planar move → capture_image → plan_trajectory → execute_xy_action → verify_outcome
- Point to object → point_to_object(object_description="...")
- Failure recovery → choose a different object or adapt approach before retrying

## Rules
1. Return STRICT JSON:
   {{
     "task_complete": bool,          // true ONLY if the ENTIRE goal is achieved
     "reasoning": str,               // what you see + why you chose this action
     "scene_summary": str,           // brief description of current scene
     "progress": {{"completed": int, "estimated_remaining": int, "notes": str}},
     "skills": [                     // EXACTLY ONE logical action (or [] if complete)
       {{"skill": str, "params": {{}}, "description": str}}
     ]
   }}
2. task_complete=true → skills=[]
3. task_complete=false → plan EXACTLY ONE logical action
4. Use CURRENT scene positions — do NOT reuse positions from history
5. If a prior action failed, adapt: try a different object or approach angle
6. Include actual values from scene analysis in params (bbox, positions)
7. Allowed skill names: {skill_names}
8. Return JSON only.
"""

    # ═══════════════════════════════════════════════════════════════════════
    #  Jog planning
    # ═══════════════════════════════════════════════════════════════════════

    async def _plan_jog(self, instruction: str) -> PlanResult:
        prompt = f"""You are a robotics joint-jog parser.
The robot has 6 joints: j0 (base), j1 (shoulder), j2 (elbow), \
j3 (wrist1), j4 (wrist2), j5 (wrist3).
Return STRICT JSON: \
{{"offsets_deg": [6 floats], "velocity": float 0.1-2.0, "acceleration": float 0.1-2.0}}
Clamp all offsets to [-45, 45]. Return JSON only.

Instruction: {instruction!r}
"""
        try:
            raw = await self._gemini.generate_json(prompt)
        except Exception:
            raw = self._fallback_jog_parse(instruction)

        offsets = raw.get("offsets_deg", [0, 0, 0, 0, 0, 0])
        if not isinstance(offsets, list) or len(offsets) != 6:
            offsets = [0, 0, 0, 0, 0, 0]
        offsets = [max(-45.0, min(45.0, float(o))) for o in offsets]

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
                "description": instruction,
            }
        ]
        nodes = self._skills_to_nodes(skills)
        return PlanResult(
            subgoals=[
                {"id": "jog_1", "skill": "jog_joints", "description": instruction}
            ],
            assumptions=[f"Jog offsets: {offsets} deg"],
            nodes=nodes,
        )

    @staticmethod
    def _fallback_jog_parse(instruction: str) -> dict[str, Any]:
        lower = instruction.lower()
        deg_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:degree|deg|°)", lower)
        deg_val = float(deg_match.group(1)) if deg_match else 5.0
        deg_val = max(-45.0, min(45.0, deg_val))

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
    #  Fallback plans (Gemini unavailable)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _fallback_plan(
        instruction: str, task_type: TaskType | None = None
    ) -> dict[str, Any]:
        lower = (instruction or "").lower()

        if task_type == TaskType.NARRATION or any(
            w in lower for w in ("commentary", "commentat", "narrat", "live", "stream")
        ):
            return {
                "assumptions": ["Fallback: live narration task"],
                "skills": [
                    {"skill": "capture_image", "params": {}, "description": "Capture current scene"},
                    {"skill": "analyze_scene", "params": {"query": "Describe everything visible in the robotic cell"}, "description": "Analyze scene"},
                    {"skill": "live_narrate", "params": {"prompt": instruction, "include_scene_context": True}, "description": "Generate commentary"},
                ],
            }

        if task_type == TaskType.PERCEPTION or any(
            w in lower
            for w in ("what", "where", "how many", "describe", "check", "inspect",
                      "scan", "look", "find", "detect", "count", "read", "identify")
        ):
            return {
                "assumptions": ["Fallback: perception-only task"],
                "skills": [
                    {"skill": "capture_image", "params": {}, "description": "Capture scene"},
                    {"skill": "analyze_scene", "params": {"query": instruction}, "description": "Analyze with VLM"},
                    {"skill": "llm_reason", "params": {"prompt": f"Summarize: {instruction}", "response_format": "text"}, "description": "Summarize"},
                ],
            }

        if task_type == TaskType.XY_MOTION:
            return {
                "assumptions": ["Fallback: XY motion task"],
                "skills": [
                    {"skill": "capture_image", "params": {}, "description": "Capture scene"},
                    {"skill": "plan_trajectory", "params": {"task": instruction, "num_points": 15}, "description": "Plan trajectory"},
                    {"skill": "execute_xy_action", "params": {}, "description": "Execute XY motion"},
                    {"skill": "verify_outcome", "params": {"expected_state": "motion completed"}, "description": "Verify"},
                ],
            }

        # Default: pick-and-place
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
                reasoning="No objects detected. Assuming task is complete.",
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
                {"skill": "plan_trajectory", "params": {"task": f"pick {object_label} and move to target", "object_label": object_label, "num_points": 15}, "description": f"Plan trajectory for {object_label}"},
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

    # ═══════════════════════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _summarize_history(history: list[dict[str, Any]]) -> str:
        if not history:
            return "No actions taken yet."
        lines: list[str] = []
        for i, entry in enumerate(history[-10:], start=1):
            status = entry.get("status", "UNKNOWN")
            desc = entry.get("description", entry.get("name", f"step_{i}"))
            error = entry.get("error")
            if isinstance(error, str) and error:
                lines.append(f"  {i}. [{status}] {desc} (error: {error})")
            else:
                lines.append(f"  {i}. [{status}] {desc}")
        total = len(history)
        if total > 10:
            lines.insert(0, f"  (showing last 10 of {total} actions)")
        return "\n".join(lines)

    def _skills_to_nodes(
        self, skills: list[dict[str, Any]], prefix: str = "step"
    ) -> list[NodePlan]:
        nodes: list[NodePlan] = []
        for idx, skill_dict in enumerate(skills, start=1):
            skill_name = skill_dict.get("skill", "")
            node_type = SKILL_TO_NODE_TYPE.get(skill_name)
            if node_type is None:
                logger.warning("Unknown skill %r in plan — skipping", skill_name)
                continue

            timeout_ms = _skill_timeout(node_type)
            nodes.append(
                NodePlan(
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
                )
            )

        if prefix == "step":
            nodes.append(
                NodePlan(
                    name="summary",
                    type=NodeType.SUMMARY_NODE,
                    payload={},
                    timeout_ms=10000,
                )
            )

        return nodes


# ── Timeout table ─────────────────────────────────────────────────────────────

def _skill_timeout(node_type: NodeType) -> int:
    if node_type in (
        NodeType.MOVE_TO_POSE,
        NodeType.EXECUTE_XY_ACTION,
        NodeType.MOVE_JOINTS,
        NodeType.POINT_TO_OBJECT,
    ):
        return 45000
    if node_type in (NodeType.WAIT, NodeType.WAIT_DIGITAL_INPUT):
        return 60000
    if node_type == NodeType.PLAN_TRAJECTORY:
        return 60000
    if node_type in (
        NodeType.CAPTURE_IMAGE,
        NodeType.GET_ROBOT_STATE,
        NodeType.SUCTION_ON,
        NodeType.SUCTION_OFF,
    ):
        return 10000
    return 30000


# ── Task-type specific guidance blocks ───────────────────────────────────────
# Injected into the planning prompt to provide domain-specific rules.

_STATIC_GUIDANCE: dict[TaskType, str] = {
    TaskType.PERCEPTION: """\
- This is a PERCEPTION task (visual query — ER model analyzes the scene)
- ALWAYS: capture_image → analyze_scene(query=<user question>) → llm_reason
- analyze_scene uses Gemini Robotics-ER 1.5 for spatial grounding and object detection
- Do NOT include motion or actuation skills unless the user explicitly asks to move
- analyze_scene query should directly answer the user's question""",

    TaskType.PICK_AND_PLACE: """\
- This is a PICK_AND_PLACE task — Gemini Robotics-ER 1.5 MUST be used for all spatial steps
- MANDATORY sequence (do not skip any step):
  capture_image
  → analyze_scene(query="locate <object> and identify <target zone>")   [ER model]
  → plan_trajectory(task="pick <object> and place at <target>")          [ER model]
  → estimate_grasp_pose(bbox={{analyze_scene.objects[0].bbox}})
  → move_to_pose(approach, motion_type=joint)
  → move_to_pose(descend, motion_type=linear)
  → suction_on
  → move_to_pose(lift, motion_type=linear)
  → move_to_pose(transit to target, motion_type=joint)
  → suction_off
  → verify_outcome
- plan_trajectory is the ONLY way to plan motion — never hardcode Cartesian poses
- estimate_grasp_pose bbox comes from analyze_scene output: {{analyze_scene.objects[0].bbox}}""",

    TaskType.XY_MOTION: """\
- This is an XY_MOTION task (planar 2D, Z height fixed) — ER model plans the path
- MANDATORY sequence:
  capture_image
  → analyze_scene(query="identify objects and target position")           [ER model]
  → plan_trajectory(task="<describe the motion>")                        [ER model]
  → execute_xy_action
  → verify_outcome
- execute_xy_action MUST follow plan_trajectory — it consumes ER waypoints directly
- execute_xy_action does NOT move Z""",

    TaskType.SORTING: """\
- This is a SORTING task — the engine will use the agentic loop
- Each iteration MUST use ER: capture_image → analyze_scene (ER) → plan one pick
- Use plan_trajectory (ER) for every motion step in the iteration""",

    TaskType.IO_CONTROL: """\
- This is an IO_CONTROL task (direct actuator or digital pin control)
- Use suction_on/suction_off for pneumatic gripper, set_digital_output for IO pins
- If the task needs spatial context first, prepend capture_image → analyze_scene (ER)
- Use wait_digital_input to wait for sensor signals""",

    TaskType.NARRATION: """\
- This is a NARRATION task (live visual commentary using ER model)
- MANDATORY sequence:
  capture_image
  → analyze_scene(query="describe everything visible in the workspace") [ER model]
  → live_narrate(prompt=<user instruction>, include_scene_context=True)
- Do NOT include motion or actuation skills""",

    TaskType.JOG: """\
- This is a JOG task (relative joint offset only — no perception needed)
- Use ONLY jog_joints with the parsed degree offsets
- Clamp offsets to [-45, 45] degrees per joint""",

    TaskType.COMPOSITE: """\
- This is a COMPOSITE or unclassified task — apply ER model for all spatial steps
- For any motion: capture_image → analyze_scene (ER) → plan_trajectory (ER) → execute
- plan_trajectory (ER) is MANDATORY before any move_to_pose or execute_xy_action
- End manipulation tasks with verify_outcome""",
}
