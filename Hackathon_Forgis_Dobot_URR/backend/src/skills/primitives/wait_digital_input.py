"""WaitDigitalInput primitive skill — wait for a digital input signal."""

import asyncio
import time
from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class WaitDigitalInputParams(BaseModel):
    """Parameters for wait_digital_input."""

    pin: int = Field(
        ...,
        ge=0,
        le=7,
        description="Digital input pin number (0-7).",
    )
    expected_value: bool = Field(
        default=True,
        description="Expected pin value to wait for.",
    )
    timeout_ms: int = Field(
        default=10000,
        ge=100,
        le=60000,
        description="Maximum time to wait in milliseconds.",
    )


@register_skill
class WaitDigitalInputSkill(Skill[WaitDigitalInputParams]):
    """Wait for a digital input pin to reach an expected value."""

    name = "wait_digital_input"
    executor_type = "robot"
    description = "Wait for a digital input pin to reach an expected value (for sensors, external triggers)."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return WaitDigitalInputParams

    async def validate(self, params: WaitDigitalInputParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: WaitDigitalInputParams, context: ExecutionContext
    ) -> SkillResult:
        robot = context.get_executor("robot")

        if not robot.is_ready():
            return SkillResult.fail("Robot not ready")

        timeout_s = params.timeout_ms / 1000.0
        start = time.time()

        while (time.time() - start) < timeout_s:
            # Read digital input from robot state
            state = robot.get_state_summary() if hasattr(robot, "get_state_summary") else {}
            digital_inputs = state.get("digital_inputs", {})
            current_value = digital_inputs.get(params.pin, not params.expected_value)

            if current_value == params.expected_value:
                elapsed_ms = int((time.time() - start) * 1000)
                return SkillResult.ok({
                    "pin": params.pin,
                    "value": current_value,
                    "elapsed_ms": elapsed_ms,
                })

            await asyncio.sleep(0.1)

        return SkillResult.fail(
            f"Timeout waiting for DI[{params.pin}] == {params.expected_value}",
            {"pin": params.pin, "timeout_ms": params.timeout_ms},
        )
