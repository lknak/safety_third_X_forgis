"""PlanTrajectory skill — use Gemini ER to plan and visualize robot trajectories.

Gemini Robotics-ER 1.5 generates sequences of normalized [y, x] (0-1000)
trajectory points directly from an image + natural-language task prompt.
This skill:
  1. Sends the camera image + task to ER
  2. Gets trajectory waypoints back as JSON
  3. Overlays the trajectory on the image (circles + lines)
  4. Returns both the annotated image (base64) and the trajectory data
"""

from typing import Any, Optional
import base64
import io
import json
import logging
import time

from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill

logger = logging.getLogger(__name__)


class PlanTrajectoryParams(BaseModel):
    """Parameters for plan_trajectory."""

    task: str = Field(
        ...,
        min_length=1,
        description=(
            "Natural-language task description describing what the robot should do, "
            "e.g. 'move the red pen to the organizer on the left'."
        ),
    )
    num_points: int = Field(
        default=15,
        ge=3,
        le=50,
        description="Number of trajectory waypoints the ER model should generate.",
    )
    object_label: Optional[str] = Field(
        default=None,
        description="Optional object label to start the trajectory from (e.g. 'red pen').",
    )
    image_b64: Optional[str] = Field(
        default=None,
        description="Base64-encoded JPEG image.  If omitted, the last captured image is used.",
    )


def _overlay_trajectory(
    image_bytes: bytes,
    points: list[dict[str, Any]],
    img_format: str = "JPEG",
) -> bytes:
    """Draw trajectory points and connecting lines on the image.

    Points are in [y, x] format normalised to 0-1000.
    Returns the annotated image as bytes.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    # Try to get a font for labels — fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(12, min(w, h) // 50))
    except Exception:
        font = ImageFont.load_default()

    # Parse & sort points by label (trajectory order)
    parsed: list[tuple[int, float, float]] = []
    for pt in points:
        raw_pt = pt.get("point", [])
        if not isinstance(raw_pt, (list, tuple)) or len(raw_pt) < 2:
            continue
        y_norm, x_norm = float(raw_pt[0]), float(raw_pt[1])
        label = pt.get("label", "")
        try:
            order = int(label)
        except (ValueError, TypeError):
            order = len(parsed)
        px = x_norm / 1000.0 * w
        py = y_norm / 1000.0 * h
        parsed.append((order, px, py))

    parsed.sort(key=lambda t: t[0])

    if not parsed:
        return image_bytes  # nothing to draw

    # Draw connecting lines (gradient green→red)
    n = len(parsed)
    for i in range(n - 1):
        ratio = i / max(n - 2, 1)
        r = int(255 * ratio)
        g = int(255 * (1 - ratio))
        b = 0
        x1, y1 = parsed[i][1], parsed[i][2]
        x2, y2 = parsed[i + 1][1], parsed[i + 1][2]
        draw.line([(x1, y1), (x2, y2)], fill=(r, g, b), width=max(2, min(w, h) // 150))

    # Draw circles + labels at each waypoint
    radius = max(4, min(w, h) // 100)
    for order, px, py in parsed:
        # Start = bright green, end = bright red
        ratio = order / max(n - 1, 1) if n > 1 else 0
        r = int(255 * ratio)
        g = int(255 * (1 - ratio))
        fill_color = (r, g, 0)
        outline_color = (255, 255, 255)

        draw.ellipse(
            [px - radius, py - radius, px + radius, py + radius],
            fill=fill_color,
            outline=outline_color,
            width=2,
        )
        draw.text((px + radius + 2, py - radius), str(order), fill=(255, 255, 255), font=font)

    # Start / end markers
    if parsed:
        sx, sy = parsed[0][1], parsed[0][2]
        draw.text((sx - radius, sy - radius * 3), "START", fill=(0, 255, 0), font=font)
        ex, ey = parsed[-1][1], parsed[-1][2]
        draw.text((ex - radius, ey + radius + 2), "END", fill=(255, 0, 0), font=font)

    buf = io.BytesIO()
    img.save(buf, format=img_format, quality=92)
    return buf.getvalue()


@register_skill
class PlanTrajectorySkill(Skill[PlanTrajectoryParams]):
    """Plan a robot trajectory using Gemini Robotics-ER 1.5.

    The ER model generates a sequence of 2D waypoints directly from the
    camera image and a natural-language task description.  The waypoints
    are overlaid on the image so the operator can visualise the planned
    path before execution.
    """

    name = "plan_trajectory"
    executor_type = "camera"
    description = (
        "Use Gemini Robotics-ER to plan a trajectory for a manipulation task. "
        "Returns trajectory waypoints overlaid on the camera image and "
        "normalised 2D coordinates that can be converted to robot-frame poses."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return PlanTrajectoryParams

    async def validate(self, params: PlanTrajectoryParams) -> tuple[bool, Optional[str]]:
        return True, None

    async def execute(
        self, params: PlanTrajectoryParams, context: ExecutionContext
    ) -> SkillResult:
        from orchestrator.gemini_client import OrchestratorGeminiClient

        # ── Resolve image bytes ────────────────────────────────────────
        image_bytes: Optional[bytes] = None
        if params.image_b64 and len(params.image_b64) > 100:
            try:
                image_bytes = base64.b64decode(params.image_b64)
            except Exception:
                image_bytes = None

        if image_bytes is None:
            image_bytes = context.get_variable("last_image_bytes")

        # Auto-capture if we still have nothing
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

        if image_bytes is None:
            return SkillResult.fail("No image available for trajectory planning")

        # ── Build ER trajectory prompt (following official docs) ────────
        object_start = ""
        if params.object_label:
            object_start = f"Place a point on the {params.object_label}, then "
        else:
            object_start = "Place a point at the start position, then "

        prompt = f"""{object_start}{params.num_points} points for the trajectory of {params.task}.
The points should be labeled by order of the trajectory, from '0' (start point) to '{params.num_points}' (final point).
The answer should follow the json format:
[{{"point": <point>, "label": <label>}}, ...].
The points are in [y, x] format normalized to 0-1000."""

        # ── Call Gemini ER ─────────────────────────────────────────────
        gemini = OrchestratorGeminiClient()
        try:
            trajectory_points = await gemini.er_trajectory(
                prompt=prompt,
                image_bytes=image_bytes,
            )
        except Exception as exc:
            return SkillResult.fail(f"Gemini ER trajectory planning failed: {exc}")

        if not isinstance(trajectory_points, list) or len(trajectory_points) == 0:
            return SkillResult.fail("ER returned empty trajectory")

        # ── Overlay trajectory on image ────────────────────────────────
        try:
            annotated_bytes = _overlay_trajectory(image_bytes, trajectory_points)
            annotated_b64 = base64.b64encode(annotated_bytes).decode("utf-8")
        except Exception as exc:
            logger.warning("Trajectory overlay failed: %s", exc)
            annotated_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # ── Store results for downstream use ───────────────────────────
        context.set_variable("last_trajectory", trajectory_points)
        context.set_variable("last_trajectory_image_b64", annotated_b64)
        context.set_variable("last_image_b64", annotated_b64)  # show in chat

        result = {
            "trajectory_points": trajectory_points,
            "num_waypoints": len(trajectory_points),
            "task": params.task,
            "annotated_image_b64": annotated_b64,
            "timestamp": time.time(),
        }

        return SkillResult.ok(result)
