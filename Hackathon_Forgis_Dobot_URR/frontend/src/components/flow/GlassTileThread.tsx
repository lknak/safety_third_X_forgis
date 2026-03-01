import { cn } from "@/lib/utils";
import type { OrchestratorTile } from "@/types";

interface GlassTileThreadProps {
  tiles: OrchestratorTile[];
  activeNodeName: string | null;
  liveText: string;
}

function edgeClass(tile: OrchestratorTile, isActive: boolean): string {
  if (tile.status === "SUCCESS") return "border-[var(--status-healthy)]";
  if (tile.status === "FAILURE" || tile.status === "TIMEOUT") return "border-[var(--status-critical)]";
  if (isActive) return "border-[var(--status-warning)] animate-pulse";
  return "border-border/50";
}

function statusLabel(tile: OrchestratorTile): string {
  if (tile.status === "RUNNING") return "Running";
  if (tile.status === "PENDING") return "Pending";
  if (tile.status === "SUCCESS") return "Success";
  if (tile.status === "FAILURE") return "Failure";
  return "Timeout";
}

export function GlassTileThread({ tiles, activeNodeName, liveText }: GlassTileThreadProps) {
  if (tiles.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground forgis-text-label font-forgis-body">
        Waiting for orchestrator telemetry...
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-x-auto overflow-y-hidden p-4">
      <div className="flex h-full gap-3 min-w-max">
        {tiles.map((tile) => {
          const isActive = activeNodeName === tile.name;
          const isLivePrimary = isActive && tile.type === "GEMINI_LIVE_COMMENTARY_NODE";

          return (
            <section
              key={tile.name}
              className={cn(
                "rounded-2xl border bg-card/70 backdrop-blur-md transition-all duration-300 flex flex-col",
                edgeClass(tile, isActive),
                isLivePrimary ? "w-[460px] p-4" : "w-[220px] p-3",
              )}
            >
              <header className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-forgis-digit">
                    {tile.type}
                  </p>
                  <h3 className="forgis-text-reading font-forgis-digit mt-1 leading-tight break-words">
                    {tile.name}
                  </h3>
                </div>
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground font-forgis-digit">
                  {statusLabel(tile)}
                </span>
              </header>

              <div className="mt-3 space-y-2 text-[11px] font-forgis-body text-muted-foreground">
                {tile.startTime && (
                  <div>Start: {new Date(tile.startTime * 1000).toLocaleTimeString()}</div>
                )}
                {tile.endTime && (
                  <div>End: {new Date(tile.endTime * 1000).toLocaleTimeString()}</div>
                )}
              </div>

              {isLivePrimary && (
                <div className="mt-4 flex-1 rounded-xl border border-border/40 bg-black/70 text-white p-3">
                  <p className="text-[10px] uppercase tracking-widest text-[var(--status-warning)] font-forgis-digit mb-2">
                    Gemini Live
                  </p>
                  <p className="forgis-text-label font-forgis-body leading-relaxed">
                    {liveText || "Listening and narrating robot motion..."}
                  </p>
                </div>
              )}

              {!isLivePrimary && tile.artifacts && (
                <div className="mt-3 rounded-lg bg-muted/40 p-2 text-[10px] font-mono text-foreground/80 overflow-hidden">
                  {JSON.stringify(tile.artifacts).slice(0, 180)}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
