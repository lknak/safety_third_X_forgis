"""Skill to close the pneumatic gripper."""

from pydantic import BaseModel
from typing import Optional

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill

class CloseGripperParams(BaseModel):
    """Parameters for the close_gripper skill (none required)."""
    pass

@register_skill
class CloseGripperSkill(Skill[CloseGripperParams]):
    """Close the pneumatic gripper."""

    name = "close_gripper"
    executor_type = "hand"
    description = "Close the pneumatic gripper by toggling the robot digital outputs."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return CloseGripperParams

    async def validate(self, params: CloseGripperParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: CloseGripperParams, context: ExecutionContext
    ) -> SkillResult:
        gripper_executor = context.get_executor()

        if not gripper_executor.is_ready():
            return SkillResult.fail("Gripper executor not ready (is the robot connected?)")

        try:
            success = await gripper_executor.close()
            if success:
                return SkillResult.ok({"state": "closed"})
            else:
                return SkillResult.fail("Failed to close pneumatic gripper (check DOUT configuration)")
        except Exception as e:
            return SkillResult.fail(f"Gripper error: {e}")
