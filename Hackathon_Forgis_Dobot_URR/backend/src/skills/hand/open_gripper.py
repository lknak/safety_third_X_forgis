"""Skill to open the pneumatic gripper."""

from pydantic import BaseModel
from typing import Optional

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill

class OpenGripperParams(BaseModel):
    """Parameters for the open_gripper skill (none required)."""
    pass

@register_skill
class OpenGripperSkill(Skill[OpenGripperParams]):
    """Open the pneumatic gripper."""

    name = "open_gripper"
    executor_type = "hand"
    description = "Open the pneumatic gripper by toggling the robot digital outputs."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return OpenGripperParams

    async def validate(self, params: OpenGripperParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: OpenGripperParams, context: ExecutionContext
    ) -> SkillResult:
        gripper_executor = context.get_executor()

        if not gripper_executor.is_ready():
            return SkillResult.fail("Gripper executor not ready (is the robot connected?)")

        try:
            success = await gripper_executor.open()
            if success:
                return SkillResult.ok({"state": "open"})
            else:
                return SkillResult.fail("Failed to open pneumatic gripper (check DOUT configuration)")
        except Exception as e:
            return SkillResult.fail(f"Gripper error: {e}")
