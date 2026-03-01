"""SuctionOff skill — release pneumatic vacuum gripper."""

from typing import Optional

from pydantic import BaseModel

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class SuctionOffParams(BaseModel):
    """Parameters for suction_off (none required)."""

    pass


@register_skill
class SuctionOffSkill(Skill[SuctionOffParams]):
    """Release the pneumatic suction gripper (vacuum off)."""

    name = "suction_off"
    executor_type = "hand"
    description = "Release the pneumatic suction gripper (vacuum off) to place an object."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return SuctionOffParams

    async def validate(self, params: SuctionOffParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: SuctionOffParams, context: ExecutionContext
    ) -> SkillResult:
        gripper = context.get_executor("hand")

        if not gripper.is_ready():
            return SkillResult.fail("Gripper executor not ready (is the robot connected?)")

        try:
            success = await gripper.open()  # open = vacuum off for suction
            if success:
                return SkillResult.ok({"state": "suction_released"})
            else:
                return SkillResult.fail("Failed to release suction")
        except Exception as e:
            return SkillResult.fail(f"Suction release error: {e}")
