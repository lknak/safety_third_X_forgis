import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Bot,
  Crosshair,
  Loader2,
  Move,
  PlugZap,
  RefreshCcw,
  SlidersHorizontal,
} from "lucide-react";
import type { Device } from "@/types";
import {
  executeRobotDigitalOutputCommand,
  executeRobotJogJointCommand,
  executeRobotMoveJointCommand,
  executeRobotMoveLinearCommand,
  getRobotState,
  type RobotState,
} from "@/api/robotApi";
import { getOverallHealth } from "@/api/healthApi";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface DeviceControlPanelProps {
  device: Device;
  className?: string;
}

type CommandState =
  | { type: "idle"; message: string }
  | { type: "running"; message: string }
  | { type: "success"; message: string }
  | { type: "error"; message: string };

const JOINT_LABELS = ["J1", "J2", "J3", "J4", "J5", "J6"];
const POSE_LABELS = ["X", "Y", "Z", "Rx", "Ry", "Rz"];
const POSE_UNITS = ["mm", "mm", "mm", "deg", "deg", "deg"];
const JOINT_STEP_OPTIONS = [1, 2, 5];

function isRobotDevice(device: Device): boolean {
  return device.type === "robot";
}

function formatJoint(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return value.toFixed(2);
}

function formatPose(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return value.toFixed(1);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Normalise joint angle to 0..1 range for progress bar (±360 deg) */
function jointProgress(deg: number): number {
  return clamp((deg + 360) / 720, 0, 1);
}

/* ─────────────────────── Live Position Display ─────────────────────── */

function LivePositionDisplay({ robotState }: { robotState: RobotState | null }) {
  const joints = robotState?.joints_deg;
  const pose = robotState?.tcp_pose_mm_deg;

  return (
    <div className="space-y-2">
      {/* Joint angles */}
      <div className="rounded-lg border border-border/60 bg-card p-2.5">
        <h4 className="mb-1.5 forgis-text-caption font-forgis-digit uppercase tracking-wider text-[var(--gunmetal-50)]">
          Joint Positions
        </h4>
        <div className="grid grid-cols-3 gap-x-3 gap-y-1">
          {JOINT_LABELS.map((label, i) => {
            const val = joints?.[i];
            const progress = val !== undefined && val !== null ? jointProgress(val) : 0.5;
            return (
              <div key={label} className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between">
                  <span className="text-[9px] uppercase tracking-wider font-forgis-digit text-[var(--gunmetal-50)]">
                    {label}
                  </span>
                  <span className="text-[11px] font-forgis-digit tabular-nums text-foreground">
                    {formatJoint(val ?? undefined)}&deg;
                  </span>
                </div>
                <div className="h-1 w-full rounded-full bg-muted/40 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary/70 transition-all duration-300"
                    style={{ width: `${progress * 100}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* TCP Cartesian pose */}
      <div className="rounded-lg border border-border/60 bg-card p-2.5">
        <h4 className="mb-1.5 forgis-text-caption font-forgis-digit uppercase tracking-wider text-[var(--gunmetal-50)]">
          TCP Pose
        </h4>
        {pose ? (
          <div className="grid grid-cols-3 gap-x-3 gap-y-1">
            {POSE_LABELS.map((label, i) => (
              <div key={label} className="flex items-center justify-between rounded bg-muted/20 px-1.5 py-1">
                <span className="text-[9px] uppercase tracking-wider font-forgis-digit text-[var(--gunmetal-50)]">
                  {label}
                </span>
                <span className="text-[11px] font-forgis-digit tabular-nums text-foreground">
                  {formatPose(pose[i])}
                  <span className="text-[8px] text-[var(--gunmetal-50)] ml-0.5">{POSE_UNITS[i]}</span>
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[10px] text-[var(--gunmetal-50)] font-forgis-body">
            TCP pose unavailable — waiting for tcp_pose_broadcaster
          </div>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────── Robot Control Pane ─────────────────────── */

function RobotControlPane({ device }: { device: Device }) {
  const [robotState, setRobotState] = useState<RobotState | null>(null);
  const [loadingState, setLoadingState] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const [ioAvailable, setIoAvailable] = useState(false);

  // MoveJ state
  const [jointTargets, setJointTargets] = useState<number[]>(Array(6).fill(0));
  const [targetsDirty, setTargetsDirty] = useState(false);
  const [jointStepDeg, setJointStepDeg] = useState(2);
  const [acceleration, setAcceleration] = useState(1.2);
  const [velocity, setVelocity] = useState(1.0);
  const targetsDirtyRef = useRef(false);

  // MoveL state
  const [poseTargets, setPoseTargets] = useState<number[]>(Array(6).fill(0));
  const [poseDirty, setPoseDirty] = useState(false);
  const [linAccel, setLinAccel] = useState(1.2);
  const [linVel, setLinVel] = useState(0.25);

  // IO state
  const [doPin, setDoPin] = useState(0);

  const [commandState, setCommandState] = useState<CommandState>({
    type: "idle",
    message: "Ready",
  });

  useEffect(() => {
    targetsDirtyRef.current = targetsDirty;
  }, [targetsDirty]);

  /* ── Fast polling (500ms) ── */
  const refreshState = useCallback(async () => {
    setLoadingState(true);
    setReadError(null);
    try {
      const state = await getRobotState();
      setRobotState(state);
      // Auto-sync joint targets from live state when user hasn't edited them
      if (!targetsDirtyRef.current && state.joints_deg && state.joints_deg.length === 6) {
        setJointTargets(state.joints_deg.map((j) => Number(j.toFixed(2))));
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Failed to read robot state";
      setReadError(detail);
    } finally {
      setLoadingState(false);
    }
  }, []);

  useEffect(() => {
    void refreshState();
    const interval = window.setInterval(() => {
      void refreshState();
    }, 500);
    return () => window.clearInterval(interval);
  }, [refreshState]);

  /* ── IO capability check ── */
  useEffect(() => {
    let disposed = false;
    const syncCapabilities = async () => {
      try {
        const health = await getOverallHealth();
        if (disposed) return;
        const ioHealth = health.devices.io_robot;
        setIoAvailable(ioHealth?.status === "connected");
      } catch {
        if (!disposed) setIoAvailable(false);
      }
    };
    void syncCapabilities();
    const interval = window.setInterval(() => void syncCapabilities(), 5000);
    return () => { disposed = true; window.clearInterval(interval); };
  }, []);

  /* ── Action executor ── */
  const executeAction = useCallback(
    async (label: string, action: () => Promise<void>) => {
      setCommandState({ type: "running", message: `${label} in progress...` });
      try {
        await action();
        setCommandState({ type: "success", message: `${label} completed` });
        await refreshState();
        return true;
      } catch (error) {
        const detail = error instanceof Error ? error.message : `${label} failed`;
        setCommandState({ type: "error", message: detail });
        return false;
      }
    },
    [refreshState],
  );

  const connected = robotState?.connected ?? false;
  const busy = commandState.type === "running";
  const currentJoints = robotState?.joints_deg;
  const currentPose = robotState?.tcp_pose_mm_deg;

  /* ── MoveJ jog ── */
  const handleJog = async (jointIndex: number, direction: -1 | 1) => {
    if (!currentJoints || currentJoints.length !== 6) {
      setCommandState({ type: "error", message: "No live joint telemetry. Refresh state first." });
      return;
    }
    const target = [...currentJoints];
    target[jointIndex] = Number((target[jointIndex] + direction * jointStepDeg).toFixed(2));
    setJointTargets(target);
    setTargetsDirty(true);
    const success = await executeAction(`${JOINT_LABELS[jointIndex]} jog`, async () => {
      await executeRobotJogJointCommand(target, { acceleration, velocity, toleranceDeg: 1.0, timeoutMs: 15000 });
    });
    if (success) setTargetsDirty(false);
  };

  /* ── MoveJ target ── */
  const handleMoveToTargets = async () => {
    if (jointTargets.length !== 6 || jointTargets.some((j) => Number.isNaN(j))) {
      setCommandState({ type: "error", message: "Invalid target joints. Provide 6 numeric values." });
      return;
    }
    const success = await executeAction("MoveJ target", async () => {
      await executeRobotMoveJointCommand(jointTargets, { acceleration, velocity, toleranceDeg: 1.0 });
    });
    if (success) setTargetsDirty(false);
  };

  /* ── MoveL target ── */
  const handleMoveLinear = async () => {
    if (poseTargets.length !== 6 || poseTargets.some((v) => Number.isNaN(v))) {
      setCommandState({ type: "error", message: "Invalid pose. Provide 6 numeric values." });
      return;
    }
    // Convert from mm/deg display units to m/rad for the backend
    const poseMetersRad = [
      poseTargets[0] / 1000, poseTargets[1] / 1000, poseTargets[2] / 1000,
      (poseTargets[3] * Math.PI) / 180, (poseTargets[4] * Math.PI) / 180, (poseTargets[5] * Math.PI) / 180,
    ];
    const success = await executeAction("MoveL target", async () => {
      await executeRobotMoveLinearCommand(poseMetersRad, { acceleration: linAccel, velocity: linVel });
    });
    if (success) setPoseDirty(false);
  };

  /* ── Digital output ── */
  const handleSetDo = async (value: boolean) => {
    await executeAction(`DO[${doPin}] -> ${value ? "HIGH" : "LOW"}`, async () => {
      await executeRobotDigitalOutputCommand(doPin, value);
    });
  };

  const commandBorderClass =
    commandState.type === "error"
      ? "border-[var(--status-critical)]/40 bg-[var(--status-critical)]/5 text-[var(--status-critical)]"
      : commandState.type === "success"
        ? "border-[var(--status-healthy)]/40 bg-[var(--status-healthy)]/5 text-[var(--status-healthy)]"
        : commandState.type === "running"
          ? "border-primary/40 bg-primary/5 text-primary animate-pulse"
          : "border-border/70 bg-muted/20 text-[var(--gunmetal-50)]";

  return (
    <div className="space-y-2.5">
      {/* ── Connection + Sync ── */}
      <div className="flex items-center justify-between rounded-lg border border-border/60 bg-card px-3 py-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-2.5 w-2.5 rounded-full",
              connected
                ? "bg-[var(--status-healthy)] shadow-[0_0_6px_var(--status-healthy)]"
                : "bg-[var(--status-critical)]",
            )}
          />
          <span className="forgis-text-detail font-forgis-body">
            {connected ? `${device.name} connected` : `${device.name} offline`}
          </span>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="h-7 px-2.5 text-[10px] uppercase tracking-wider font-forgis-digit"
          disabled={loadingState || busy}
          onClick={() => void refreshState()}
        >
          <RefreshCcw className={cn("h-3.5 w-3.5", loadingState && "animate-spin")} />
          Sync
        </Button>
      </div>

      {readError && (
        <div className="rounded-lg border border-[var(--status-critical)]/40 bg-[var(--status-critical)]/5 px-3 py-2">
          <div className="forgis-text-detail text-[var(--status-critical)] font-forgis-body">{readError}</div>
        </div>
      )}

      {/* ── Command status ── */}
      <div className={cn("rounded-lg border px-3 py-1.5", commandBorderClass)}>
        <div className="forgis-text-detail font-forgis-body flex items-center gap-1.5">
          {commandState.type === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
          {commandState.message}
        </div>
      </div>

      {/* ── Live position display ── */}
      <LivePositionDisplay robotState={robotState} />

      {/* ── Joint Jog ── */}
      <div className="rounded-lg border border-border/60 bg-card p-2.5">
        <div className="mb-1.5 flex items-center justify-between">
          <h4 className="forgis-text-caption font-forgis-digit uppercase tracking-wider text-[var(--gunmetal-50)]">
            Joint Jog
          </h4>
          <div className="flex items-center gap-1">
            {JOINT_STEP_OPTIONS.map((step) => (
              <button
                key={step}
                className={cn(
                  "rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider border transition-colors",
                  step === jointStepDeg
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border/60 text-[var(--gunmetal-50)] hover:bg-muted/40",
                )}
                disabled={busy || !connected}
                onClick={() => setJointStepDeg(step)}
              >
                {step}&deg;
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-1">
          {JOINT_LABELS.map((label, index) => (
            <div key={label} className="flex items-center gap-1 rounded bg-muted/20 px-1.5 py-1">
              <div className="w-6 text-[9px] uppercase tracking-wider font-forgis-digit text-[var(--gunmetal-50)]">
                {label}
              </div>
              <Button
                size="sm"
                variant="outline"
                className="h-6 w-8 text-[10px] font-forgis-digit p-0"
                disabled={busy || !connected}
                onClick={() => void handleJog(index, -1)}
              >
                -
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-6 w-8 text-[10px] font-forgis-digit p-0"
                disabled={busy || !connected}
                onClick={() => void handleJog(index, 1)}
              >
                +
              </Button>
            </div>
          ))}
        </div>
      </div>

      {/* ── MoveJ Target ── */}
      <div className="rounded-lg border border-border/60 bg-card p-2.5">
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <h4 className="forgis-text-caption font-forgis-digit uppercase tracking-wider text-[var(--gunmetal-50)] flex items-center gap-1">
            <SlidersHorizontal className="h-3 w-3" /> MoveJ
          </h4>
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-[9px] uppercase tracking-wider font-forgis-digit"
            disabled={busy || !connected}
            onClick={() => {
              if (currentJoints && currentJoints.length === 6) {
                setJointTargets(currentJoints.map((j) => Number(j.toFixed(2))));
                setTargetsDirty(false);
              }
            }}
          >
            Use Current
          </Button>
        </div>
        <div className="grid grid-cols-3 gap-1">
          {jointTargets.map((value, index) => (
            <div key={JOINT_LABELS[index]} className="relative">
              <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-[8px] uppercase font-forgis-digit text-[var(--gunmetal-50)]">
                {JOINT_LABELS[index]}
              </span>
              <Input
                type="number"
                step="0.1"
                value={Number.isFinite(value) ? value : ""}
                disabled={busy || !connected}
                className="h-7 pl-7 text-[10px] font-forgis-digit"
                onChange={(e) => {
                  const v = Number.parseFloat(e.target.value);
                  setTargetsDirty(true);
                  setJointTargets((prev) =>
                    prev.map((j, i) => (i === index ? (Number.isNaN(v) ? j : v) : j)),
                  );
                }}
              />
            </div>
          ))}
        </div>

        <div className="mt-1.5 grid grid-cols-[1fr_1fr_auto] gap-1.5 items-end">
          <div>
            <span className="text-[8px] uppercase tracking-wider text-[var(--gunmetal-50)] font-forgis-digit">accel</span>
            <Input
              type="number" step="0.1" min={0.1} max={2.0} value={acceleration}
              disabled={busy || !connected} className="h-7 text-[10px] font-forgis-digit"
              onChange={(e) => { const v = Number.parseFloat(e.target.value); if (!Number.isNaN(v)) setAcceleration(clamp(v, 0.1, 2.0)); }}
            />
          </div>
          <div>
            <span className="text-[8px] uppercase tracking-wider text-[var(--gunmetal-50)] font-forgis-digit">vel</span>
            <Input
              type="number" step="0.1" min={0.1} max={2.0} value={velocity}
              disabled={busy || !connected} className="h-7 text-[10px] font-forgis-digit"
              onChange={(e) => { const v = Number.parseFloat(e.target.value); if (!Number.isNaN(v)) setVelocity(clamp(v, 0.1, 2.0)); }}
            />
          </div>
          <Button
            className="h-7 px-3 text-[10px] uppercase tracking-wider font-forgis-digit"
            disabled={busy || !connected}
            onClick={() => void handleMoveToTargets()}
          >
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Move className="h-3 w-3" />}
            Go
          </Button>
        </div>
      </div>

      {/* ── MoveL Target ── */}
      <div className="rounded-lg border border-border/60 bg-card p-2.5">
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <h4 className="forgis-text-caption font-forgis-digit uppercase tracking-wider text-[var(--gunmetal-50)] flex items-center gap-1">
            <Crosshair className="h-3 w-3" /> MoveL
          </h4>
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-[9px] uppercase tracking-wider font-forgis-digit"
            disabled={busy || !connected || !currentPose}
            onClick={() => {
              if (currentPose && currentPose.length === 6) {
                setPoseTargets(currentPose.map((v) => Number(v.toFixed(1))));
                setPoseDirty(false);
              }
            }}
          >
            Use Current
          </Button>
        </div>
        <div className="grid grid-cols-3 gap-1">
          {poseTargets.map((value, index) => (
            <div key={POSE_LABELS[index]} className="relative">
              <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-[8px] uppercase font-forgis-digit text-[var(--gunmetal-50)]">
                {POSE_LABELS[index]}
              </span>
              <Input
                type="number"
                step={index < 3 ? "1" : "0.1"}
                value={Number.isFinite(value) ? value : ""}
                disabled={busy || !connected}
                className="h-7 pl-7 text-[10px] font-forgis-digit"
                onChange={(e) => {
                  const v = Number.parseFloat(e.target.value);
                  setPoseDirty(true);
                  setPoseTargets((prev) =>
                    prev.map((p, i) => (i === index ? (Number.isNaN(v) ? p : v) : p)),
                  );
                }}
              />
            </div>
          ))}
        </div>
        <div className="mt-0.5 grid grid-cols-3 gap-1 text-[8px] text-[var(--gunmetal-50)] font-forgis-digit text-center">
          {POSE_UNITS.map((u, i) => <span key={i}>{u}</span>)}
        </div>

        <div className="mt-1.5 grid grid-cols-[1fr_1fr_auto] gap-1.5 items-end">
          <div>
            <span className="text-[8px] uppercase tracking-wider text-[var(--gunmetal-50)] font-forgis-digit">accel</span>
            <Input
              type="number" step="0.1" min={0.01} max={3.0} value={linAccel}
              disabled={busy || !connected} className="h-7 text-[10px] font-forgis-digit"
              onChange={(e) => { const v = Number.parseFloat(e.target.value); if (!Number.isNaN(v)) setLinAccel(clamp(v, 0.01, 3.0)); }}
            />
          </div>
          <div>
            <span className="text-[8px] uppercase tracking-wider text-[var(--gunmetal-50)] font-forgis-digit">vel</span>
            <Input
              type="number" step="0.01" min={0.01} max={1.0} value={linVel}
              disabled={busy || !connected} className="h-7 text-[10px] font-forgis-digit"
              onChange={(e) => { const v = Number.parseFloat(e.target.value); if (!Number.isNaN(v)) setLinVel(clamp(v, 0.01, 1.0)); }}
            />
          </div>
          <Button
            className="h-7 px-3 text-[10px] uppercase tracking-wider font-forgis-digit"
            disabled={busy || !connected}
            onClick={() => void handleMoveLinear()}
          >
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Crosshair className="h-3 w-3" />}
            Go
          </Button>
        </div>
      </div>

      {/* ── Digital Output ── */}
      {ioAvailable ? (
        <div className="rounded-lg border border-border/60 bg-card p-2.5">
          <h4 className="mb-1.5 forgis-text-caption font-forgis-digit uppercase tracking-wider text-[var(--gunmetal-50)]">
            Digital Output
          </h4>
          <div className="grid grid-cols-[1fr_1fr_1fr] gap-1.5">
            <Input
              type="number" min={0} max={7} value={doPin}
              disabled={busy || !connected} className="h-7 text-[10px] font-forgis-digit"
              onChange={(e) => { const v = Number.parseInt(e.target.value, 10); if (!Number.isNaN(v)) setDoPin(clamp(v, 0, 7)); }}
            />
            <Button
              size="sm" variant="outline" className="h-7 text-[10px] font-forgis-digit"
              disabled={busy || !connected} onClick={() => void handleSetDo(true)}
            >
              HIGH
            </Button>
            <Button
              size="sm" variant="outline" className="h-7 text-[10px] font-forgis-digit"
              disabled={busy || !connected} onClick={() => void handleSetDo(false)}
            >
              LOW
            </Button>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-border/60 bg-card p-2.5 text-[10px] text-[var(--gunmetal-50)] font-forgis-body">
          Digital I/O executor is unavailable or offline.
        </div>
      )}
    </div>
  );
}

/* ─────────────────────── Main Panel Wrapper ─────────────────────── */

export function DeviceControlPanel({ device, className }: DeviceControlPanelProps) {
  const robotDevice = useMemo(() => isRobotDevice(device), [device]);

  return (
    <div className={cn("flex flex-1 min-h-0 flex-col border-t border-border", className)}>
      <div className="flex items-center justify-between px-3 pt-2.5 pb-2">
        <div className="min-w-0">
          <div className="forgis-text-label font-forgis-digit uppercase text-[var(--gunmetal-50)]">
            Device Panel
          </div>
          <div className="truncate text-[11px] font-forgis-body text-foreground">
            {device.name} - {device.vendor}
          </div>
        </div>
        <Badge variant="outline" className="text-[10px] uppercase tracking-wider font-forgis-digit">
          {device.type}
        </Badge>
      </div>

      <Tabs defaultValue="guide" className="flex flex-1 min-h-0 flex-col px-3 pb-3">
        <TabsList className="grid h-8 w-full grid-cols-2">
          <TabsTrigger value="guide" className="text-[10px] uppercase tracking-wider font-forgis-digit">
            <BookOpen className="h-3.5 w-3.5" />
            Guide
          </TabsTrigger>
          <TabsTrigger value="control" className="text-[10px] uppercase tracking-wider font-forgis-digit">
            <Bot className="h-3.5 w-3.5" />
            Control
          </TabsTrigger>
        </TabsList>

        <TabsContent value="guide" className="mt-2 flex-1 overflow-y-auto">
          {robotDevice ? (
            <div className="space-y-3 rounded-lg border border-border/60 bg-card p-3">
              <div className="flex items-center gap-2">
                <PlugZap className="h-4 w-4 text-primary" />
                <h4 className="forgis-text-label font-forgis-digit uppercase text-[var(--gunmetal-50)]">Robot Operational Guide</h4>
              </div>

              <ol className="space-y-2 text-[11px] leading-relaxed text-foreground/90 font-forgis-body">
                <li>1. Keep PC and controller on the same subnet, and verify reachability using ping.</li>
                <li>2. Run backend + matching driver profile (`ROBOT_TYPE` and `COMPOSE_PROFILES`) with correct robot IP in `.env`.</li>
                <li>3. Put the robot in remote/external mode so ROS control is accepted (UR: External Control, DOBOT: Remote TCP).</li>
                <li>4. Confirm `/api/robot/state` reports `connected: true` before sending commands.</li>
                <li>5. Use small jog increments first, then execute full target motions.</li>
              </ol>

              <div className="rounded-md border border-[var(--orange)]/40 bg-[var(--orange)]/10 px-2.5 py-2 text-[10px] text-[var(--gunmetal)] font-forgis-body">
                <div className="mb-1 flex items-center gap-1.5 font-semibold uppercase tracking-wide font-forgis-digit">
                  <AlertTriangle className="h-3.5 w-3.5 text-[var(--orange)]" />
                  Safety
                </div>
                Keep a clear workspace, verify tool/TCP setup, and use small jog steps first.
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-border/60 bg-card p-3">
              <div className="forgis-text-detail text-[var(--gunmetal-50)] font-forgis-body">
                Operational guide for this device will be added in the next iteration.
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="control" className="mt-2 flex-1 overflow-y-auto">
          {robotDevice ? (
            <RobotControlPane device={device} />
          ) : (
            <div className="rounded-lg border border-border/60 bg-card p-3">
              <div className="forgis-text-detail text-[var(--gunmetal-50)] font-forgis-body">
                Control is available only for devices of type `robot`.
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
