"""DepthEstimation skill — estimate 3D depth from monocular camera via Gemini ER."""

from typing import Optional
import base64
import json
import logging

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill

logger = logging.getLogger(__name__)


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
    """Estimate 3D depth of an object from monocular camera using Gemini ER spatial reasoning."""

    name = "depth_estimation"
    executor_type = "camera"
    description = (
        "Estimate 3D depth of an object from monocular camera using Gemini ER spatial reasoning. "
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

        min_z = float(os.environ.get("SAFE_Z_MIN", "0.05"))
        max_z = float(os.environ.get("SAFE_Z_MAX", "0.45"))
        default_grasp_z = float(os.environ.get("DEFAULT_GRASP_Z", "0.12"))
        safety_margin = float(os.environ.get("SAFETY_MARGIN_Z", "0.03"))

        # Resolve image bytes for ER model
        image_bytes: Optional[bytes] = None
        if params.image_b64 and len(params.image_b64) > 100:
            try:
                image_bytes = base64.b64decode(params.image_b64)
            except Exception:
                image_bytes = None

        if image_bytes is None:
            image_bytes = context.get_variable("last_image_bytes")

        # Auto-capture if no image available
        if image_bytes is None:
            try:
                camera = context.get_executor("camera")
                if camera.is_ready():
                    jpeg = camera.get_snapshot_jpeg(quality=90)
                    if jpeg:
                        image_bytes = jpeg
                        context.set_variable("last_image_bytes", jpeg)
                        context.set_variable(
                            "last_image_b64",
                            base64.b64encode(jpeg).decode("utf-8"),
                        )
            except Exception:
                pass

        # Try Gemini ER for real spatial depth estimation
        er_result = None
        if image_bytes is not None:
            try:
                from orchestrator.gemini_client import OrchestratorGeminiClient

                gemini = OrchestratorGeminiClient()

                bbox_info = ""
                if params.bbox:
                    bbox_info = f"\nTarget object bounding box: {json.dumps(params.bbox)}"

                prompt = f"""You are Gemini Robotics ER performing monocular depth estimation 
for a robot manipulation task.

Analyze the image and estimate the 3D depth of the target object from the camera's perspective.
The robot workspace has these constraints:
- Z range (height above table): {min_z}m to {max_z}m
- Typical grasp heights: small objects ~0.08m, medium ~0.12m, large ~0.18m
- Safety margin: {safety_margin}m

Object class: {params.object_class!r}{bbox_info}

Return STRICT JSON:
{{
  "estimated_depth_m": float (height of object surface above table in meters),
  "object_height_m": float (estimated object height),
  "confidence": float (0-1),
  "spatial_notes": str (brief observations about object placement and surroundings)
}}
Return JSON only."""

                raw = await gemini.analyze_er(prompt=prompt, image_bytes=image_bytes)
                er_result = raw
                logger.info("ER depth estimation result: %s", raw)
            except Exception as exc:
                logger.warning("Gemini ER depth estimation failed (%s), using calibration fallback", exc)

        # Extract depth from ER result or use calibration fallback
        if er_result and isinstance(er_result, dict):
            grasp_z = float(er_result.get("estimated_depth_m", default_grasp_z))
            grasp_z = min(max(grasp_z, min_z), max_z)
            method = "gemini_er_spatial"
            confidence = float(er_result.get("confidence", 0.7))
            spatial_notes = str(er_result.get("spatial_notes", ""))
        else:
            grasp_z = min(max(default_grasp_z, min_z), max_z)
            method = "calibration_fallback"
            confidence = 0.3
            spatial_notes = "Using calibration defaults — no ER model available or image missing"

        approach_z = min(grasp_z + safety_margin + 0.05, max_z)

        result = {
            "estimated_depth_m": grasp_z,
            "approach_z": approach_z,
            "z_clamp": {"min": min_z, "max": max_z},
            "method": method,
            "confidence": confidence,
            "object_class": params.object_class,
            "spatial_notes": spatial_notes,
        }

        context.set_variable("last_depth_estimation", result)

        return SkillResult.ok(result)
