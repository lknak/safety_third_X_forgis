"""In-context learning exemplar store for the orchestrator planner.

Stores successful (instruction → skill_sequence) pairs and retrieves
the most similar ones to inject as few-shot examples into planning prompts.

This implements In-Context Exemplar Learning (ICEL):
  - After every successful run, the plan is stored as an exemplar
  - On new planning requests, the top-K most similar past plans are
    retrieved using Jaccard token similarity and injected into the prompt
  - The LLM can then learn patterns from real-world successful plans
    without any weight updates (pure in-context learning)

References:
  - Brown et al. "Language Models are Few-Shot Learners" (GPT-3, 2020)
  - Liu et al. "What Makes Good In-Context Examples for GPT-3?" (2022)
  - Shi et al. "Large Language Models are Easily Distracted by Irrelevant
    Context" (2023) — motivates selective, similarity-based retrieval
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Exemplar:
    """A single successful (instruction, plan) pair for few-shot injection."""

    instruction: str
    task_type: str
    skills_used: list[str]
    skill_sequence: list[dict[str, Any]]  # [{skill, description}] — no stale params
    run_id: str = ""

    def to_prompt_text(self) -> str:
        """Format as a readable few-shot example for LLM prompt injection."""
        steps: list[str] = []
        for i, s in enumerate(self.skill_sequence, 1):
            skill = s.get("skill", "?")
            desc = s.get("description", "")
            steps.append(f"    {i}. {skill}: {desc}")
        steps_text = "\n".join(steps)
        return f'Task: "{self.instruction}"\nSkill sequence:\n{steps_text}'


class ExemplarStore:
    """Lightweight in-context learning store for successful orchestrator plans.

    On startup, exemplars are bootstrapped from persisted run JSON files in
    `runs_dir`. New exemplars are added via `add()` after each successful run.
    Retrieval uses Jaccard token similarity for fast, dependency-free matching.
    """

    def __init__(self, runs_dir: str, max_exemplars: int = 40) -> None:
        self._runs_dir = Path(runs_dir)
        self._max = max_exemplars
        self._exemplars: list[Exemplar] = []
        self._load_from_runs()

    # ── Bootstrap from persisted runs ────────────────────────────────────

    def _load_from_runs(self) -> None:
        """Load exemplars from persisted run JSON files (success only)."""
        if not str(self._runs_dir) or not self._runs_dir.exists():
            return

        paths = sorted(
            self._runs_dir.glob("flow_*.json"),
            key=lambda p: p.stat().st_mtime,
        )

        loaded = 0
        for path in paths:
            if loaded >= self._max:
                break
            try:
                with open(path, encoding="utf-8") as f:
                    run = json.load(f)
                if run.get("final_status") != "SUCCESS":
                    continue
                ex = self._extract_from_run(run)
                if ex is not None:
                    self._exemplars.append(ex)
                    loaded += 1
            except Exception as exc:
                logger.debug("Skipping exemplar from %s: %s", path.name, exc)

        logger.info(
            "ExemplarStore: bootstrapped %d exemplars from %s",
            loaded,
            self._runs_dir,
        )

    def _extract_from_run(self, run: dict[str, Any]) -> Exemplar | None:
        """Extract a reusable exemplar from a run record dict."""
        instruction = (run.get("instruction") or "").strip()
        if not instruction:
            return None

        nodes: list[dict[str, Any]] = run.get("nodes", [])
        skill_sequence: list[dict[str, Any]] = []

        for node in nodes:
            artifacts = node.get("artifacts", {})
            skill_name = artifacts.get("skill_name", "")
            if not skill_name:
                continue
            # Strip raw params to avoid stale bbox / pose data polluting examples
            skill_sequence.append(
                {
                    "skill": skill_name,
                    "description": artifacts.get("description", ""),
                }
            )

        if not skill_sequence:
            return None

        return Exemplar(
            instruction=instruction,
            task_type="",
            skills_used=[s["skill"] for s in skill_sequence],
            skill_sequence=skill_sequence,
            run_id=run.get("flow_id", ""),
        )

    # ── Write ─────────────────────────────────────────────────────────────

    def add(
        self,
        instruction: str,
        skill_sequence: list[dict[str, Any]],
        run_id: str = "",
        task_type: str = "",
    ) -> None:
        """Store a newly completed successful plan as an exemplar.

        Deduplicates by instruction text (case-insensitive) to avoid
        flooding the store with repeated identical tasks.
        """
        instruction = (instruction or "").strip()
        if not instruction or not skill_sequence:
            return

        skills_used = [
            s.get("skill", "") for s in skill_sequence if s.get("skill")
        ]
        if not skills_used:
            return

        # Deduplicate: skip if an exemplar for this instruction already exists
        norm = instruction.lower()
        if any(ex.instruction.lower() == norm for ex in self._exemplars):
            return

        # Strip params to keep exemplars portable
        clean_seq = [
            {"skill": s.get("skill", ""), "description": s.get("description", "")}
            for s in skill_sequence
            if s.get("skill")
        ]

        ex = Exemplar(
            instruction=instruction,
            task_type=task_type,
            skills_used=skills_used,
            skill_sequence=clean_seq,
            run_id=run_id,
        )
        self._exemplars.append(ex)

        # Trim to max capacity (evict oldest)
        if len(self._exemplars) > self._max:
            self._exemplars = self._exemplars[-self._max :]

    # ── Retrieve ──────────────────────────────────────────────────────────

    def retrieve(self, instruction: str, top_k: int = 3) -> list[Exemplar]:
        """Return top-k most similar exemplars using Jaccard token similarity.

        Only exemplars with ≥15% token overlap are returned to ensure
        the few-shot examples are genuinely relevant.
        """
        if not self._exemplars:
            return []

        words = frozenset(re.findall(r"\b\w+\b", instruction.lower()))
        scored: list[tuple[float, Exemplar]] = []

        for ex in self._exemplars:
            ex_words = frozenset(re.findall(r"\b\w+\b", ex.instruction.lower()))
            union = words | ex_words
            inter = words & ex_words
            score = len(inter) / max(len(union), 1)
            scored.append((score, ex))

        scored.sort(key=lambda x: -x[0])
        return [ex for score, ex in scored[:top_k] if score >= 0.15]

    def format_for_prompt(self, exemplars: list[Exemplar]) -> str:
        """Format exemplars as a numbered few-shot block for LLM injection."""
        if not exemplars:
            return ""
        sections = [
            f"Example {i + 1}:\n{ex.to_prompt_text()}"
            for i, ex in enumerate(exemplars)
        ]
        return "\n\n".join(sections)

    @property
    def count(self) -> int:
        return len(self._exemplars)
