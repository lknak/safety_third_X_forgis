"""Wait skill — pause execution for a duration or until a condition is met."""

import asyncio
import base64
import time
from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class WaitParams(BaseModel):
    """Parameters for wait."""

    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        le=60000,
        description="Fixed wait duration in milliseconds. If omitted, 'condition' must be provided.",
    )
    condition: Optional[str] = Field(
        default=None,
        description="Natural-language condition to wait for, evaluated via camera + LLM (e.g. 'the conveyor belt has stopped'). Polled every 2 seconds.",
    )
    max_condition_wait_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Maximum time to wait for condition to become true.",
    )


@register_skill
class WaitSkill(Skill[WaitParams]):
    """Pause execution for a fixed duration or until a natural-language condition is met."""

    name = "wait"
    executor_type = "camera"
    description = (
        "Pause execution for a fixed duration (ms) or until a natural-language condition "
        "is true (evaluated via camera + Gemini VLM). Use for settling time, adhesive curing, "
        "or waiting for external events."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return WaitParams

    async def validate(self, params: WaitParams) -> tuple[bool, Optional[str]]:
        if params.duration_ms is None and params.condition is None:
            return False, "Either 'duration_ms' or 'condition' must be provided"
        return True, None

    async def execute(
        self, params: WaitParams, context: ExecutionContext
    ) -> SkillResult:
        start = time.time()

        # Simple timed wait
        if params.duration_ms is not None and params.condition is None:
            await asyncio.sleep(params.duration_ms / 1000.0)
            return SkillResult.ok({"elapsed_ms": params.duration_ms, "mode": "timed"})

        # Condition-based wait (with optional initial delay)
        if params.duration_ms:
            await asyncio.sleep(params.duration_ms / 1000.0)

        if params.condition:
            from orchestrator.gemini_client import OrchestratorGeminiClient

            gemini = OrchestratorGeminiClient()
            timeout_s = params.max_condition_wait_ms / 1000.0
            poll_interval = 2.0

            while (time.time() - start) < timeout_s:
                # Capture fresh image
                image_bytes = None
                try:
                    camera = context.get_executor("camera")
                    if camera.is_ready():
                        image_bytes = camera.get_snapshot_jpeg(quality=70)
                except Exception:
                    pass

                prompt = f"""You are monitoring a robotic cell.
Answer STRICT JSON: {{"condition_met": true/false, "reasoning": "brief explanation"}}

Condition to check: {params.condition!r}
Return JSON only.
"""
                try:
                    response = await gemini.analyze_er(
                        prompt=prompt, image_bytes=image_bytes
                    )
                    if response.get("condition_met") is True:
                        elapsed = int((time.time() - start) * 1000)
                        return SkillResult.ok({
                            "elapsed_ms": elapsed,
                            "mode": "condition",
                            "condition": params.condition,
                            "reasoning": response.get("reasoning", ""),
                        })
                except Exception:
                    pass

                await asyncio.sleep(poll_interval)

            elapsed = int((time.time() - start) * 1000)
            return SkillResult.fail(
                f"Condition not met within {params.max_condition_wait_ms}ms: {params.condition}",
                {"elapsed_ms": elapsed, "condition": params.condition},
            )

        elapsed = int((time.time() - start) * 1000)
        return SkillResult.ok({"elapsed_ms": elapsed, "mode": "immediate"})
