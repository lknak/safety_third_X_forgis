"""EstimateGraspPose skill — convert 2D bbox to 3D robot-frame grasp pose."""

from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class EstimateGraspPoseParams(BaseModel):
    """Parameters for estimate_grasp_pose."""

    bbox: dict = Field(
        ...,
        description=(
            "Bounding box dictionary. Supported formats: "
            "{x,y,width,height} (normalized 0-1 or 0-1000) OR "
            "{box_2d:[ymin,xmin,ymax,xmax]} in Gemini ER 0-1000 format."
        ),
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

    @staticmethod
    def _normalize_bbox(bbox: dict) -> tuple[float, float, float, float]:
        """Return normalized (x, y, width, height) in 0..1."""
        if isinstance(bbox.get("box_2d"), list) and len(bbox["box_2d"]) == 4:
            ymin, xmin, ymax, xmax = [float(v) for v in bbox["box_2d"]]
            x = (xmin + xmax) / 2.0
            y = (ymin + ymax) / 2.0
            width = max(0.0, xmax - xmin)
            height = max(0.0, ymax - ymin)
        else:
            x = float(bbox.get("x", 0.5))
            y = float(bbox.get("y", 0.5))
            width = float(bbox.get("width", 0.1))
            height = float(bbox.get("height", 0.1))

        # Convert 0..1000 ER coordinates to 0..1.
        if max(abs(x), abs(y), abs(width), abs(height)) > 1.5:
            x /= 1000.0
            y /= 1000.0
            width /= 1000.0
            height /= 1000.0

        return (
            min(max(x, 0.0), 1.0),
            min(max(y, 0.0), 1.0),
            min(max(width, 0.0), 1.0),
            min(max(height, 0.0), 1.0),
        )

    async def validate(self, params: EstimateGraspPoseParams) -> tuple[bool, Optional[str]]:
        has_xywh = {"x", "y", "width", "height"}.issubset(params.bbox.keys())
        has_box2d = isinstance(params.bbox.get("box_2d"), list) and len(params.bbox["box_2d"]) == 4
        if not has_xywh and not has_box2d:
            return False, "bbox must include {x,y,width,height} or {box_2d:[ymin,xmin,ymax,xmax]}"
        return True, None

    async def execute(
        self, params: EstimateGraspPoseParams, context: ExecutionContext
    ) -> SkillResult:
        import os

        bbox = params.bbox
        x_norm, y_norm, width_norm, height_norm = self._normalize_bbox(bbox)

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
            "normalized_bbox": {
                "x": round(x_norm, 5),
                "y": round(y_norm, 5),
                "width": round(width_norm, 5),
                "height": round(height_norm, 5),
            },
            "workspace": {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max},
            "z_clamp": {"min": min_z, "max": max_z},
        }

        # Store in context for robot execution nodes
        context.set_variable("last_grasp_pose", grasp_pose)
        context.set_variable("last_approach_pose", approach_pose)
        context.set_variable("last_place_pose", place_pose)

        return SkillResult.ok(result)
