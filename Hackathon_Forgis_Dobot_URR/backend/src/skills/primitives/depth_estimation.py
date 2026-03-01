"""DepthEstimation skill — estimate 3D depth from monocular camera (placeholder)."""

from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class DepthEstimationParams(BaseModel):
    """Parameters for depth_estimation."""

    bbox: Optional[dict] = Field(
        default=None,
        description="Bounding box dict {x, y, width, height} for the target object (normalized or pixel coords).",
    )
    object_class: str = Field(
        default="object",
        description="Object class name for depth lookup.",
    )
    image_b64: Optional[str] = Field(
        default=None,
        description="Optional base64-encoded image. Uses last captured image if omitted.",
    )


@register_skill
class DepthEstimationSkill(Skill[DepthEstimationParams]):
    """Estimate 3D depth of an object from monocular camera.

    Placeholder — implementation will use Gemini ER spatial reasoning
    or a learned monocular depth model.
    """

    name = "depth_estimation"
    executor_type = "camera"
    description = (
        "Estimate 3D depth of an object from monocular camera using VLM spatial reasoning. "
        "Returns estimated z-depth in robot frame."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return DepthEstimationParams

    async def validate(self, params: DepthEstimationParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: DepthEstimationParams, context: ExecutionContext
    ) -> SkillResult:
        import os

        # TODO: Replace with actual depth estimation (Gemini ER spatial / monocular depth model)
        # For now, use calibration-based heuristics from environment
        min_z = float(os.environ.get("SAFE_Z_MIN", "0.05"))
        max_z = float(os.environ.get("SAFE_Z_MAX", "0.45"))
        default_grasp_z = float(os.environ.get("DEFAULT_GRASP_Z", "0.12"))
        safety_margin = float(os.environ.get("SAFETY_MARGIN_Z", "0.03"))

        grasp_z = min(max(default_grasp_z, min_z), max_z)
        approach_z = min(grasp_z + safety_margin + 0.05, max_z)

        result = {
            "estimated_depth_m": grasp_z,
            "approach_z": approach_z,
            "z_clamp": {"min": min_z, "max": max_z},
            "method": "placeholder_calibration",
            "object_class": params.object_class,
        }

        context.set_variable("last_depth_estimation", result)

        return SkillResult.ok(result)
