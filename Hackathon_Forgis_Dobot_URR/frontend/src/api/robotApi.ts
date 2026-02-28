import { apiUrl, getJson, postJson } from "./httpClient";

export interface IoPinState {
  pin: number;
  state: boolean;
}

export interface RobotState {
  timestamp: number;
  connected: boolean;
  joints_deg: number[] | null;
  tcp_pose_mm_deg: number[] | null;
  io: {
    digital_in: IoPinState[];
    digital_out: IoPinState[];
  };
}

interface FlowStatusResponse {
  status: string;
  flow_id?: string | null;
  current_state?: string | null;
  current_step?: string | null;
  error_message?: string | null;
}

interface ManualFlowStep {
  id: string;
  skill: string;
  executor: "robot" | "io_robot";
  params: Record<string, unknown>;
  timeout_ms: number;
}

interface ManualFlowSchema {
  id: string;
  name: string;
  initial_state: string;
  loop: boolean;
  variables: Record<string, unknown>;
  states: Array<{
    name: string;
    steps: ManualFlowStep[];
  }>;
  transitions: Array<{
    type: "sequential" | "conditional";
    from_state: string;
    to_state: string;
    condition?: string;
  }>;
}

interface DirectRobotCommandResponse {
  success: boolean;
  message: string;
}

const STATUS_POLL_MS = 300;
const MANUAL_STATE_NAME = "manual_execute";
const MANUAL_DONE_STATE = "manual_done";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function getFlowStatus(): Promise<FlowStatusResponse> {
  return getJson<FlowStatusResponse>("/flows/status");
}

async function upsertAndStartFlow(flow: ManualFlowSchema): Promise<void> {
  await postJson<{ success: boolean; message: string }>("/flows", flow);
  await postJson<{ success: boolean; message: string }>(`/flows/${flow.id}/start`);
}

async function deleteFlow(flowId: string): Promise<void> {
  const response = await fetch(apiUrl(`/flows/${flowId}`), { method: "DELETE" });
  if (!response.ok && response.status !== 404) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Failed to delete flow '${flowId}'`);
  }
}

function describeFlowProgress(status: FlowStatusResponse): string {
  const state = status.current_state ? `state='${status.current_state}'` : "state='n/a'";
  const step = status.current_step ? `step='${status.current_step}'` : "step='n/a'";
  return `${state}, ${step}, status='${status.status}'`;
}

async function waitForFlowCompletion(flowId: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let hasSeenFlow = false;
  let lastSeenFlowStatus: FlowStatusResponse | null = null;

  while (Date.now() < deadline) {
    const status = await getFlowStatus();

    if (status.flow_id === flowId) {
      hasSeenFlow = true;
      lastSeenFlowStatus = status;

      if (status.status === "completed" || status.status === "idle") {
        return;
      }
      if (status.status === "error" || status.status === "aborted") {
        const progress = describeFlowProgress(status);
        throw new Error(status.error_message || `Flow '${flowId}' failed (${progress})`);
      }
    } else if (hasSeenFlow && status.status === "idle") {
      // Fallback: backend may drop flow_id when returning to idle.
      return;
    }

    await sleep(STATUS_POLL_MS);
  }

  const progress = lastSeenFlowStatus
    ? `Last progress: ${describeFlowProgress(lastSeenFlowStatus)}.`
    : "No progress was reported for this flow.";
  throw new Error(
    `Flow '${flowId}' timed out after ${Math.round(timeoutMs / 1000)}s. ${progress} ` +
      "Check robot remote/external control mode and clear any active protective stop.",
  );
}

export async function getRobotState(): Promise<RobotState> {
  return getJson<RobotState>("/robot/state");
}

function buildSingleStepManualFlow(flowId: string, name: string, step: ManualFlowStep): ManualFlowSchema {
  return {
    id: flowId,
    name,
    initial_state: MANUAL_STATE_NAME,
    loop: false,
    variables: {},
    states: [
      {
        name: MANUAL_STATE_NAME,
        steps: [step],
      },
      {
        name: MANUAL_DONE_STATE,
        steps: [],
      },
    ],
    transitions: [
      {
        type: "sequential",
        from_state: MANUAL_STATE_NAME,
        to_state: MANUAL_DONE_STATE,
      },
    ],
  };
}

async function runManualFlow(flow: ManualFlowSchema, timeoutMs: number): Promise<void> {
  await upsertAndStartFlow(flow);
  try {
    await waitForFlowCompletion(flow.id, timeoutMs);
  } finally {
    await deleteFlow(flow.id).catch(() => undefined);
  }
}

async function ensureRobotConnected(): Promise<void> {
  const robotState = await getRobotState();
  if (!robotState.connected) {
    throw new Error("Robot is offline. Wait for '/api/robot/state' to report connected=true and retry.");
  }
}

function shouldFallbackToFlowExecution(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return message.includes("not found") || message.includes("405") || message.includes("method not allowed");
}

async function executeDirectJogJointCommand(
  targetJointsDeg: number[],
  options?: {
    acceleration?: number;
    velocity?: number;
    toleranceDeg?: number;
    timeoutMs?: number;
  },
): Promise<void> {
  await postJson<DirectRobotCommandResponse>("/robot/jog-joint", {
    target_joints_deg: targetJointsDeg,
    acceleration: options?.acceleration ?? 0.5,
    velocity: options?.velocity ?? 0.5,
    tolerance_deg: options?.toleranceDeg ?? 1.0,
    timeout_ms: options?.timeoutMs ?? 15000,
  });
}

async function executeDirectMoveJointCommand(
  targetJointsDeg: number[],
  options?: {
    acceleration?: number;
    velocity?: number;
    toleranceDeg?: number;
    timeoutMs?: number;
  },
): Promise<void> {
  await postJson<DirectRobotCommandResponse>("/robot/move-joint", {
    target_joints_deg: targetJointsDeg,
    acceleration: options?.acceleration ?? 1.2,
    velocity: options?.velocity ?? 1.0,
    tolerance_deg: options?.toleranceDeg ?? 1.0,
    timeout_ms: options?.timeoutMs ?? 45000,
  });
}

async function executeDirectMoveLinearCommand(
  pose: number[],
  options?: {
    acceleration?: number;
    velocity?: number;
    timeoutMs?: number;
  },
): Promise<void> {
  await postJson<DirectRobotCommandResponse>("/robot/move-linear", {
    pose,
    acceleration: options?.acceleration ?? 1.2,
    velocity: options?.velocity ?? 0.25,
    timeout_ms: options?.timeoutMs ?? 45000,
  });
}

async function executeDirectDigitalOutputCommand(pin: number, value: boolean): Promise<void> {
  await postJson<DirectRobotCommandResponse>("/robot/set-digital-output", { pin, value });
}

export async function executeUrMoveJointCommand(
  targetJointsDeg: number[],
  options?: {
    acceleration?: number;
    velocity?: number;
    toleranceDeg?: number;
    timeoutMs?: number;
  },
): Promise<void> {
  await ensureRobotConnected();

  try {
    await executeDirectMoveJointCommand(targetJointsDeg, options);
    return;
  } catch (error) {
    if (!shouldFallbackToFlowExecution(error)) {
      throw error;
    }
  }

  const flowId = `manual_ur_move_joint_${Date.now()}`;
  const timeoutMs = options?.timeoutMs ?? 45000;
  const stepTimeoutMs = Math.max(1000, timeoutMs - 5000);

  const flow = buildSingleStepManualFlow(flowId, "Manual UR Move Joint", {
    id: "step_move_joint",
    skill: "move_joint",
    executor: "robot",
    params: {
      target_joints_deg: targetJointsDeg,
      acceleration: options?.acceleration ?? 1.2,
      velocity: options?.velocity ?? 1.0,
      tolerance_deg: options?.toleranceDeg ?? 1.0,
    },
    timeout_ms: stepTimeoutMs,
  });

  await runManualFlow(flow, timeoutMs);
}

export async function executeRobotJogJointCommand(
  targetJointsDeg: number[],
  options?: {
    acceleration?: number;
    velocity?: number;
    toleranceDeg?: number;
    timeoutMs?: number;
  },
): Promise<void> {
  await ensureRobotConnected();
  await executeDirectJogJointCommand(targetJointsDeg, options);
}

export async function executeRobotMoveJointCommand(
  targetJointsDeg: number[],
  options?: {
    acceleration?: number;
    velocity?: number;
    toleranceDeg?: number;
    timeoutMs?: number;
  },
): Promise<void> {
  await executeUrMoveJointCommand(targetJointsDeg, options);
}

export async function executeUrDigitalOutputCommand(
  pin: number,
  value: boolean,
  timeoutMs = 15000,
): Promise<void> {
  await ensureRobotConnected();

  try {
    await executeDirectDigitalOutputCommand(pin, value);
    return;
  } catch (error) {
    if (!shouldFallbackToFlowExecution(error)) {
      throw error;
    }
  }

  const flowId = `manual_ur_set_do_${Date.now()}`;

  const flow = buildSingleStepManualFlow(flowId, "Manual UR Set DO", {
    id: "step_set_do",
    skill: "io_set_digital_output",
    executor: "io_robot",
    params: {
      pin,
      value,
    },
    timeout_ms: Math.max(1000, timeoutMs - 2000),
  });

  await runManualFlow(flow, timeoutMs);
}

export async function executeRobotDigitalOutputCommand(
  pin: number,
  value: boolean,
  timeoutMs = 15000,
): Promise<void> {
  await executeUrDigitalOutputCommand(pin, value, timeoutMs);
}

export async function executeRobotMoveLinearCommand(
  pose: number[],
  options?: {
    acceleration?: number;
    velocity?: number;
    timeoutMs?: number;
  },
): Promise<void> {
  await ensureRobotConnected();

  try {
    await executeDirectMoveLinearCommand(pose, options);
    return;
  } catch (error) {
    if (!shouldFallbackToFlowExecution(error)) {
      throw error;
    }
  }

  const flowId = `manual_ur_move_linear_${Date.now()}`;
  const timeoutMs = options?.timeoutMs ?? 45000;
  const stepTimeoutMs = Math.max(1000, timeoutMs - 5000);

  const flow = buildSingleStepManualFlow(flowId, "Manual UR Move Linear", {
    id: "step_move_linear",
    skill: "move_linear",
    executor: "robot",
    params: {
      pose,
      acceleration: options?.acceleration ?? 1.2,
      velocity: options?.velocity ?? 0.25,
    },
    timeout_ms: stepTimeoutMs,
  });

  await runManualFlow(flow, timeoutMs);
}
