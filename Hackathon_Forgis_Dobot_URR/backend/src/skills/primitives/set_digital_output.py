"""SetDigitalOutput primitive skill — set any digital output pin."""

from typing import Optional

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill


class SetDigitalOutputParams(BaseModel):
    """Parameters for set_digital_output."""

    pin: int = Field(
        ...,
        ge=0,
        le=7,
        description="Digital output pin number (0-7).",
    )
    value: bool = Field(
        ...,
        description="Output value (true = HIGH, false = LOW).",
    )


@register_skill
class SetDigitalOutputSkill(Skill[SetDigitalOutputParams]):
    """Set a digital output pin to HIGH or LOW."""

    name = "set_digital_output"
    executor_type = "robot"
    description = "Set a digital output pin (0-7) to HIGH or LOW on the robot controller."

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return SetDigitalOutputParams

    async def validate(self, params: SetDigitalOutputParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: SetDigitalOutputParams, context: ExecutionContext
    ) -> SkillResult:
        robot = context.get_executor("robot")

        if not robot.is_ready():
            return SkillResult.fail("Robot not ready")

        try:
            await robot.set_digital_output(params.pin, params.value)
            return SkillResult.ok({"pin": params.pin, "value": params.value})
        except Exception as e:
            return SkillResult.fail(
                f"Failed to set digital output: {e}",
                {"pin": params.pin, "value": params.value},
            )
