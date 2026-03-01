"""Generate trajectory skill using Physical AI Node (Gemini + Depth)."""

from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class GenerateTrajectoryParams(BaseModel):
    """Parameters for the generate_trajectory skill."""

    task_prompt: str = Field(
        ...,
        description="High-level goal for the AI (e.g. '1. Locate the robot gripper...' )",
    )
    use_depth_estimation: bool = Field(
        default=True,
        description="Whether to run Depth estimation concurrently.",
    )
    current_pose: Optional[dict] = Field(
        default=None,
        description="The XYZ position dict of the UR arm '{\"position\": {\"x\": 1, \"y\": 2, \"z\": 3}}'",
    )


@register_skill
class GenerateTrajectorySkill(Skill[GenerateTrajectoryParams]):
    """Generate dynamic trajectory waypoints using an AI node."""

    name = "generate_trajectory"
    executor_type = "physical_ai_node"
    description = "Create a robot trajectory using Gemini ER and depth estimation"

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return GenerateTrajectoryParams

    async def validate(self, params: GenerateTrajectoryParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: GenerateTrajectoryParams, context: ExecutionContext
    ) -> SkillResult:

        ai_executor = context.get_executor("physical_ai_node")

        if not ai_executor.is_ready():
            return SkillResult.fail("Physical AI executor not ready (no camera/models)")

        result = await ai_executor.generate_trajectory(
            prompt=params.task_prompt,
            use_depth=params.use_depth_estimation,
            current_pose=params.current_pose,
        )

        if result["success"]:
            return SkillResult.ok({
                "waypoints": result.get("waypoints", []),
                "coordinates": result.get("coordinates", {}),
                "depth_map_available": result.get("depth_map_available", False),
                "target_pose": result.get("target_pose", None)
            })
        else:
            return SkillResult.fail(
                result.get("error", "AI failed to generate trajectory"),
                {"waypoints": []},
            )
