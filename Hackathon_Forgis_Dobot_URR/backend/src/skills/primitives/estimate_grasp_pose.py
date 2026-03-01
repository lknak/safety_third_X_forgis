"""EstimateGraspPose skill — convert 2D bbox to 3D robot-frame grasp pose."""

from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class EstimateGraspPoseParams(BaseModel):
    """Parameters for estimate_grasp_pose."""

    bbox: dict = Field(
        ...,
        description="Bounding box dict with keys x, y, width, height (pixel or normalized 0-1 coords).",
    )
    object_class: str = Field(
        default="object",
        description="Object class name for height/depth lookup (e.g. 'box', 'bottle').",
    )
    depth_hint_m: Optional[float] = Field(
        default=None,
        ge=0.01,
        le=0.5,
        description="Optional known object height in meters for depth estimation.",
    )


@register_skill
class EstimateGraspPoseSkill(Skill[EstimateGraspPoseParams]):
    """Convert a 2D detection into a 3D robot-frame grasp pose using workspace calibration."""

    name = "estimate_grasp_pose"
    executor_type = "camera"
    description = (
        "Convert 2D bounding box + object class into robot-frame 3D grasp, "
        "approach, and place poses using monocular depth estimation and workspace calibration."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return EstimateGraspPoseParams

    async def validate(self, params: EstimateGraspPoseParams) -> tuple[bool, Optional[str]]:
        required_keys = {"x", "y", "width", "height"}
        if not required_keys.issubset(params.bbox.keys()):
            return False, f"bbox must contain keys: {required_keys}"
        return True, None

    async def execute(
        self, params: EstimateGraspPoseParams, context: ExecutionContext
    ) -> SkillResult:
        import os

        bbox = params.bbox
        x_norm = float(bbox.get("x", 0.5))
        y_norm = float(bbox.get("y", 0.5))

        # Workspace calibration from environment or defaults
        x_min = float(os.environ.get("WORKSPACE_X_MIN", "-0.25"))
        x_max = float(os.environ.get("WORKSPACE_X_MAX", "0.25"))
        y_min = float(os.environ.get("WORKSPACE_Y_MIN", "-0.35"))
        y_max = float(os.environ.get("WORKSPACE_Y_MAX", "0.35"))
        min_z = float(os.environ.get("SAFE_Z_MIN", "0.05"))
        max_z = float(os.environ.get("SAFE_Z_MAX", "0.45"))
        safety_margin = float(os.environ.get("SAFETY_MARGIN_Z", "0.03"))

        # Object-class based grasp height (default or depth_hint)
        grasp_z = params.depth_hint_m or float(os.environ.get("DEFAULT_GRASP_Z", "0.12"))
        grasp_z = min(max(grasp_z, min_z), max_z)

        place_z = grasp_z + 0.04  # Slightly above grasp height
        place_z = min(place_z, max_z)

        # Convert normalized bbox center to robot XY
        x = x_min + (x_max - x_min) * x_norm
        y = y_min + (y_max - y_min) * y_norm

        # Standard downward orientation (tool pointing down)
        rx, ry, rz = 0.0, 3.14, 0.0

        grasp_pose = [x, y, grasp_z, rx, ry, rz]
        approach_pose = [x, y, min(grasp_z + safety_margin + 0.05, max_z), rx, ry, rz]
        place_pose = [x, y, place_z, rx, ry, rz]

        result = {
            "grasp_pose": grasp_pose,
            "approach_pose": approach_pose,
            "place_pose": place_pose,
            "object_class": params.object_class,
            "workspace": {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max},
            "z_clamp": {"min": min_z, "max": max_z},
        }

        # Store in context for robot execution nodes
        context.set_variable("last_grasp_pose", grasp_pose)
        context.set_variable("last_approach_pose", approach_pose)
        context.set_variable("last_place_pose", place_pose)

        return SkillResult.ok(result)
