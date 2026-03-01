import type { ReactNode } from "react";

// ── Flow types (aligned with backend naming) ────────────────

export interface FlowStep {
  id: string;
  skill: string;
  executor: string;
  params?: Record<string, unknown>;
}

export interface FlowNode {
  id: string;
  type: string;           // "state", "start", "end"
  label: string;          // display name
  steps?: FlowStep[];     // steps inside state nodes
  position: { x: number; y: number };
  style?: { width: number; height: number };
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  data?: Record<string, unknown>;
}

export interface Flow {
  id: string;
  name: string;
  loop?: boolean;
  nodes: FlowNode[];
  edges: FlowEdge[];
}

// ── Chat types ──────────────────────────────────────────────

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  kind?: "text" | "node" | "reasoning" | "plan" | "status" | "success" | "error";
  node?: {
    flowId: string;
    name: string;
    type: OrchestratorNodeType | string;
    status: OrchestratorNodeStatus | "RUNNING";
    durationMs?: number;
  };
  artifacts?: Record<string, unknown>;
  media?: Array<{
    type: "image" | "video";
    dataUrl: string;
    label?: string;
  }>;
  planSteps?: Array<{
    skill: string;
    description: string;
  }>;
}

// ── Device types ────────────────────────────────────────────

export type DeviceType = "robot" | "camera" | "sensor" | "gripper";
export type DeviceStatus = "connected" | "warning" | "disconnected";

export interface Device {
  id: string;
  name: string;
  vendor: string;
  type: DeviceType;
  status: DeviceStatus;
  ip: string;
  reachable: boolean;
  onlineSince?: string;
  firmwareVersion?: string;
  lastMaintenance?: string;
}

// ── Step selection (for parameter editor) ───────────────────

export interface SelectedStep {
  nodeId: string;
  step: FlowStep;
}

// ── Node creator (UI-only) ──────────────────────────────────

export interface NodeCreatorState {
  nodeType: string | null;
  task: string | null;
  label: string;
}

// ── Flow execution types ────────────────────────────────────

export type NodeExecStatus = "idle" | "running" | "success" | "failure";

export interface StepExecState {
  status: NodeExecStatus;
  retries?: number;
  error?: string;
  result?: Record<string, unknown>;
}

export interface NodeExecState {
  status: NodeExecStatus;
  durationMs?: number;
  error?: string;
  stepStates?: Record<string, StepExecState>; // Track individual step execution
  currentStep?: string; // Currently executing step ID
}

// Aligned with backend FlowExecutionStatus enum
export type FlowExecStatus = "idle" | "running" | "paused" | "completed" | "error";

// ── WebSocket messages: Server → Client (aligned with backend) ─────

export type ServerMessage =
  | { type: "connected"; message: string; timestamp: number }
  | { type: "flow_started"; flow_id: string; name: string; timestamp: number }
  | { type: "flow_completed"; flow_id: string; status: string; timestamp: number }
  | { type: "flow_paused"; flow_id: string; timestamp: number }
  | { type: "flow_resumed"; flow_id: string; timestamp: number }
  | { type: "flow_aborted"; flow_id: string; timestamp: number }
  | { type: "flow_error"; flow_id: string; error: string; step_id?: string; timestamp: number }
  | { type: "state_entered"; flow_id: string; state: string; timestamp: number }
  | { type: "state_completed"; flow_id: string; state: string; timestamp: number }
  | { type: "loop_restart"; flow_id: string; initial_state: string; timestamp: number }
  | { type: "step_started"; flow_id: string; step_id: string; skill: string; executor: string; timestamp: number }
  | { type: "step_completed"; flow_id: string; step_id: string; result: Record<string, unknown>; retries: number; timestamp: number }
  | { type: "step_error"; flow_id: string; step_id: string; error: string; strategy?: string; timestamp: number }
  | { type: "step_retry"; flow_id: string; step_id: string; attempt: number; max_retries: number; timestamp: number }
  | { type: "step_skipped"; flow_id: string; step_id: string; error: string; strategy: string; timestamp: number }
  | { type: "waiting_condition"; flow_id: string; state: string; timestamp: number }
  | { type: "camera_frame"; frame: string; width: number; height: number; timestamp: number }
  | { type: "bounding_box"; bbox: BoundingBox; frame_width: number; frame_height: number; display_duration_ms: number; timestamp: number }
  | { type: "orchestrator_state_transition"; from_state: string; to_state: string; reason: string; timestamp: number }
  | { type: "orchestrator_task_queued"; task_id: string; flow_id: string; instruction: string; queue_position: number; timestamp: number }
  | { type: "orchestrator_run_completed"; flow_id: string; final_status: string; error?: string; timestamp: number }
  | { type: "orchestrator_replanned"; flow_id: string; reason: string; action: string; subgoals: Array<Record<string, unknown>>; timestamp: number }
  | { type: "orchestrator_goal_change_requested"; flow_id: string; goal: string; timestamp: number }
  | { type: "orchestrator_goal_change_applied"; flow_id: string; goal: string; timestamp: number }
  | { type: "orchestrator_node_started"; flow_id: string; node_name: string; node_type: OrchestratorNodeType; timestamp: number }
  | { type: "orchestrator_node_finished"; flow_id: string; node_name: string; node_type: OrchestratorNodeType; status: OrchestratorNodeStatus; duration_ms: number; artifacts: Record<string, unknown>; timestamp: number }
  | { type: "orchestrator_tile_focus"; flow_id: string; active_node: string; primary_tile: string; timestamp: number }
  | { type: "orchestrator_clarification_requested"; flow_id: string; node_name: string; reason: string; timeout_seconds: number; choices: Array<"retry" | "replan" | "modify_goal" | "safe_stop">; timestamp: number }
  | { type: "orchestrator_clarification_resolved"; flow_id: string; action: "retry" | "replan" | "modify_goal" | "safe_stop"; note?: string; timestamp: number }
  | { type: "orchestrator_clarification_timeout"; flow_id: string; node_name: string; timestamp: number }
  | { type: "orchestrator_agentic_micro_plan"; flow_id: string; iteration: number; reasoning: string; scene_summary?: string; progress?: Record<string, unknown>; timestamp: number }
  | { type: "orchestrator_live_chunk"; flow_id: string; node_name: string; text: string; audio_chunk: string; focus_regions?: Array<Record<string, unknown>>; timestamp: number }
  | { type: "pong" };

// ── Bounding box types ─────────────────────────────────────

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
  class_name: string;
}

export interface BoundingBoxOverlay {
  bbox: BoundingBox;
  frameWidth: number;
  frameHeight: number;
  expiresAt: number;
}

export type OrchestratorNodeType =
  | "INPUT_NODE"
  | "ORCHESTRATOR_PLANNER_NODE"
  | "SUMMARY_NODE"
  | "CAPTURE_IMAGE"
  | "ANALYZE_SCENE"
  | "ESTIMATE_GRASP_POSE"
  | "DEPTH_ESTIMATION"
  | "LLM_REASON"
  | "LIVE_NARRATE"
  | "MOVE_TO_POSE"
  | "MOVE_JOINTS"
  | "JOG_JOINTS"
  | "GET_ROBOT_STATE"
  | "SUCTION_ON"
  | "SUCTION_OFF"
  | "SET_DIGITAL_OUTPUT"
  | "WAIT_DIGITAL_INPUT"
  | "WAIT"
  | "VERIFY_OUTCOME"
  // Legacy aliases retained for backward compatibility with historical runs
  | "ER_1_5_ANALYSIS_NODE"
  | "DEPTH_ESTIMATION_NODE"
  | "ROBOT_EXECUTION_NODE"
  | "GEMINI_LIVE_COMMENTARY_NODE"
  | "VERIFICATION_NODE"
  | "JOG_JOINTS_NODE";

export type OrchestratorNodeStatus = "SUCCESS" | "FAILURE" | "TIMEOUT";

export interface OrchestratorTile {
  name: string;
  type: OrchestratorNodeType;
  status: OrchestratorNodeStatus | "PENDING" | "RUNNING";
  startTime?: number;
  endTime?: number;
  artifacts?: Record<string, unknown>;
}

export interface PlannedOrchestratorNode {
  name: string;
  type: OrchestratorNodeType;
  order: number;
}

export type OrchestratorTilePhase = "past" | "active" | "future";

export interface OrchestratorTimelineTile extends OrchestratorTile {
  order: number;
  phase: OrchestratorTilePhase;
  isActive: boolean;
  durationMs: number | null;
  hasArtifacts: boolean;
}
/**
 * Props for the generic ContentPanel component
 */
export interface ContentPanelProps {
  /** Panel title displayed in the header */
  title: string;
  /** Optional subtitle displayed below the title */
  subtitle?: string;
  /** Optional action buttons/elements for the header (right side) */
  actions?: ReactNode;
  /** Optional center content for the header */
  centerActions?: ReactNode;
  /** Panel content */
  children?: ReactNode;
  /** Additional CSS classes for the outer card */
  className?: string;
  /** Additional CSS classes for the content area */
  contentClassName?: string;
  /** Enable scrolling in content area (default: true) */
  scrollable?: boolean;
}
