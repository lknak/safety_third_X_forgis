"""Skill system for flowdiagram execution."""

from .base import ExecutionContext, Skill, SkillResult
from .registry import get_skill, list_skills, register_skill

# Import subpackages to trigger @register_skill decorators
from . import camera  # noqa: F401
from . import hand  # noqa: F401
from . import io  # noqa: F401
from . import robot  # noqa: F401
from . import primitives  # noqa: F401  — primitive skills for the orchestrator

__all__ = [
    "ExecutionContext",
    "Skill",
    "SkillResult",
    "get_skill",
    "list_skills",
    "register_skill",
]

