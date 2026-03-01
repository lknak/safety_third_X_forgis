"""Primitive skills — the minimal generalist skill set for the orchestrator.

16 skills across 5 layers:
  Perception:  capture_image, analyze_scene, estimate_grasp_pose, depth_estimation
  Reasoning:   llm_reason, live_narrate
  Motion:      move_to_pose, move_joints, jog_joints, get_robot_state
  Actuation:   suction_on, suction_off, set_digital_output, wait_digital_input
  Flow:        wait, verify_outcome
"""

# Perception
from .capture_image import CaptureImageSkill
from .analyze_scene import AnalyzeSceneSkill
from .estimate_grasp_pose import EstimateGraspPoseSkill
from .depth_estimation import DepthEstimationSkill

# Reasoning
from .llm_reason import LLMReasonSkill
from .live_narrate import LiveNarrateSkill

# Motion
from .move_to_pose import MoveToPoseSkill
from .move_joints import MoveJointsSkill
from .jog_joints import JogJointsPrimitiveSkill
from .get_robot_state import GetRobotStateSkill

# Actuation
from .suction_on import SuctionOnSkill
from .suction_off import SuctionOffSkill
from .set_digital_output import SetDigitalOutputSkill
from .wait_digital_input import WaitDigitalInputSkill

# Flow Control
from .wait import WaitSkill
from .verify_outcome import VerifyOutcomeSkill

__all__ = [
    "CaptureImageSkill",
    "AnalyzeSceneSkill",
    "EstimateGraspPoseSkill",
    "DepthEstimationSkill",
    "LLMReasonSkill",
    "LiveNarrateSkill",
    "MoveToPoseSkill",
    "MoveJointsSkill",
    "JogJointsPrimitiveSkill",
    "GetRobotStateSkill",
    "SuctionOnSkill",
    "SuctionOffSkill",
    "SetDigitalOutputSkill",
    "WaitDigitalInputSkill",
    "WaitSkill",
    "VerifyOutcomeSkill",
]

# Ordered list used by the planner prompt so Gemini knows available skills
PRIMITIVE_SKILL_CATALOG = [
    {
        "name": "capture_image",
        "layer": "perception",
        "description": "Capture a single RGB frame from the monocular camera.",
        "params": {"resolution": "optional str ('480p'|'720p'|'1080p')"},
        "returns": "image_bytes (base64), timestamp",
    },
    {
        "name": "analyze_scene",
        "layer": "perception",
        "description": "Send an image + natural-language query to Gemini VLM for scene understanding, object detection, anomaly check, text reading, or any visual question.",
        "params": {"query": "str — what to analyze", "image_b64": "optional — auto-captured if omitted"},
        "returns": "Structured JSON with objects, bounding_boxes, labels, spatial_relations, answer",
    },
    {
        "name": "estimate_grasp_pose",
        "layer": "perception",
        "description": "Convert a 2D bounding box + object class into a 3D robot-frame grasp pose using monocular depth estimation and workspace calibration.",
        "params": {"bbox": "{x,y,w,h}", "object_class": "str", "depth_hint_m": "optional float"},
        "returns": "grasp_pose [x,y,z,rx,ry,rz], approach_pose, place_pose",
    },
    {
        "name": "depth_estimation",
        "layer": "perception",
        "description": "Estimate 3D depth of an object from monocular camera using VLM spatial reasoning or monocular depth model.",
        "params": {"bbox": "optional {x,y,w,h}", "object_class": "str", "image_b64": "optional"},
        "returns": "estimated_depth_m, approach_z, z_clamp",
    },
    {
        "name": "llm_reason",
        "layer": "reasoning",
        "description": "General-purpose Gemini call for mid-flow planning, decision-making, text parsing, conditional branching, or error diagnosis.",
        "params": {"prompt": "str", "model": "optional ('flash'|'pro'|'er')", "response_format": "optional ('json'|'text')", "image_b64": "optional"},
        "returns": "response (text or parsed JSON)",
    },
    {
        "name": "live_narrate",
        "layer": "reasoning",
        "description": "Generate real-time voice commentary about the current operation using Gemini Live.",
        "params": {"prompt": "str", "image_b64": "optional"},
        "returns": "commentary_text, audio_chunk_b64",
    },
    {
        "name": "move_to_pose",
        "layer": "motion",
        "description": "Move robot TCP to a Cartesian pose [x,y,z,rx,ry,rz]. Supports linear (straight-line) or joint interpolation.",
        "params": {"pose": "[x,y,z,rx,ry,rz] meters+radians", "velocity": "float", "acceleration": "float", "motion_type": "'linear'|'joint'"},
        "returns": "success, final_pose",
    },
    {
        "name": "move_joints",
        "layer": "motion",
        "description": "Move robot to explicit joint positions in degrees.",
        "params": {"joint_positions_deg": "[j0..j5]", "velocity": "float", "acceleration": "float"},
        "returns": "success, final_joints_deg",
    },
    {
        "name": "jog_joints",
        "layer": "motion",
        "description": "Apply relative joint offsets from current positions.",
        "params": {"offsets_deg": "[j0..j5]", "velocity": "float", "acceleration": "float"},
        "returns": "success, previous_deg, target_deg",
    },
    {
        "name": "get_robot_state",
        "layer": "motion",
        "description": "Read current robot state: joint positions, TCP pose, digital IO status.",
        "params": {},
        "returns": "joint_positions_deg, tcp_pose, digital_inputs, digital_outputs, is_ready",
    },
    {
        "name": "suction_on",
        "layer": "actuation",
        "description": "Activate the pneumatic suction gripper (vacuum on).",
        "params": {},
        "returns": "success",
    },
    {
        "name": "suction_off",
        "layer": "actuation",
        "description": "Release the pneumatic suction gripper (vacuum off).",
        "params": {},
        "returns": "success",
    },
    {
        "name": "set_digital_output",
        "layer": "actuation",
        "description": "Set a digital output pin to HIGH or LOW.",
        "params": {"pin": "int 0-7", "value": "bool"},
        "returns": "success",
    },
    {
        "name": "wait_digital_input",
        "layer": "actuation",
        "description": "Wait for a digital input pin to reach an expected value (sensor, external trigger).",
        "params": {"pin": "int 0-7", "expected_value": "bool", "timeout_ms": "int"},
        "returns": "success, actual_value",
    },
    {
        "name": "wait",
        "layer": "flow_control",
        "description": "Pause execution for a fixed duration or until a natural-language condition is true (evaluated via camera+LLM).",
        "params": {"duration_ms": "optional int", "condition": "optional str (natural language)"},
        "returns": "success, elapsed_ms",
    },
    {
        "name": "verify_outcome",
        "layer": "flow_control",
        "description": "Post-action visual verification. Captures image and asks Gemini whether the expected state is achieved.",
        "params": {"expected_state": "str (natural language description)"},
        "returns": "verified (bool), reasoning, confidence",
    },
]

