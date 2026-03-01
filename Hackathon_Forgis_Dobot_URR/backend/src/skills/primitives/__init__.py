"""Primitive skills - the minimal generalist skill set for the orchestrator.

17 skills across 5 layers:
  Perception:  capture_image, analyze_scene, estimate_grasp_pose, plan_trajectory
  Reasoning:   llm_reason, live_narrate
  Motion:      move_to_pose, execute_xy_action, move_joints, jog_joints, get_robot_state
  Actuation:   suction_on, suction_off, set_digital_output, wait_digital_input
  Flow:        wait, verify_outcome

Trajectory / motion planning is handled by Gemini Robotics-ER 1.5 via the
plan_trajectory skill. ER generates trajectory waypoints from images +
natural-language tasks, overlays them on the image, and outputs annotated images.
"""

# Perception
from .capture_image import CaptureImageSkill
from .analyze_scene import AnalyzeSceneSkill
from .estimate_grasp_pose import EstimateGraspPoseSkill
from .plan_trajectory import PlanTrajectorySkill

# Reasoning
from .llm_reason import LLMReasonSkill
from .live_narrate import LiveNarrateSkill

# Motion
from .move_to_pose import MoveToPoseSkill
from .execute_xy_action import ExecuteXYActionSkill
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
    "PlanTrajectorySkill",
    "LLMReasonSkill",
    "LiveNarrateSkill",
    "MoveToPoseSkill",
    "ExecuteXYActionSkill",
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

# Ordered list used by the planner prompt so Gemini knows available skills.
# Keep descriptions explicit so the planner can choose skills unambiguously.
PRIMITIVE_SKILL_CATALOG = [
    {
        "name": "capture_image",
        "layer": "perception",
        "description": "Capture a single RGB frame from the camera.",
        "params": {"resolution": "optional str ('480p'|'720p'|'1080p')"},
        "returns": "image_b64, timestamp",
        "use_when": "Any workflow needs a fresh frame.",
        "avoid_when": "Not needed if a valid image_b64 already exists.",
    },
    {
        "name": "analyze_scene",
        "layer": "perception",
        "description": "Gemini ER single-frame visual understanding for detection, counting, label reading, and visual QA.",
        "params": {
            "query": "str - explicit visual question",
            "image_b64": "optional - auto-captured if omitted",
        },
        "returns": "analysis: {objects:[{label,bbox}], answer, spatial_relations}",
        "use_when": "User asks what/where/how-many/read-text in current frame.",
        "avoid_when": "Do not use for trajectory planning or long-form text synthesis.",
    },
    {
        "name": "estimate_grasp_pose",
        "layer": "perception",
        "description": "Convert one detected 2D object region into robot-frame 3D grasp/approach/place poses.",
        "params": {
            "bbox": "{x,y,width,height} or {box_2d:[ymin,xmin,ymax,xmax]}",
            "object_class": "str",
            "depth_hint_m": "optional float",
        },
        "returns": "grasp_pose, approach_pose, place_pose",
        "use_when": "After analyze_scene when target object bbox is known.",
        "avoid_when": "Do not call without concrete bbox coordinates.",
    },
    {
        "name": "plan_trajectory",
        "layer": "perception",
        "description": "Gemini ER motion-path planning from image + task. Returns ordered 2D waypoints and an annotated trajectory image.",
        "params": {
            "task": "str - manipulation intent",
            "num_points": "int (default 15)",
            "object_label": "optional str",
            "image_b64": "optional",
        },
        "returns": "trajectory_points [{point:[y,x],label}], annotated_image_b64, num_waypoints",
        "use_when": "Task requires planning path/route/motion through the scene.",
        "avoid_when": "Do not use for simple visual QA or pure text summarization.",
    },
    {
        "name": "llm_reason",
        "layer": "reasoning",
        "description": "Text reasoning only: summarize, transform, or decide using outputs from prior skills.",
        "params": {
            "prompt": "str",
            "model": "optional ('flash'|'pro'|'er')",
            "response_format": "optional ('json'|'text')",
            "image_b64": "optional",
        },
        "returns": "response (text or parsed JSON)",
        "use_when": "Post-process analyze_scene/trajectory outputs.",
        "avoid_when": "Do not use as first skill for camera perception.",
    },
    {
        "name": "live_narrate",
        "layer": "reasoning",
        "description": "Gemini Live operator narration from the current camera frame. Generates one concise commentary sentence.",
        "params": {
            "prompt": "str",
            "image_b64": "optional",
            "include_scene_context": "bool (default true)",
        },
        "returns": "commentary_text, audio_chunk_b64, had_visual_context, model_path",
        "use_when": "Need operator-facing live narration during motion.",
        "avoid_when": "Do not use for detection/counting/path planning.",
    },
    {
        "name": "move_to_pose",
        "layer": "motion",
        "description": "Move robot TCP to Cartesian pose [x,y,z,rx,ry,rz].",
        "params": {"pose": "[x,y,z,rx,ry,rz]", "velocity": "float", "acceleration": "float", "motion_type": "'linear'|'joint'"},
        "returns": "success, final_pose",
    },
    {
        "name": "execute_xy_action",
        "layer": "motion",
        "description": "Execute XY-only linear motion from Gemini ER start/end points using calibrated pixel-to-robot mapping.",
        "params": {
            "start_point": "optional [y,x] normalized (or [x,y] pixels in pixel_xy mode)",
            "end_point": "optional [y,x] normalized (or [x,y] pixels in pixel_xy mode)",
            "point_mode": "'normalized_yx'|'pixel_xy'",
            "frame_width": "int (default 1920)",
            "frame_height": "int (default 1080)",
            "move_to_start": "bool",
            "velocity": "float",
            "acceleration": "float",
            "reference_pose": "optional [x,y,z,rx,ry,rz] for Z/orientation lock",
        },
        "returns": "start/end mapped poses, reached, z_motion_allowed=false",
        "use_when": "Immediately after plan_trajectory for planar XY execution.",
        "avoid_when": "Do not use before plan_trajectory output is available; does not perform Z motion.",
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
        "description": "Read current robot state including joints, pose, and IO.",
        "params": {},
        "returns": "joint_positions_deg, tcp_pose, digital_inputs, digital_outputs, is_ready",
    },
    {
        "name": "suction_on",
        "layer": "actuation",
        "description": "Activate pneumatic suction gripper.",
        "params": {},
        "returns": "success",
    },
    {
        "name": "suction_off",
        "layer": "actuation",
        "description": "Deactivate pneumatic suction gripper.",
        "params": {},
        "returns": "success",
    },
    {
        "name": "set_digital_output",
        "layer": "actuation",
        "description": "Set a digital output pin HIGH or LOW.",
        "params": {"pin": "int 0-7", "value": "bool"},
        "returns": "success",
    },
    {
        "name": "wait_digital_input",
        "layer": "actuation",
        "description": "Wait for digital input pin to reach expected value.",
        "params": {"pin": "int 0-7", "expected_value": "bool", "timeout_ms": "int"},
        "returns": "success, actual_value",
    },
    {
        "name": "wait",
        "layer": "flow_control",
        "description": "Pause for duration or until a natural-language condition is satisfied.",
        "params": {"duration_ms": "optional int", "condition": "optional str"},
        "returns": "success, elapsed_ms",
    },
    {
        "name": "verify_outcome",
        "layer": "flow_control",
        "description": "Post-action visual verification against expected outcome.",
        "params": {"expected_state": "str"},
        "returns": "verified, reasoning, confidence",
    },
]
