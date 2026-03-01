"""GetRobotState skill — read current robot state snapshot."""

from typing import Optional

from pydantic import BaseModel

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class GetRobotStateParams(BaseModel):
    """Parameters for get_robot_state (none required)."""

    pass


@register_skill
class GetRobotStateSkill(Skill[GetRobotStateParams]):
    """Read current robot joint positions, TCP pose, and digital IO status."""

    name = "get_robot_state"
    executor_type = "robot"
    description = "Read current robot state: joint positions, TCP pose, digital IO, readiness."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return GetRobotStateParams

    async def validate(self, params: GetRobotStateParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: GetRobotStateParams, context: ExecutionContext
    ) -> SkillResult:
        robot = context.get_executor("robot")

        is_ready = robot.is_ready()
        joint_deg = robot.get_joint_positions_deg() if is_ready else None
        state_summary = robot.get_state_summary() if hasattr(robot, "get_state_summary") else {}

        result = {
            "is_ready": is_ready,
            "joint_positions_deg": joint_deg,
            "state_summary": state_summary,
        }

        # Store for downstream skills
        context.set_variable("robot_state", result)

        return SkillResult.ok(result)
