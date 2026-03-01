"""ExecuteXYAction skill: run XY-only robot motion from ER trajectory points.

This skill is designed to run after `plan_trajectory`.
It consumes Gemini ER start/end points, maps image-space pixels to robot XY
using a calibrated homography, and executes linear motion while keeping Z and
orientation fixed from the current TCP pose (or a provided reference pose).
"""

from __future__ import annotations

import math
from typing import Any, Optional

import cv2
import numpy as np
from pydantic import BaseModel, Field

from ..base import ExecutionContext, Skill, SkillResult
from ..registry import register_skill

# Calibration points from the provided pixel->robot mapping.
# Pixel points are [x, y] in a 1920x1080 camera frame.
_PIXEL_POINTS = np.array(
    [
        [813.0, 1044.0],
        [415.0, 891.0],
        [790.0, 684.0],
        [1188.0, 777.0],
    ],
    dtype=np.float32,
)

# Robot points are [x_mm, y_mm, z_mm].
_ROBOT_POINTS = np.array(
    [
        [639.49, -87.28, -245.69],
        [399.47, -424.79, -245.69],
        [256.25, -36.88, -245.71],
        [530.02, 351.46, -245.72],
    ],
    dtype=np.float32,
)

# Homography for mapping (u, v) pixel -> (x, y) robot mm.
_H, _ = cv2.findHomography(_PIXEL_POINTS, _ROBOT_POINTS[:, :2])
if _H is None:
    raise RuntimeError("Failed to compute pixel-to-robot homography for execute_xy_action")

# Plane fit for Z as a function of pixel (u, v): z = a*u + b*v + c.
_A_Z = np.column_stack([_PIXEL_POINTS, np.ones(len(_PIXEL_POINTS))])
_Z_VALUES = _ROBOT_POINTS[:, 2]
_PLANE_PARAMS_Z, _, _, _ = np.linalg.lstsq(_A_Z, _Z_VALUES, rcond=None)


def fallback_depth_from_plane(pixel_x: float, pixel_y: float) -> tuple[float, float, float]:
    """Map pixel coordinates to robot coordinates in mm using calibration."""
    px_vec = np.array([pixel_x, pixel_y, 1.0], dtype=np.float32).reshape(3, 1)
    robot_xy_hom = _H @ px_vec
    if robot_xy_hom[2, 0] != 0:
        robot_xy_hom /= robot_xy_hom[2, 0]

    res_x = float(robot_xy_hom[0, 0])
    res_y = float(robot_xy_hom[1, 0])
    res_z = float(np.dot([pixel_x, pixel_y, 1.0], _PLANE_PARAMS_Z))
    return res_x, res_y, res_z


def _to_float_pair(value: Any) -> Optional[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None


def _extract_start_end_points_from_trajectory(trajectory: Any) -> Optional[tuple[list[float], list[float]]]:
    """Extract first/last ER points as [y, x] from `last_trajectory`."""
    if not isinstance(trajectory, list) or len(trajectory) == 0:
        return None

    parsed: list[tuple[float, list[float]]] = []
    for idx, item in enumerate(trajectory):
        order = float(idx)
        point_raw: Any = item

        if isinstance(item, dict):
            point_raw = item.get("point")
            label = item.get("label")
            try:
                order = float(label)
            except (TypeError, ValueError):
                order = float(idx)

        pair = _to_float_pair(point_raw)
        if pair is None:
            continue
        parsed.append((order, pair))

    if not parsed:
        return None

    parsed.sort(key=lambda p: p[0])
    return parsed[0][1], parsed[-1][1]


def _normalized_yx_to_pixel(point_yx: list[float], frame_width: int, frame_height: int) -> tuple[float, float]:
    """Convert ER [y, x] normalized in 0..1000 to pixel (x, y)."""
    y_norm, x_norm = point_yx
    pixel_x = x_norm * frame_width / 1000.0
    pixel_y = y_norm * frame_height / 1000.0
    return pixel_x, pixel_y


def _mm_deg_pose_to_m_rad_pose(tcp_pose_mm_deg: Any) -> Optional[list[float]]:
    if not isinstance(tcp_pose_mm_deg, (list, tuple)) or len(tcp_pose_mm_deg) < 6:
        return None

    try:
        x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg = [float(v) for v in tcp_pose_mm_deg[:6]]
    except (TypeError, ValueError):
        return None

    return [
        x_mm / 1000.0,
        y_mm / 1000.0,
        z_mm / 1000.0,
        math.radians(rx_deg),
        math.radians(ry_deg),
        math.radians(rz_deg),
    ]


def _resolve_reference_pose(robot: Any, context: ExecutionContext, explicit_pose: Optional[list[float]]) -> Optional[list[float]]:
    """Resolve [x,y,z,rx,ry,rz] in meters/radians for Z and orientation lock."""
    if explicit_pose is not None:
        return [float(v) for v in explicit_pose]

    # Prefer UR node direct TCP if available.
    ur_node = getattr(robot, "_robot", None)
    if ur_node is not None and hasattr(ur_node, "get_tcp_pose"):
        raw_pose = ur_node.get_tcp_pose()
        if isinstance(raw_pose, list) and len(raw_pose) == 6:
            return [float(v) for v in raw_pose]

    # Fallback to state summary that exposes tcp_pose_mm_deg.
    if hasattr(robot, "get_state_summary"):
        summary = robot.get_state_summary() or {}
        pose = _mm_deg_pose_to_m_rad_pose(summary.get("tcp_pose_mm_deg"))
        if pose is not None:
            return pose

    # Fallback to context variable from get_robot_state output.
    robot_state = context.get_variable("robot_state")
    if isinstance(robot_state, dict):
        state_summary = robot_state.get("state_summary")
        if isinstance(state_summary, dict):
            pose = _mm_deg_pose_to_m_rad_pose(state_summary.get("tcp_pose_mm_deg"))
            if pose is not None:
                return pose

    return None


class ExecuteXYActionParams(BaseModel):
    """Parameters for execute_xy_action."""

    start_point: Optional[list[float]] = Field(
        default=None,
        min_length=2,
        max_length=2,
        description=(
            "Optional start point. For normalized_yx mode: [y, x] in 0..1000. "
            "For pixel_xy mode: [x, y] in pixels."
        ),
    )
    end_point: Optional[list[float]] = Field(
        default=None,
        min_length=2,
        max_length=2,
        description=(
            "Optional end point. For normalized_yx mode: [y, x] in 0..1000. "
            "For pixel_xy mode: [x, y] in pixels."
        ),
    )
    point_mode: str = Field(
        default="normalized_yx",
        description="Point format: 'normalized_yx' (ER output) or 'pixel_xy'.",
    )
    frame_width: int = Field(
        default=1920,
        ge=1,
        le=8192,
        description="Frame width used when converting normalized ER points to pixels.",
    )
    frame_height: int = Field(
        default=1080,
        ge=1,
        le=8192,
        description="Frame height used when converting normalized ER points to pixels.",
    )
    move_to_start: bool = Field(
        default=True,
        description="If true, move to mapped start point before end point.",
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
        description="Linear motion acceleration in m/s^2.",
    )
    reference_pose: Optional[list[float]] = Field(
        default=None,
        min_length=6,
        max_length=6,
        description=(
            "Optional [x,y,z,rx,ry,rz] in meters/radians. Used to lock Z/orientation "
            "when current TCP pose cannot be read from robot state."
        ),
    )


@register_skill
class ExecuteXYActionSkill(Skill[ExecuteXYActionParams]):
    """Execute a planar (XY-only) motion using ER start/end points."""

    name = "execute_xy_action"
    executor_type = "robot"
    description = (
        "Execute XY-only robot motion using calibrated pixel-to-robot mapping. "
        "Requires prior plan_trajectory output and keeps Z/orientation fixed."
    )

    @classmethod
    def params_schema(cls) -> type[BaseModel]:
        return ExecuteXYActionParams

    async def validate(self, params: ExecuteXYActionParams) -> tuple[bool, Optional[str]]:
        if params.point_mode not in ("normalized_yx", "pixel_xy"):
            return False, "point_mode must be 'normalized_yx' or 'pixel_xy'"

        if params.point_mode == "normalized_yx":
            for name, point in (("start_point", params.start_point), ("end_point", params.end_point)):
                if point is None:
                    continue
                if point[0] < 0 or point[0] > 1000 or point[1] < 0 or point[1] > 1000:
                    return False, f"{name} must be within [0,1000] for normalized_yx mode"

        return True, None

    async def execute(self, params: ExecuteXYActionParams, context: ExecutionContext) -> SkillResult:
        robot = context.get_executor("robot")
        if not robot.is_ready():
            return SkillResult.fail("Robot not ready")

        # Enforce sequencing: this skill must run after ER trajectory output exists.
        trajectory = context.get_variable("last_trajectory")
        if not isinstance(trajectory, list) or len(trajectory) == 0:
            return SkillResult.fail(
                "execute_xy_action requires ER output from plan_trajectory. "
                "Run plan_trajectory first."
            )

        extracted = _extract_start_end_points_from_trajectory(trajectory)
        if extracted is None:
            return SkillResult.fail("Could not extract valid start/end points from last_trajectory")
        traj_start_yx, traj_end_yx = extracted

        # Allow explicit override, otherwise consume ER start/end points.
        start_point = [float(v) for v in (params.start_point or traj_start_yx)]
        end_point = [float(v) for v in (params.end_point or traj_end_yx)]

        if params.point_mode == "normalized_yx":
            start_pixel = _normalized_yx_to_pixel(start_point, params.frame_width, params.frame_height)
            end_pixel = _normalized_yx_to_pixel(end_point, params.frame_width, params.frame_height)
        else:
            start_pixel = (start_point[0], start_point[1])
            end_pixel = (end_point[0], end_point[1])

        start_robot_mm = fallback_depth_from_plane(start_pixel[0], start_pixel[1])
        end_robot_mm = fallback_depth_from_plane(end_pixel[0], end_pixel[1])

        reference_pose = _resolve_reference_pose(robot, context, params.reference_pose)
        if reference_pose is None:
            return SkillResult.fail(
                "Cannot resolve current TCP pose for Z/orientation lock. "
                "Provide reference_pose or run get_robot_state on a robot with tcp_pose feedback."
            )

        locked_z = float(reference_pose[2])
        locked_orientation = [float(v) for v in reference_pose[3:6]]

        # Z motion is explicitly disabled: all commanded poses keep the same Z.
        start_pose = [
            float(start_robot_mm[0]) / 1000.0,
            float(start_robot_mm[1]) / 1000.0,
            locked_z,
            *locked_orientation,
        ]
        end_pose = [
            float(end_robot_mm[0]) / 1000.0,
            float(end_robot_mm[1]) / 1000.0,
            locked_z,
            *locked_orientation,
        ]

        if params.move_to_start:
            ok_start = await robot.move_linear(
                pose=start_pose,
                acceleration=params.acceleration,
                velocity=params.velocity,
            )
            if not ok_start:
                return SkillResult.fail(
                    "Failed to move to XY start point",
                    {
                        "start_pose": start_pose,
                        "end_pose": end_pose,
                        "locked_z_m": locked_z,
                    },
                )

        ok_end = await robot.move_linear(
            pose=end_pose,
            acceleration=params.acceleration,
            velocity=params.velocity,
        )
        if not ok_end:
            return SkillResult.fail(
                "Failed to move to XY end point",
                {
                    "start_pose": start_pose,
                    "end_pose": end_pose,
                    "locked_z_m": locked_z,
                },
            )

        result = {
            "point_mode": params.point_mode,
            "start_point_input": start_point,
            "end_point_input": end_point,
            "start_pixel": [float(start_pixel[0]), float(start_pixel[1])],
            "end_pixel": [float(end_pixel[0]), float(end_pixel[1])],
            "start_robot_mm_estimated": [float(start_robot_mm[0]), float(start_robot_mm[1]), float(start_robot_mm[2])],
            "end_robot_mm_estimated": [float(end_robot_mm[0]), float(end_robot_mm[1]), float(end_robot_mm[2])],
            "start_pose_commanded": start_pose,
            "end_pose_commanded": end_pose,
            "z_motion_allowed": False,
            "commanded_z_delta_m": 0.0,
            "locked_z_m": locked_z,
            "reached": True,
        }
        context.set_variable("last_xy_action", result)
        return SkillResult.ok(result)
