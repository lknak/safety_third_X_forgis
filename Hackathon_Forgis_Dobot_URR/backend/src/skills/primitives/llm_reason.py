"""LLMReason skill — general-purpose Gemini call for mid-flow reasoning."""

from typing import Optional
import base64
import json

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class LLMReasonParams(BaseModel):
    """Parameters for llm_reason."""

    prompt: str = Field(
        ...,
        min_length=1,
        description="The reasoning prompt for Gemini.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Model variant: 'flash', 'pro', 'er'. Defaults to orchestrator model.",
    )
    response_format: Optional[str] = Field(
        default="json",
        description="Expected response format: 'json' or 'text'.",
    )
    image_b64: Optional[str] = Field(
        default=None,
        description="Optional base64-encoded image for vision queries.",
    )


@register_skill
class LLMReasonSkill(Skill[LLMReasonParams]):
    """General-purpose Gemini reasoning for planning, decisions, parsing, and branching."""

    name = "llm_reason"
    executor_type = "camera"  # lightweight — uses AI service, only needs camera for optional images
    description = (
        "General-purpose Gemini call for mid-flow reasoning: sub-goal planning, "
        "conditional branching, text parsing, error diagnosis, parameter generation."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return LLMReasonParams

    async def validate(self, params: LLMReasonParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: LLMReasonParams, context: ExecutionContext
    ) -> SkillResult:
        from orchestrator.gemini_client import OrchestratorGeminiClient

        gemini = OrchestratorGeminiClient()

        # If image is provided or requested, use ER model for vision
        image_bytes: Optional[bytes] = None
        if params.image_b64:
            image_bytes = base64.b64decode(params.image_b64)
        elif params.model == "er":
            # Fall back to last captured image
            image_bytes = context.get_variable("last_image_bytes")

        try:
            if image_bytes:
                response = await gemini.analyze_er(
                    prompt=params.prompt, image_bytes=image_bytes
                )
            elif params.response_format == "json":
                response = await gemini.generate_json(params.prompt)
            else:
                text = await gemini.generate_text(params.prompt)
                response = {"text": text}
        except Exception as exc:
            return SkillResult.fail(f"LLM reasoning failed: {exc}")

        # Store reasoning result for downstream use
        context.set_variable("last_reasoning", response)

        return SkillResult.ok({
            "response": response,
            "model": params.model or "default",
            "format": params.response_format,
        })
