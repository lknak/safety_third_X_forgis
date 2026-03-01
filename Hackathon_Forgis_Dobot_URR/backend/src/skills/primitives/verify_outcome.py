"""VerifyOutcome skill — post-action visual verification via camera + VLM."""

import base64
import time
from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class VerifyOutcomeParams(BaseModel):
    """Parameters for verify_outcome."""

    expected_state: str = Field(
        ...,
        min_length=1,
        description="Natural-language description of the expected outcome (e.g. 'the red box is in Zone B').",
    )
    image_b64: Optional[str] = Field(
        default=None,
        description="Optional base64-encoded image. If omitted, a fresh frame is captured.",
    )


@register_skill
class VerifyOutcomeSkill(Skill[VerifyOutcomeParams]):
    """Post-action verification using camera + Gemini VLM."""

    name = "verify_outcome"
    executor_type = "camera"
    description = (
        "Capture an image and ask Gemini VLM whether the expected state has been achieved. "
        "Returns verified (bool), reasoning, and confidence."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return VerifyOutcomeParams

    async def validate(self, params: VerifyOutcomeParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: VerifyOutcomeParams, context: ExecutionContext
    ) -> SkillResult:
        from orchestrator.gemini_client import OrchestratorGeminiClient

        # Get image
        image_bytes: Optional[bytes] = None
        if params.image_b64:
            image_bytes = base64.b64decode(params.image_b64)
        else:
            try:
                camera = context.get_executor("camera")
                if camera.is_ready():
                    image_bytes = camera.get_snapshot_jpeg(quality=90)
            except Exception:
                pass

        prompt = f"""You are verifying the outcome of a robotic operation.
Analyze the image and determine whether the following expected state is achieved:

Expected state: {params.expected_state!r}

Return STRICT JSON with keys:
- verified: bool (true if the expected state is achieved, false otherwise)
- confidence: float 0.0-1.0 (how confident you are in the assessment)
- reasoning: str (brief explanation of your assessment)

Return JSON only.
"""

        gemini = OrchestratorGeminiClient()
        try:
            response = await gemini.analyze_er(prompt=prompt, image_bytes=image_bytes)
        except Exception as exc:
            return SkillResult.fail(f"Verification failed: {exc}")

        verified = response.get("verified", False)
        confidence = float(response.get("confidence", 0.0))
        reasoning = response.get("reasoning", "")

        result = {
            "verified": verified,
            "confidence": confidence,
            "reasoning": reasoning,
            "expected_state": params.expected_state,
            "timestamp": time.time(),
        }

        context.set_variable("last_verification", result)

        if verified:
            return SkillResult.ok(result)
        else:
            return SkillResult.fail(
                f"Verification failed: {reasoning}",
                result,
            )
