"""MoveToPose skill — move TCP to a Cartesian pose with linear or joint interpolation."""

from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class MoveToPoseParams(BaseModel):
    """Parameters for move_to_pose."""

    pose: list[float] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Target pose [x, y, z, rx, ry, rz] in meters and radians.",
    )
    velocity: float = Field(
        default=0.25,
        ge=0.01,
        le=2.0,
        description="Motion velocity (m/s for linear, rad/s for joint).",
    )
    acceleration: float = Field(
        default=1.2,
        ge=0.01,
        le=3.0,
        description="Motion acceleration.",
    )
    motion_type: str = Field(
        default="linear",
        description="Interpolation type: 'linear' (straight-line TCP path) or 'joint' (fastest joint path).",
    )


@register_skill
class MoveToPoseSkill(Skill[MoveToPoseParams]):
    """Move robot TCP to a Cartesian pose using linear or joint interpolation."""

    name = "move_to_pose"
    executor_type = "robot"
    description = (
        "Move robot TCP to a Cartesian pose [x,y,z,rx,ry,rz]. "
        "Supports 'linear' (straight-line) or 'joint' (fastest path) interpolation."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return MoveToPoseParams

    async def validate(self, params: MoveToPoseParams) -> tuple[bool, Optional[str]]:
        if params.motion_type not in ("linear", "joint"):
            return False, f"motion_type must be 'linear' or 'joint', got '{params.motion_type}'"
        return True, None

    async def execute(
        self, params: MoveToPoseParams, context: ExecutionContext
    ) -> SkillResult:
        robot = context.get_executor("robot")

        if not robot.is_ready():
            return SkillResult.fail("Robot not ready")

        if params.motion_type == "linear":
            success = await robot.move_linear(
                pose=params.pose,
                acceleration=params.acceleration,
                velocity=params.velocity,
            )
        else:
            # Joint-space move to Cartesian target — use movej with pose
            # UR robots accept movej with pose argument (IK solved internally)
            import math

            success = await robot.move_joint(
                target_rad=params.pose,  # UR movej accepts pose as well
                acceleration=params.acceleration,
                velocity=params.velocity,
                tolerance_rad=math.radians(1.0),
            )

        if success:
            return SkillResult.ok({
                "target_pose": params.pose,
                "motion_type": params.motion_type,
                "reached": True,
            })
        else:
            return SkillResult.fail(
                f"Failed to reach pose via {params.motion_type}",
                {"target_pose": params.pose, "motion_type": params.motion_type, "reached": False},
            )
