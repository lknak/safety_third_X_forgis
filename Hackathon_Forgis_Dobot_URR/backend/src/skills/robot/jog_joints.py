"""JogJoints skill for relative joint movement."""

import math
from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class JogJointsParams(BaseModel):
    """Parameters for the jog_joints skill."""

    offsets_deg: list[float] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Relative offset for each joint in degrees [j0, j1, j2, j3, j4, j5]. "
        "Positive = CCW, negative = CW.",
    )
    acceleration: float = Field(
        default=0.5,
        ge=0.1,
        le=2.0,
        description="Joint acceleration in rad/s^2",
    )
    velocity: float = Field(
        default=0.5,
        ge=0.1,
        le=2.0,
        description="Joint velocity in rad/s",
    )
    tolerance_deg: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Position tolerance in degrees",
    )


@register_skill
class JogJointsSkill(Skill[JogJointsParams]):
    """Jog robot joints by relative offsets from current position."""

    name = "jog_joints"
    executor_type = "robot"
    description = (
        "Move robot joints by relative offsets in degrees from their current positions. "
        "Example: move every joint by +5 degrees, rotate joint 3 by -10 degrees."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return JogJointsParams

    async def validate(self, params: JogJointsParams) -> tuple[bool, Optional[str]]:
        max_single_jog = 45.0
        for i, offset in enumerate(params.offsets_deg):
            if abs(offset) > max_single_jog:
                return False, (
                    f"Joint {i} offset ({offset} deg) exceeds safety limit of "
                    f"+/-{max_single_jog} deg per jog"
                )
        return True, None

    async def execute(
        self, params: JogJointsParams, context: ExecutionContext
    ) -> SkillResult:
        robot_executor = context.get_executor("robot")

        current_deg = robot_executor.get_joint_positions_deg()
        if current_deg is None:
            return SkillResult.fail("Cannot read current joint positions")

        target_deg = [
            cur + off for cur, off in zip(current_deg, params.offsets_deg)
        ]

        # Clamp to safe limits
        for i, deg in enumerate(target_deg):
            if not -360.0 <= deg <= 360.0:
                return SkillResult.fail(
                    f"Joint {i} target ({deg:.1f} deg) outside [-360, 360] limits"
                )

        target_rad = [math.radians(d) for d in target_deg]
        tolerance_rad = math.radians(params.tolerance_deg)

        success = await robot_executor.jog_joint(
            target_rad=target_rad,
            acceleration=params.acceleration,
            velocity=params.velocity,
            tolerance_rad=tolerance_rad,
        )

        if success:
            return SkillResult.ok(
                {
                    "previous_deg": [round(d, 2) for d in current_deg],
                    "offsets_deg": params.offsets_deg,
                    "target_deg": [round(d, 2) for d in target_deg],
                    "reached": True,
                }
            )
        return SkillResult.fail(
            "Jog motion timed out or failed",
            {
                "previous_deg": [round(d, 2) for d in current_deg],
                "offsets_deg": params.offsets_deg,
                "target_deg": [round(d, 2) for d in target_deg],
                "reached": False,
            },
        )
