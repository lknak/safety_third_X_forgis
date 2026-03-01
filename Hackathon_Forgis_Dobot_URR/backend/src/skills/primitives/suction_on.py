"""SuctionOn skill — activate pneumatic vacuum gripper."""

from typing import Optional

from pydantic import BaseModel

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class SuctionOnParams(BaseModel):
    """Parameters for suction_on (none required)."""

    pass


@register_skill
class SuctionOnSkill(Skill[SuctionOnParams]):
    """Activate the pneumatic suction gripper (vacuum on)."""

    name = "suction_on"
    executor_type = "hand"
    description = "Activate the pneumatic suction gripper (vacuum on) to grasp an object."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return SuctionOnParams

    async def validate(self, params: SuctionOnParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: SuctionOnParams, context: ExecutionContext
    ) -> SkillResult:
        gripper = context.get_executor("hand")

        if not gripper.is_ready():
            return SkillResult.fail("Gripper executor not ready (is the robot connected?)")

        try:
            success = await gripper.close()  # close = vacuum on for suction
            if success:
                return SkillResult.ok({"state": "suction_active"})
            else:
                return SkillResult.fail("Failed to activate suction")
        except Exception as e:
            return SkillResult.fail(f"Suction error: {e}")
