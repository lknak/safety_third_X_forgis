import { apiUrl, getJson, postJson } from "./httpClient";

export interface IoPinState {
  pin: number;
  state: boolean;
}

export interface RobotState {
  timestamp: number;
  connected: boolean;
  joints_deg: number[] | null;
  io: {
    digital_in: IoPinState[];
    digital_out: IoPinState[];
  };
}

interface FlowStatusResponse {
  status: string;
  flow_id?: string | null;
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

const STATUS_POLL_MS = 300;

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

async function waitForFlowCompletion(flowId: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let hasSeenFlow = false;

  while (Date.now() < deadline) {
    const status = await getFlowStatus();

    if (status.flow_id === flowId) {
      hasSeenFlow = true;

      if (status.status === "completed" || status.status === "idle") {
        return;
      }
      if (status.status === "error" || status.status === "aborted") {
        throw new Error(status.error_message || `Flow '${flowId}' failed`);
      }
    } else if (hasSeenFlow && status.status === "idle") {
      // Fallback: backend may drop flow_id when returning to idle.
      return;
    }

    await sleep(STATUS_POLL_MS);
  }

  throw new Error(`Flow '${flowId}' timed out after ${Math.round(timeoutMs / 1000)}s`);
}

export async function getRobotState(): Promise<RobotState> {
  return getJson<RobotState>("/robot/state");
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
  const flowId = `manual_ur_move_joint_${Date.now()}`;
  const timeoutMs = options?.timeoutMs ?? 70000;
  const stepTimeoutMs = Math.max(1000, timeoutMs - 5000);

  const flow: ManualFlowSchema = {
    id: flowId,
    name: "Manual UR Move Joint",
    initial_state: "manual_move_joint",
    loop: false,
    variables: {},
    states: [
      {
        name: "manual_move_joint",
        steps: [
          {
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
          },
        ],
      },
    ],
    transitions: [],
  };

  await upsertAndStartFlow(flow);
  try {
    await waitForFlowCompletion(flowId, timeoutMs);
  } finally {
    await deleteFlow(flowId).catch(() => undefined);
  }
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
  const flowId = `manual_ur_set_do_${Date.now()}`;

  const flow: ManualFlowSchema = {
    id: flowId,
    name: "Manual UR Set DO",
    initial_state: "manual_set_do",
    loop: false,
    variables: {},
    states: [
      {
        name: "manual_set_do",
        steps: [
          {
            id: "step_set_do",
            skill: "io_set_digital_output",
            executor: "io_robot",
            params: {
              pin,
              value,
            },
            timeout_ms: Math.max(1000, timeoutMs - 2000),
          },
        ],
      },
    ],
    transitions: [],
  };

  await upsertAndStartFlow(flow);
  try {
    await waitForFlowCompletion(flowId, timeoutMs);
  } finally {
    await deleteFlow(flowId).catch(() => undefined);
  }
}

export async function executeRobotDigitalOutputCommand(
  pin: number,
  value: boolean,
  timeoutMs = 15000,
): Promise<void> {
  await executeUrDigitalOutputCommand(pin, value, timeoutMs);
}
