import { cn } from "@/lib/utils";
import { Eye, Cpu, Move, Mic, CheckCircle2, Zap, Bot, Wrench, Loader2 } from "lucide-react";
import type { OrchestratorTile, OrchestratorNodeType } from "@/types";

interface GlassTileThreadProps {
  tiles: OrchestratorTile[];
  activeNodeName: string | null;
  liveText: string;
}

// ── Node type → friendly label + icon ────────────────────────

const NODE_META: Record<OrchestratorNodeType, { label: string; Icon: typeof Eye }> = {
  INPUT_NODE: { label: "Cell Snapshot", Icon: Eye },
  ORCHESTRATOR_PLANNER_NODE: { label: "Task Planner", Icon: Cpu },
  ER_1_5_ANALYSIS_NODE: { label: "Scene Analysis", Icon: Eye },
  DEPTH_ESTIMATION_NODE: { label: "Depth Calc", Icon: Zap },
  ROBOT_EXECUTION_NODE: { label: "Robot Motion", Icon: Move },
  GEMINI_LIVE_COMMENTARY_NODE: { label: "Live Narration", Icon: Mic },
  VERIFICATION_NODE: { label: "Verify", Icon: CheckCircle2 },
  SUMMARY_NODE: { label: "Summary", Icon: Bot },
};

function edgeClass(tile: OrchestratorTile, isActive: boolean): string {
  if (tile.status === "SUCCESS") return "border-[var(--status-healthy)] shadow-[0_0_12px_rgba(34,197,94,0.15)]";
  if (tile.status === "FAILURE" || tile.status === "TIMEOUT") return "border-[var(--status-critical)] shadow-[0_0_12px_rgba(239,68,68,0.15)]";
  if (isActive) return "border-[var(--status-warning)] animate-pulse shadow-[0_0_16px_rgba(245,158,11,0.2)]";
  if (tile.status === "PENDING") return "border-border/30 opacity-60";
  return "border-border/50";
}

function statusDot(tile: OrchestratorTile, isActive: boolean): string {
  if (tile.status === "SUCCESS") return "bg-[var(--status-healthy)]";
  if (tile.status === "FAILURE" || tile.status === "TIMEOUT") return "bg-[var(--status-critical)]";
  if (isActive || tile.status === "RUNNING") return "bg-[var(--status-warning)] animate-pulse";
  return "bg-muted-foreground/30";
}

function durationLabel(tile: OrchestratorTile): string | null {
  if (!tile.startTime || !tile.endTime) return null;
  const ms = Math.round((tile.endTime - tile.startTime) * 1000);
  return ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

const EMPTY_DOODLE = `
     ╭──────────────────╮
     │  ┌─┐   Waiting   │
     │  │ │   for nodes  │
     │  └─┘   ...        │
     ╰──────────────────╯
`.trimStart();

export function GlassTileThread({ tiles, activeNodeName, liveText }: GlassTileThreadProps) {
  if (tiles.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-3">
        <pre className="text-[10px] leading-tight font-mono opacity-50">
          {EMPTY_DOODLE}
        </pre>
        <p className="forgis-text-label font-forgis-body italic">
          Send a task to see the execution thread
        </p>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-x-auto overflow-y-hidden p-4">
      <div className="flex h-full gap-3 min-w-max items-stretch">
        {tiles.map((tile, idx) => {
          const isActive = activeNodeName === tile.name;
          const isLivePrimary = isActive && tile.type === "GEMINI_LIVE_COMMENTARY_NODE";
          const meta = NODE_META[tile.type] || { label: tile.type, Icon: Wrench };
          const duration = durationLabel(tile);

          return (
            <section
              key={tile.name}
              className={cn(
                "rounded-2xl border bg-card/70 backdrop-blur-md transition-all duration-300 flex flex-col relative",
                edgeClass(tile, isActive),
                isLivePrimary ? "w-[460px] p-4" : "w-[220px] p-3",
              )}
            >
              {/* Step number badge */}
              <div className="absolute -top-2 -left-2 w-5 h-5 rounded-full bg-card border border-border flex items-center justify-center">
                <span className="text-[8px] font-forgis-digit text-muted-foreground">
                  {idx + 1}
                </span>
              </div>

              <header className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <meta.Icon size={14} className={cn(
                    tile.status === "SUCCESS" ? "text-[var(--status-healthy)]" :
                    tile.status === "FAILURE" || tile.status === "TIMEOUT" ? "text-[var(--status-critical)]" :
                    isActive ? "text-[var(--status-warning)]" :
                    "text-muted-foreground"
                  )} />
                  <div>
                    <h3 className="text-[11px] font-forgis-digit uppercase tracking-wider leading-tight">
                      {meta.label}
                    </h3>
                    <p className="text-[9px] text-muted-foreground font-mono mt-0.5 break-all">
                      {tile.name}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  {isActive && <Loader2 size={10} className="animate-spin text-[var(--status-warning)]" />}
                  <span className={cn("w-2 h-2 rounded-full", statusDot(tile, isActive))} />
                </div>
              </header>

              {/* Timing */}
              <div className="mt-2 flex items-center gap-2 text-[9px] font-mono text-muted-foreground">
                {tile.startTime && (
                  <span>{new Date(tile.startTime * 1000).toLocaleTimeString()}</span>
                )}
                {duration && (
                  <span className="px-1 py-0.5 rounded bg-muted/40 text-foreground/70">
                    {duration}
                  </span>
                )}
              </div>

              {/* Live commentary panel */}
              {isLivePrimary && (
                <div className="mt-3 flex-1 rounded-xl border border-border/40 bg-black/80 text-white p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                    <p className="text-[9px] uppercase tracking-widest text-[var(--status-warning)] font-forgis-digit">
                      Live
                    </p>
                  </div>
                  <p className="text-xs font-forgis-body leading-relaxed">
                    {liveText || "Narrating robot motion..."}
                  </p>
                </div>
              )}

              {/* Artifacts preview */}
              {!isLivePrimary && tile.artifacts && Object.keys(tile.artifacts).length > 0 && (
                <div className="mt-2 flex-1 rounded-lg bg-muted/30 p-2 text-[9px] font-mono text-foreground/70 overflow-hidden">
                  {JSON.stringify(tile.artifacts, null, 1).slice(0, 200)}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
