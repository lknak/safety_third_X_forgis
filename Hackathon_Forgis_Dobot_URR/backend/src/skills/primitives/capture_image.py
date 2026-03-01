"""CaptureImage skill — grab a single RGB frame from the camera."""

from typing import Optional
import base64
import time

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class CaptureImageParams(BaseModel):
    """Parameters for capture_image."""

    resolution: Optional[str] = Field(
        default=None,
        description="Desired resolution hint ('480p', '720p', '1080p'). Camera native if omitted.",
    )


@register_skill
class CaptureImageSkill(Skill[CaptureImageParams]):
    """Capture a single RGB frame from the monocular camera."""

    name = "capture_image"
    executor_type = "camera"
    description = "Capture a single RGB frame from the camera and return it as base64 JPEG."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return CaptureImageParams

    async def validate(self, params: CaptureImageParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: CaptureImageParams, context: ExecutionContext
    ) -> SkillResult:
        camera = context.get_executor("camera")

        if not camera.is_ready():
            return SkillResult.fail("Camera not ready — no frames received yet")

        quality = 90
        jpeg_bytes = camera.get_snapshot_jpeg(quality=quality)
        if jpeg_bytes is None:
            return SkillResult.fail("Camera returned no frame")

        image_b64 = base64.b64encode(jpeg_bytes).decode("utf-8")

        # Store in context so downstream skills can reuse without re-capturing
        context.set_variable("last_image_b64", image_b64)
        context.set_variable("last_image_bytes", jpeg_bytes)

        return SkillResult.ok({
            "image_b64": image_b64,
            "timestamp": time.time(),
            "size_bytes": len(jpeg_bytes),
        })
