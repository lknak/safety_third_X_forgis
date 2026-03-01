"""LLMReason skill — general-purpose Gemini call for mid-flow reasoning."""

from typing import Any, Optional
import base64
import re

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill

_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def _resolve_path(root: Any, path: str) -> Any:
    """Resolve dotted path from dict-like / object-like roots."""
    current = root
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current.get(part)
            continue
        if hasattr(current, part):
            current = getattr(current, part)
            continue
        return None
    return current


def _resolve_prompt_template(prompt: str, context: ExecutionContext) -> tuple[str, list[str]]:
    """
    Resolve {{path}} placeholders from flow variables.

    Supported forms:
    - {{var_name}}
    - {{var_name.nested.key}}
    """

    unresolved: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        token = match.group(1).strip()
        if not token:
            unresolved.append(token)
            return match.group(0)

        head = token.split(".", 1)[0]
        base = context.get_variable(head)
        if base is None:
            unresolved.append(token)
            return match.group(0)

        value = _resolve_path(base, token[len(head) + 1 :]) if "." in token else base
        if value is None:
            unresolved.append(token)
            return match.group(0)

        if isinstance(value, (dict, list)):
            return str(value)
        return str(value)

    rendered = _TEMPLATE_PATTERN.sub(_replace, prompt)
    return rendered, unresolved


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
        resolved_prompt, unresolved_tokens = _resolve_prompt_template(params.prompt, context)

        # If image is provided or requested, use ER model for vision
        image_bytes: Optional[bytes] = None
        if params.image_b64 and len(params.image_b64) > 100:
            try:
                image_bytes = base64.b64decode(params.image_b64)
            except Exception:
                image_bytes = None
        if image_bytes is None and params.model == "er":
            # Fall back to last captured image
            image_bytes = context.get_variable("last_image_bytes")

        try:
            if image_bytes:
                response = await gemini.analyze_er(
                    prompt=resolved_prompt, image_bytes=image_bytes
                )
            elif params.response_format == "json":
                try:
                    response = await gemini.generate_json(resolved_prompt)
                except Exception:
                    # Graceful fallback: avoid failing the entire run if model emits text.
                    text = await gemini.generate_text(resolved_prompt)
                    response = {"text": text}
            else:
                text = await gemini.generate_text(resolved_prompt)
                response = {"text": text}
        except Exception as exc:
            return SkillResult.fail(f"LLM reasoning failed: {exc}")

        # Store reasoning result for downstream use
        context.set_variable("last_reasoning", response)

        return SkillResult.ok({
            "response": response,
            "model": params.model or "default",
            "format": params.response_format,
            "resolved_prompt": resolved_prompt,
            "unresolved_placeholders": unresolved_tokens,
        })
