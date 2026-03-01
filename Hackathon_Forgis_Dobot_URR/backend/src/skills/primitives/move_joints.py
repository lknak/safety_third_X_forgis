"""MoveJoints skill — move robot to explicit joint positions."""

import math
from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class MoveJointsParams(BaseModel):
    """Parameters for move_joints."""

    joint_positions_deg: list[float] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Target joint positions in degrees [j0, j1, j2, j3, j4, j5].",
    )
    velocity: float = Field(
        default=1.05,
        ge=0.1,
        le=2.0,
        description="Joint velocity in rad/s.",
    )
    acceleration: float = Field(
        default=1.4,
        ge=0.1,
        le=2.0,
        description="Joint acceleration in rad/s².",
    )


@register_skill
class MoveJointsSkill(Skill[MoveJointsParams]):
    """Move robot to explicit joint positions in degrees."""

    name = "move_joints"
    executor_type = "robot"
    description = "Move robot to explicit joint positions [j0..j5] in degrees."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return MoveJointsParams

    async def validate(self, params: MoveJointsParams) -> tuple[bool, Optional[str]]:
        for i, deg in enumerate(params.joint_positions_deg):
            if not -360.0 <= deg <= 360.0:
                return False, f"Joint {i} ({deg}°) outside limits [-360, 360]"
        return True, None

    async def execute(
        self, params: MoveJointsParams, context: ExecutionContext
    ) -> SkillResult:
        robot = context.get_executor("robot")

        if not robot.is_ready():
            return SkillResult.fail("Robot not ready")

        target_rad = [math.radians(d) for d in params.joint_positions_deg]

        success = await robot.move_joint(
            target_rad=target_rad,
            acceleration=params.acceleration,
            velocity=params.velocity,
            tolerance_rad=math.radians(1.0),
        )

        if success:
            return SkillResult.ok({
                "target_joints_deg": params.joint_positions_deg,
                "reached": True,
            })
        else:
            return SkillResult.fail(
                "Failed to reach target joint positions",
                {"target_joints_deg": params.joint_positions_deg, "reached": False},
            )
