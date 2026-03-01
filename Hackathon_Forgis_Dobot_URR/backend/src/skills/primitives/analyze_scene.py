"""AnalyzeScene skill — general-purpose VLM scene understanding via Gemini."""

from typing import Optional
import base64
import json
import time

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class AnalyzeSceneParams(BaseModel):
    """Parameters for analyze_scene."""

    query: str = Field(
        ...,
        min_length=1,
        description="Natural-language question or instruction for the VLM (e.g. 'locate the red box', 'count all items', 'read the label text').",
    )
    image_b64: Optional[str] = Field(
        default=None,
        description="Base64-encoded JPEG image. If omitted, the last captured image from context is used; if none exists, a fresh frame is captured.",
    )


@register_skill
class AnalyzeSceneSkill(Skill[AnalyzeSceneParams]):
    """Send an image + query to Gemini VLM for general scene understanding."""

    name = "analyze_scene"
    executor_type = "camera"
    description = (
        "Analyze the scene using Gemini VLM. Supports object detection, counting, "
        "anomaly detection, label/text reading, spatial relationship queries, and more."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return AnalyzeSceneParams

    async def validate(self, params: AnalyzeSceneParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: AnalyzeSceneParams, context: ExecutionContext
    ) -> SkillResult:
        from orchestrator.gemini_client import OrchestratorGeminiClient

        # Resolve image bytes
        image_bytes: Optional[bytes] = None
        if params.image_b64:
            image_bytes = base64.b64decode(params.image_b64)
        else:
            image_bytes = context.get_variable("last_image_bytes")

        # Auto-capture if we still don't have an image
        if image_bytes is None:
            try:
                camera = context.get_executor("camera")
                if camera.is_ready():
                    image_bytes = camera.get_snapshot_jpeg(quality=90)
                    if image_bytes:
                        context.set_variable("last_image_bytes", image_bytes)
                        context.set_variable(
                            "last_image_b64",
                            base64.b64encode(image_bytes).decode("utf-8"),
                        )
            except Exception:
                pass

        # Build ER prompt
        prompt = f"""You are an industrial robotics vision system.
Analyze the image and answer the query below. Return STRICT JSON with keys:
- objects: array of {{ "label": str, "bbox": {{ "x": float, "y": float, "width": float, "height": float }}, "confidence": float }}
- answer: str (concise answer to the query)
- spatial_relations: array of str (e.g. "red box is left of blue cylinder")

Query: {params.query!r}
Return JSON only.
"""

        gemini = OrchestratorGeminiClient()
        try:
            response = await gemini.analyze_er(prompt=prompt, image_bytes=image_bytes)
        except Exception as exc:
            return SkillResult.fail(f"VLM analysis failed: {exc}")

        # Store analysis for downstream use
        context.set_variable("last_scene_analysis", response)

        return SkillResult.ok({
            "analysis": response,
            "query": params.query,
            "timestamp": time.time(),
        })
