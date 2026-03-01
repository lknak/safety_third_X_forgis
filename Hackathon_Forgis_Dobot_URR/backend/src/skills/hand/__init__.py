"""Pneumatic gripper skills (formerly hand skills)."""

from .open_gripper import OpenGripperSkill
from .close_gripper import CloseGripperSkill
from .set_grip import SetGripSkill             # Compatibility layer
from .set_finger_positions import SetFingerPositionsSkill  # Compatibility layer

__all__ = [
    "OpenGripperSkill",
    "CloseGripperSkill",
    "SetGripSkill",
    "SetFingerPositionsSkill"
]
