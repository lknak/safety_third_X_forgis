"""LiveNarrate skill — real-time voice commentary via Gemini Live."""

from typing import Optional
import base64

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class LiveNarrateParams(BaseModel):
    """Parameters for live_narrate."""

    prompt: str = Field(
        default="Describe the current robotic operation in one concise sentence.",
        description="Commentary prompt for the live narration.",
    )
    image_b64: Optional[str] = Field(
        default=None,
        description="Optional base64-encoded image for visual context.",
    )


@register_skill
class LiveNarrateSkill(Skill[LiveNarrateParams]):
    """Generate real-time voice commentary using Gemini Live."""

    name = "live_narrate"
    executor_type = "camera"
    description = "Generate real-time voice commentary about the current operation using Gemini Live."

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

        try:
            commentary = await gemini.live_commentary(params.prompt)
        except Exception as exc:
            return SkillResult.fail(f"Live narration failed: {exc}")

        # Encode text as placeholder audio (real audio integration would use TTS)
        audio_b64 = base64.b64encode(commentary.encode("utf-8")).decode("utf-8")

        return SkillResult.ok({
            "commentary_text": commentary,
            "audio_chunk_b64": audio_b64,
        })
