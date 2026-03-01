"""JogJoints primitive skill — relative joint offsets from current position."""

import math
from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class JogJointsParams(BaseModel):
    """Parameters for jog_joints."""

    offsets_deg: list[float] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Relative offsets in degrees for each joint [j0..j5]. Use 0 for joints that should not move.",
    )
    velocity: float = Field(
        default=0.5,
        ge=0.1,
        le=2.0,
        description="Joint velocity in rad/s.",
    )
    acceleration: float = Field(
        default=0.5,
        ge=0.1,
        le=2.0,
        description="Joint acceleration in rad/s².",
    )


@register_skill
class JogJointsPrimitiveSkill(Skill[JogJointsParams]):
    """Apply relative joint offsets from the current position."""

    name = "jog_joints_primitive"
    executor_type = "robot"
    description = "Jog robot joints by relative offsets in degrees from current positions."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return JogJointsParams

    async def validate(self, params: JogJointsParams) -> tuple[bool, Optional[str]]:
        for i, offset in enumerate(params.offsets_deg):
            if not -45.0 <= offset <= 45.0:
                return False, f"Joint {i} offset ({offset}°) exceeds safe range [-45, 45]"
        return True, None

    async def execute(
        self, params: JogJointsParams, context: ExecutionContext
    ) -> SkillResult:
        robot = context.get_executor("robot")

        if not robot.is_ready():
            return SkillResult.fail("Robot not ready")

        current_deg = robot.get_joint_positions_deg()
        if current_deg is None:
            return SkillResult.fail("Cannot read current joint positions")

        target_deg = [cur + off for cur, off in zip(current_deg, params.offsets_deg)]

        # Safety check
        for i, d in enumerate(target_deg):
            if not -360.0 <= d <= 360.0:
                return SkillResult.fail(
                    f"Joint {i} target {d:.1f}° outside [-360, 360]",
                    {"previous_deg": current_deg, "offsets_deg": params.offsets_deg},
                )

        target_rad = [math.radians(d) for d in target_deg]

        success = await robot.jog_joint(
            target_rad=target_rad,
            acceleration=params.acceleration,
            velocity=params.velocity,
            tolerance_rad=math.radians(1.0),
        )

        result = {
            "previous_deg": [round(d, 2) for d in current_deg],
            "offsets_deg": params.offsets_deg,
            "target_deg": [round(d, 2) for d in target_deg],
        }

        if success:
            return SkillResult.ok({**result, "reached": True})
        else:
            return SkillResult.fail("Jog motion failed or timed out", {**result, "reached": False})
