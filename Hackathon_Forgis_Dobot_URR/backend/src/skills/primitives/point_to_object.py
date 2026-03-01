"""PointToObject skill — use Gemini ER 1.5 to locate an object and move the robot to it.

Two-phase operation:
  1. Send camera image + object description to Gemini Robotics-ER 1.5 which
     returns a normalised [y, x] point (0-1000) indicating the object centre.
  2. Convert the ER point to robot XY via the calibrated pixel→robot homography
     and execute a linear move while keeping Z and orientation locked.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import time
from typing import Any, Optional

import cv2
import numpy as np
from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill

# Re-use the same calibrated homography from execute_xy_action
from .execute_xy_action import (
    fallback_depth_from_plane,
    _normalized_yx_to_pixel,
    _resolve_reference_pose,
)

logger = logging.getLogger(__name__)


class PointToObjectParams(BaseModel):
    """Parameters for point_to_object."""

    object_description: str = Field(
        ...,
        min_length=1,
        description=(
            "Natural-language description of the object to point at, "
            "e.g. 'the red bottle', 'leftmost box', 'barcode label'."
        ),
    )
    image_b64: Optional[str] = Field(
        default=None,
        description=(
            "Base64-encoded JPEG image. If omitted, the last captured image "
            "from context is used; if none exists, a fresh frame is captured."
        ),
    )
    frame_width: int = Field(
        default=1920,
        ge=1,
        le=8192,
        description="Camera frame width in pixels (used for ER→pixel conversion).",
    )
    frame_height: int = Field(
        default=1080,
        ge=1,
        le=8192,
        description="Camera frame height in pixels (used for ER→pixel conversion).",
    )
    velocity: float = Field(
        default=0.12,
        ge=0.01,
        le=2.0,
        description="Linear motion velocity in m/s.",
    )
    acceleration: float = Field(
        default=0.6,
        ge=0.01,
        le=3.0,
        description="Linear motion acceleration in m/s².",
    )
    reference_pose: Optional[list[float]] = Field(
        default=None,
        min_length=6,
        max_length=6,
        description=(
            "Optional [x,y,z,rx,ry,rz] in metres/radians. "
            "If omitted, Z and orientation are read from the current TCP pose."
        ),
    )


def _overlay_point(
    image_bytes: bytes,
    point_yx: list[float],
    label: str,
    frame_w: int,
    frame_h: int,
) -> bytes:
    """Draw a crosshair + label on the image at the ER point."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    px = point_yx[1] / 1000.0 * w
    py = point_yx[0] / 1000.0 * h

    radius = max(8, min(w, h) // 60)
    line_len = radius * 2

    # Crosshair
    draw.line([(px - line_len, py), (px + line_len, py)], fill=(0, 255, 0), width=3)
    draw.line([(px, py - line_len), (px, py + line_len)], fill=(0, 255, 0), width=3)
    draw.ellipse(
        [px - radius, py - radius, px + radius, py + radius],
        outline=(0, 255, 0),
        width=3,
    )

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            max(14, min(w, h) // 40),
        )
    except Exception:
        font = ImageFont.load_default()

    draw.text((px + radius + 4, py - radius), label, fill=(0, 255, 0), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


@register_skill
class PointToObjectSkill(Skill[PointToObjectParams]):
    """Locate an object with ER 1.5 and move the robot to its XY position.

    Phase 1 — Perception (ER 1.5):
        Sends the camera image + object description to Gemini Robotics-ER.
        The model returns a single normalised [y, x] point (0-1000).

    Phase 2 — Motion (XY action):
        Converts the ER point to robot coordinates via calibrated homography
        and executes a linear move with Z/orientation locked.
    """

    name = "point_to_object"
    executor_type = "robot"
    description = (
        "Use Gemini Robotics-ER 1.5 to locate an object in the scene, then "
        "move the robot to the detected XY position while keeping Z and "
        "orientation fixed."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return PointToObjectParams

    async def validate(self, params: PointToObjectParams) -> tuple[bool, Optional[str]]:
        if not params.object_description.strip():
            return False, "object_description must not be empty"
        return True, None

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_er_point(response: dict | list) -> Optional[list[float]]:
        """Extract a single [y, x] point from the ER response.

        The model may return:
          • {"point": [y, x]}
          • [{"point": [y, x], "label": "..."}]
          • {"object": "...", "point": [y, x]}
        """
        if isinstance(response, list):
            # Take the first item
            if len(response) == 0:
                return None
            response = response[0]

        if isinstance(response, dict):
            raw = response.get("point")
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                try:
                    return [float(raw[0]), float(raw[1])]
                except (TypeError, ValueError):
                    return None
        return None

    # ── main execution ──────────────────────────────────────────────

    async def execute(
        self, params: PointToObjectParams, context: ExecutionContext
    ) -> SkillResult:
        from orchestrator.gemini_client import OrchestratorGeminiClient

        # ── Phase 0: Resolve image ─────────────────────────────────
        image_bytes: Optional[bytes] = None
        if params.image_b64 and len(params.image_b64) > 100:
            try:
                image_bytes = base64.b64decode(params.image_b64)
            except Exception:
                image_bytes = None

        if image_bytes is None:
            image_bytes = context.get_variable("last_image_bytes")

        # Auto-capture if still missing
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
            return SkillResult.fail("No image available — camera may not be connected")

        # ── Phase 1: Ask ER 1.5 for the object point ──────────────
        prompt = (
            f"Point to {params.object_description}.\n"
            "Return a single JSON object with the center point of the object.\n"
            'Format: {"point": [y, x], "label": "<object name>"}\n'
            "Coordinates are [y, x] normalised to 0-1000."
        )

        gemini = OrchestratorGeminiClient()
        try:
            er_response = await gemini.analyze_er(
                prompt=prompt,
                image_bytes=image_bytes,
            )
        except Exception as exc:
            return SkillResult.fail(f"Gemini ER 1.5 pointing failed: {exc}")

        logger.info("ER 1.5 point_to_object response: %s", er_response)

        point_yx = self._parse_er_point(er_response)
        if point_yx is None:
            return SkillResult.fail(
                f"Could not parse ER point from response: {er_response}"
            )

        # Validate range
        if not (0 <= point_yx[0] <= 1000 and 0 <= point_yx[1] <= 1000):
            return SkillResult.fail(
                f"ER point out of range [0-1000]: {point_yx}"
            )

        # Store ER result for downstream use
        context.set_variable("last_er_point", point_yx)

        # Overlay crosshair on the image for visualisation
        try:
            annotated_bytes = _overlay_point(
                image_bytes,
                point_yx,
                params.object_description,
                params.frame_width,
                params.frame_height,
            )
            annotated_b64 = base64.b64encode(annotated_bytes).decode("utf-8")
            context.set_variable("last_image_b64", annotated_b64)
            context.set_variable("last_image_bytes", annotated_bytes)
        except Exception as exc:
            logger.warning("Point overlay failed: %s", exc)
            annotated_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # ── Phase 2: Convert ER point → robot XY and move ─────────
        robot = context.get_executor("robot")
        if not robot.is_ready():
            return SkillResult.fail(
                "Robot not ready — ER detection succeeded but cannot execute motion",
                {
                    "er_point_yx": point_yx,
                    "annotated_image_b64": annotated_b64,
                },
            )

        # ER [y, x] → pixel (x, y) → robot (x_mm, y_mm, z_mm)
        pixel_x, pixel_y = _normalized_yx_to_pixel(
            point_yx, params.frame_width, params.frame_height
        )
        robot_mm = fallback_depth_from_plane(pixel_x, pixel_y)

        # Resolve Z and orientation from current TCP pose
        reference_pose = _resolve_reference_pose(
            robot, context, params.reference_pose
        )
        if reference_pose is None:
            return SkillResult.fail(
                "Cannot resolve TCP pose for Z/orientation lock. "
                "Provide reference_pose or run get_robot_state first.",
                {
                    "er_point_yx": point_yx,
                    "robot_mm_estimated": list(robot_mm),
                    "annotated_image_b64": annotated_b64,
                },
            )

        locked_z = float(reference_pose[2])
        locked_orientation = [float(v) for v in reference_pose[3:6]]

        target_pose = [
            float(robot_mm[0]) / 1000.0,   # x  (mm → m)
            float(robot_mm[1]) / 1000.0,   # y  (mm → m)
            locked_z,                        # z  (locked)
            *locked_orientation,             # rx, ry, rz (locked)
        ]

        logger.info(
            "point_to_object: ER [y,x]=%s → pixel=(%s,%s) → robot_mm=%s → pose=%s",
            point_yx, pixel_x, pixel_y, robot_mm, target_pose,
        )

        ok = await robot.move_linear(
            pose=target_pose,
            acceleration=params.acceleration,
            velocity=params.velocity,
        )

        if not ok:
            return SkillResult.fail(
                "Linear move to ER-detected point failed",
                {
                    "er_point_yx": point_yx,
                    "target_pose": target_pose,
                    "annotated_image_b64": annotated_b64,
                },
            )

        result = {
            "object_description": params.object_description,
            "er_point_yx": point_yx,
            "pixel_xy": [pixel_x, pixel_y],
            "robot_mm_estimated": [
                float(robot_mm[0]),
                float(robot_mm[1]),
                float(robot_mm[2]),
            ],
            "target_pose_commanded": target_pose,
            "locked_z_m": locked_z,
            "reached": True,
            "annotated_image_b64": annotated_b64,
            "timestamp": time.time(),
        }
        context.set_variable("last_point_to_object", result)
        return SkillResult.ok(result)
