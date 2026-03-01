"""LiveNarrate skill — real-time voice commentary via Gemini Live with image context."""

from typing import Optional
import base64
import logging

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill

logger = logging.getLogger(__name__)


class LiveNarrateParams(BaseModel):
    """Parameters for live_narrate."""

    prompt: str = Field(
        default="Describe the current robotic operation in one concise sentence.",
        description="Commentary prompt for Gemini Live video narration.",
    )
    image_b64: Optional[str] = Field(
        default=None,
        description="Optional base64-encoded image for visual context.",
    )
    include_scene_context: bool = Field(
        default=True,
        description="If True, automatically include the last captured image and scene analysis.",
    )


@register_skill
class LiveNarrateSkill(Skill[LiveNarrateParams]):
    """Generate real-time visual commentary using Gemini Live with image context."""

    name = "live_narrate"
    executor_type = "camera"
    description = (
        "Generate concise live commentary from the latest camera frame using Gemini Live. "
        "Use this for operator narration, not for object detection or trajectory planning."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return LiveNarrateParams

    async def validate(self, params: LiveNarrateParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: LiveNarrateParams, context: ExecutionContext
    ) -> SkillResult:
        from orchestrator.gemini_client import OrchestratorGeminiClient

        gemini = OrchestratorGeminiClient()

        # Gather image context
        image_bytes: Optional[bytes] = None
        if params.image_b64 and len(params.image_b64) > 100:
            try:
                image_bytes = base64.b64decode(params.image_b64)
            except Exception:
                image_bytes = None  # Invalid base64, fall through
        elif params.include_scene_context:
            image_bytes = context.get_variable("last_image_bytes")

        # Auto-capture if we need visual context but don't have it
        if image_bytes is None and params.include_scene_context:
            try:
                camera = context.get_executor("camera")
                if camera.is_ready():
                    jpeg = camera.get_snapshot_jpeg(quality=70)
                    if jpeg:
                        image_bytes = jpeg
            except Exception:
                pass

        # Build enriched prompt with scene context
        scene_analysis = context.get_variable("last_scene_analysis")
        scene_context = ""
        if scene_analysis and isinstance(scene_analysis, dict):
            answer = scene_analysis.get("answer", "")
            objects = scene_analysis.get("objects", [])
            if answer:
                scene_context += f"\nScene observation: {answer}"
            if objects and isinstance(objects, list):
                labels = [str(o.get("label", "unknown")) for o in objects[:5] if isinstance(o, dict)]
                scene_context += f"\nVisible objects: {', '.join(labels)}"

        enriched_prompt = (
            "You are a robotics operator assistant. "
            "Return exactly one short sentence describing what is happening now. "
            "Do not invent unseen objects.\n\n"
            f"Instruction: {params.prompt}"
        )
        if scene_context:
            enriched_prompt += f"\n\nContext from latest scene analysis:{scene_context}"

        try:
            commentary_text = await gemini.live_commentary(
                enriched_prompt,
                image_bytes=image_bytes,
            )
        except Exception as exc:
            logger.warning("Live narration failed: %s", exc)
            return SkillResult.fail(f"Live narration failed: {exc}")

        # Encode text as placeholder audio (real audio integration would use TTS)
        audio_b64 = base64.b64encode(commentary_text.encode("utf-8")).decode("utf-8")

        return SkillResult.ok({
            "commentary_text": commentary_text,
            "audio_chunk_b64": audio_b64,
            "had_visual_context": image_bytes is not None,
            "model_path": "live",
        })
