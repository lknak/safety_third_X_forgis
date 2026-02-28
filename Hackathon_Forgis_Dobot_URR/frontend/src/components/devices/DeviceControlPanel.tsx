import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Bot,
  Loader2,
  PlugZap,
  RefreshCcw,
  SlidersHorizontal,
} from "lucide-react";
import type { Device } from "@/types";
import {
  executeRobotDigitalOutputCommand,
  executeRobotMoveJointCommand,
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
const JOINT_STEP_OPTIONS = [1, 2, 5];

function isRobotDevice(device: Device): boolean {
  return device.type === "robot";
}

function formatJoint(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return `${value.toFixed(2)} deg`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function RobotControlPane({ device }: { device: Device }) {
  const [robotState, setRobotState] = useState<RobotState | null>(null);
  const [loadingState, setLoadingState] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const [ioAvailable, setIoAvailable] = useState(false);

  const [jointTargets, setJointTargets] = useState<number[]>(Array(6).fill(0));
  const [targetsDirty, setTargetsDirty] = useState(false);
  const [jointStepDeg, setJointStepDeg] = useState(2);
  const [acceleration, setAcceleration] = useState(1.2);
  const [velocity, setVelocity] = useState(1.0);
  const [doPin, setDoPin] = useState(0);
  const targetsDirtyRef = useRef(false);

  const [commandState, setCommandState] = useState<CommandState>({
    type: "idle",
    message: "Ready",
  });

  useEffect(() => {
    targetsDirtyRef.current = targetsDirty;
  }, [targetsDirty]);

  const refreshState = useCallback(async () => {
    setLoadingState(true);
    setReadError(null);
    try {
      const state = await getRobotState();
      setRobotState(state);
      if (!targetsDirtyRef.current && state.joints_deg && state.joints_deg.length === 6) {
        setJointTargets(state.joints_deg.map((joint) => Number(joint.toFixed(2))));
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
    }, 2500);
    return () => window.clearInterval(interval);
  }, [refreshState]);

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
    const interval = window.setInterval(() => {
      void syncCapabilities();
    }, 5000);

    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, []);

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

  const handleJog = async (jointIndex: number, direction: -1 | 1) => {
    if (!currentJoints || currentJoints.length !== 6) {
      setCommandState({
        type: "error",
        message: "No live joint telemetry available. Refresh state first.",
      });
      return;
    }

    const target = [...currentJoints];
    target[jointIndex] = Number((target[jointIndex] + direction * jointStepDeg).toFixed(2));
    setJointTargets(target);
    setTargetsDirty(true);

    const success = await executeAction(`${JOINT_LABELS[jointIndex]} jog`, async () => {
      await executeRobotMoveJointCommand(target, {
        acceleration,
        velocity,
        toleranceDeg: 1.0,
      });
    });
    if (success) {
      setTargetsDirty(false);
    }
  };

  const handleMoveToTargets = async () => {
    if (jointTargets.length !== 6 || jointTargets.some((joint) => Number.isNaN(joint))) {
      setCommandState({ type: "error", message: "Invalid target joints. Provide 6 numeric values." });
      return;
    }

    const success = await executeAction("MoveJ target", async () => {
      await executeRobotMoveJointCommand(jointTargets, {
        acceleration,
        velocity,
        toleranceDeg: 1.0,
      });
    });
    if (success) {
      setTargetsDirty(false);
    }
  };

  const handleSetDo = async (value: boolean) => {
    await executeAction(`DO[${doPin}] -> ${value ? "HIGH" : "LOW"}`, async () => {
      await executeRobotDigitalOutputCommand(doPin, value);
    });
  };

  const commandStateClasses =
    commandState.type === "error"
      ? "text-[var(--status-critical)] border-[var(--status-critical)]/40 bg-[var(--status-critical)]/5"
      : commandState.type === "success"
        ? "text-[var(--status-healthy)] border-[var(--status-healthy)]/40 bg-[var(--status-healthy)]/5"
        : "text-[var(--gunmetal-50)] border-border/70 bg-muted/20";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-lg border border-border/60 bg-card px-3 py-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-2 w-2 rounded-full",
              connected ? "bg-[var(--status-healthy)]" : "bg-[var(--status-critical)]",
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

      <div className={cn("rounded-lg border px-3 py-2", commandStateClasses)}>
        <div className="forgis-text-detail font-forgis-body">{commandState.message}</div>
      </div>

      <div className="rounded-lg border border-border/60 bg-card p-3">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="forgis-text-label font-forgis-digit uppercase text-[var(--gunmetal-50)]">Joint Jog</h4>
          <div className="flex items-center gap-1">
            {JOINT_STEP_OPTIONS.map((step) => (
              <button
                key={step}
                className={cn(
                  "rounded px-2 py-1 text-[10px] uppercase tracking-wider border transition-colors",
                  step === jointStepDeg
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border/60 text-[var(--gunmetal-50)] hover:bg-muted/40",
                )}
                disabled={busy || !connected}
                onClick={() => setJointStepDeg(step)}
              >
                {step} deg
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-1.5">
          {JOINT_LABELS.map((label, index) => (
            <div key={label} className="grid grid-cols-[30px_1fr_58px_58px] items-center gap-2 rounded bg-muted/20 px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider font-forgis-digit text-[var(--gunmetal-50)]">{label}</div>
              <div className="text-[11px] font-forgis-digit text-foreground">{formatJoint(currentJoints?.[index])}</div>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-[11px] font-forgis-digit"
                disabled={busy || !connected}
                onClick={() => void handleJog(index, -1)}
              >
                -
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-[11px] font-forgis-digit"
                disabled={busy || !connected}
                onClick={() => void handleJog(index, 1)}
              >
                +
              </Button>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border/60 bg-card p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h4 className="forgis-text-label font-forgis-digit uppercase text-[var(--gunmetal-50)]">MoveJ Target</h4>
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5 text-[10px] uppercase tracking-wider font-forgis-digit"
            disabled={busy || !connected}
            onClick={() => {
              if (currentJoints && currentJoints.length === 6) {
                setJointTargets(currentJoints.map((joint) => Number(joint.toFixed(2))));
                setTargetsDirty(false);
              } else {
                void refreshState();
              }
            }}
          >
            Use Current Joints
          </Button>
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          {jointTargets.map((value, index) => (
            <Input
              key={JOINT_LABELS[index]}
              type="number"
              step="0.1"
              value={Number.isFinite(value) ? value : ""}
              disabled={busy || !connected}
              className="h-8 text-[11px] font-forgis-digit"
              onChange={(event) => {
                const nextValue = Number.parseFloat(event.target.value);
                setTargetsDirty(true);
                setJointTargets((prev) =>
                  prev.map((joint, jointIndex) => (jointIndex === index ? (Number.isNaN(nextValue) ? joint : nextValue) : joint)),
                );
              }}
            />
          ))}
        </div>

        <div className="mt-2 grid grid-cols-2 gap-2">
          <Input
            type="number"
            step="0.1"
            min={0.1}
            max={2.0}
            value={acceleration}
            disabled={busy || !connected}
            className="h-8 text-[11px] font-forgis-digit"
            onChange={(event) => {
              const next = Number.parseFloat(event.target.value);
              if (!Number.isNaN(next)) setAcceleration(clamp(next, 0.1, 2.0));
            }}
          />
          <Input
            type="number"
            step="0.1"
            min={0.1}
            max={2.0}
            value={velocity}
            disabled={busy || !connected}
            className="h-8 text-[11px] font-forgis-digit"
            onChange={(event) => {
              const next = Number.parseFloat(event.target.value);
              if (!Number.isNaN(next)) setVelocity(clamp(next, 0.1, 2.0));
            }}
          />
        </div>
        <div className="mt-1 grid grid-cols-2 gap-2 text-[9px] uppercase tracking-wider text-[var(--gunmetal-50)] font-forgis-digit">
          <span>acceleration</span>
          <span>velocity</span>
        </div>

        <Button
          className="mt-3 h-8 w-full text-[11px] uppercase tracking-wider font-forgis-digit"
          disabled={busy || !connected}
          onClick={() => void handleMoveToTargets()}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <SlidersHorizontal className="h-3.5 w-3.5" />}
          Execute MoveJ
        </Button>
      </div>

      {ioAvailable ? (
        <div className="rounded-lg border border-border/60 bg-card p-3">
          <h4 className="mb-2 forgis-text-label font-forgis-digit uppercase text-[var(--gunmetal-50)]">Digital Output</h4>
          <div className="grid grid-cols-[1fr_1fr_1fr] gap-2">
            <Input
              type="number"
              min={0}
              max={7}
              value={doPin}
              disabled={busy || !connected}
              className="h-8 text-[11px] font-forgis-digit"
              onChange={(event) => {
                const next = Number.parseInt(event.target.value, 10);
                if (!Number.isNaN(next)) setDoPin(clamp(next, 0, 7));
              }}
            />
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-[11px] font-forgis-digit"
              disabled={busy || !connected}
              onClick={() => void handleSetDo(true)}
            >
              HIGH
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-[11px] font-forgis-digit"
              disabled={busy || !connected}
              onClick={() => void handleSetDo(false)}
            >
              LOW
            </Button>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-border/60 bg-card p-3 text-[11px] text-[var(--gunmetal-50)] font-forgis-body">
          Digital I/O executor is unavailable or offline for the current robot configuration.
        </div>
      )}
    </div>
  );
}

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
                <li>
                  1. Keep PC and controller on the same subnet, and verify reachability using ping.
                </li>
                <li>
                  2. Run backend + matching driver profile (`ROBOT_TYPE` and `COMPOSE_PROFILES`) with correct robot IP in `.env`.
                </li>
                <li>
                  3. Put the robot in remote/external mode so ROS control is accepted (UR: External Control, DOBOT: Remote TCP).
                </li>
                <li>
                  4. Confirm `/api/robot/state` reports `connected: true` before sending commands.
                </li>
                <li>
                  5. Use small jog increments first, then execute full target motions.
                </li>
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
