import { getJson, postJson } from "./httpClient";

export type OrchestratorState =
  | "BOOT"
  | "CELL_CHECK"
  | "READY"
  | "EXECUTING"
  | "ERROR"
  | "RECOVERY";

export type OrchestratorNodeType =
  | "INPUT_NODE"
  | "ORCHESTRATOR_PLANNER_NODE"
  | "ER_1_5_ANALYSIS_NODE"
  | "DEPTH_ESTIMATION_NODE"
  | "ROBOT_EXECUTION_NODE"
  | "GEMINI_LIVE_COMMENTARY_NODE"
  | "VERIFICATION_NODE"
  | "SUMMARY_NODE";

export type OrchestratorNodeStatus = "SUCCESS" | "FAILURE" | "TIMEOUT";

export interface PreviewFlowStep {
  id: string;
  skill: string;
  executor: string;
  params?: Record<string, unknown>;
}

export interface PreviewFlowNode {
  id: string;
  type: string;
  label: string;
  steps: PreviewFlowStep[];
  position: { x: number; y: number };
}

export interface PreviewFlowEdge {
  id: string;
  source: string;
  target: string;
}

export interface PreviewFlow {
  id: string;
  name: string;
  loop: boolean;
  nodes: PreviewFlowNode[];
  edges: PreviewFlowEdge[];
}

export interface CreateTaskResponse {
  mode?: "cell_manager" | "orchestrator";
  accepted: boolean;
  message: string;
  task_id?: string;
  flow_id?: string;
  queue_depth?: number;
  preview_flow?: PreviewFlow;
}

export interface OrchestratorStateResponse {
  state: OrchestratorState;
  queue_depth: number;
  queue_limit: number;
  active_flow_id?: string | null;
  last_error?: string | null;
}

export interface QueueItem {
  task_id: string;
  flow_id: string;
  instruction: string;
  created_at: number;
}

export interface QueueResponse {
  items: QueueItem[];
}

export interface RunNode {
  name: string;
  type: OrchestratorNodeType;
  status: OrchestratorNodeStatus;
  start_time: number;
  end_time: number;
  artifacts: Record<string, unknown>;
  timeout_ms: number;
}

export interface FlowRunRecord {
  flow_id: string;
  instruction: string;
  state_transitions: Array<{
    from_state: OrchestratorState;
    to_state: OrchestratorState;
    timestamp: number;
    reason: string;
  }>;
  nodes: RunNode[];
  final_status: "SUCCESS" | "FAILURE" | "TIMEOUT" | "ABORTED" | "PARTIAL";
  started_at: number;
  completed_at?: number | null;
  error_message?: string | null;
}

export interface RunsResponse {
  runs: FlowRunRecord[];
}

export interface DecisionPayload {
  action: "retry" | "replan" | "modify_goal" | "safe_stop";
  note?: string;
}

export async function createOrchestratorTask(instruction: string): Promise<CreateTaskResponse> {
  return postJson<CreateTaskResponse>("/orchestrator/tasks", { instruction });
}

export async function getOrchestratorState(): Promise<OrchestratorStateResponse> {
  return getJson<OrchestratorStateResponse>("/orchestrator/state");
}

export async function getOrchestratorQueue(): Promise<QueueResponse> {
  return getJson<QueueResponse>("/orchestrator/queue");
}

export async function listOrchestratorRuns(limit = 20, offset = 0): Promise<RunsResponse> {
  return getJson<RunsResponse>(`/orchestrator/runs?limit=${limit}&offset=${offset}`);
}

export async function getOrchestratorRun(flowId: string): Promise<FlowRunRecord> {
  return getJson<FlowRunRecord>(`/orchestrator/runs/${flowId}`);
}

export async function submitOrchestratorDecision(flowId: string, payload: DecisionPayload): Promise<void> {
  await postJson(`/orchestrator/runs/${flowId}/decision`, payload);
}

export async function requestOrchestratorGoalChange(flowId: string, goal: string): Promise<void> {
  await postJson(`/orchestrator/runs/${flowId}/goal`, { goal });
}
