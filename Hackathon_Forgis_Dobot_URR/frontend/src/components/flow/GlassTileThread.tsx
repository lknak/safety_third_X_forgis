import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { OrchestratorTimelineTile } from "@/types";

interface GlassTileThreadProps {
  orderedTiles: OrchestratorTimelineTile[];
  heroTile: OrchestratorTimelineTile | null;
  activeNodeName: string | null;
  liveText: string;
  onInspectTile: (nodeName: string) => void;
}

const AUTO_FOLLOW_PAUSE_MS = 2500;

function statusLabel(tile: OrchestratorTimelineTile): string {
  if (tile.status === "RUNNING") return "Running";
  if (tile.status === "PENDING") return "Pending";
  if (tile.status === "SUCCESS") return "Success";
  if (tile.status === "FAILURE") return "Failure";
  return "Timeout";
}

function statusClass(tile: OrchestratorTimelineTile): string {
  if (tile.status === "SUCCESS") return "glass-status-success";
  if (tile.status === "FAILURE" || tile.status === "TIMEOUT") return "glass-status-failure";
  if (tile.status === "RUNNING") return "glass-status-running";
  return "border-border/40 text-muted-foreground";
}

function artifactSummary(artifacts?: Record<string, unknown>): string[] {
  if (!artifacts || Object.keys(artifacts).length === 0) {
    return [];
  }

  return Object.entries(artifacts)
    .slice(0, 4)
    .map(([key, value]) => {
      if (value == null) return `${key}: none`;
      if (typeof value === "string") {
        const compact = value.replace(/\s+/g, " ").trim();
        return `${key}: ${compact.length > 22 ? `${compact.slice(0, 22)}...` : compact}`;
      }
      if (typeof value === "number" || typeof value === "boolean") {
        return `${key}: ${String(value)}`;
      }
      if (Array.isArray(value)) {
        return `${key}: ${value.length} items`;
      }
      return `${key}: object`;
    });
}

function formatTime(epoch?: number): string {
  if (!epoch) return "n/a";
  return new Date(epoch * 1000).toLocaleTimeString();
}

function formatDuration(durationMs: number | null): string {
  if (durationMs == null) return "n/a";
  return `${(durationMs / 1000).toFixed(1)} s`;
}

export function GlassTileThread({
  orderedTiles,
  heroTile,
  activeNodeName,
  liveText,
  onInspectTile,
}: GlassTileThreadProps) {
  const stripRef = useRef<HTMLDivElement | null>(null);
  const frameRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [autoFollowPausedUntil, setAutoFollowPausedUntil] = useState(0);

  const focusNodeName = activeNodeName ?? orderedTiles.find((tile) => tile.isActive)?.name ?? null;
  const heroArtifactSummary = useMemo(
    () => artifactSummary(heroTile?.artifacts),
    [heroTile?.artifacts],
  );

  const pauseAutoFollow = () => {
    setAutoFollowPausedUntil(Date.now() + AUTO_FOLLOW_PAUSE_MS);
  };

  useEffect(() => {
    if (!focusNodeName) return;
    if (Date.now() < autoFollowPausedUntil) return;
    const target = frameRefs.current[focusNodeName];
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [autoFollowPausedUntil, focusNodeName, orderedTiles]);

  if (orderedTiles.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground forgis-text-label font-forgis-body">
        Waiting for orchestrator telemetry...
      </div>
    );
  }

  const showLiveSection = !!heroTile && (heroTile.type === "GEMINI_LIVE_COMMENTARY_NODE" || !!liveText);

  return (
    <div className="h-full w-full p-4 md:p-5">
      <div className="h-full flex flex-col gap-4 md:gap-5">
        <section
          key={heroTile?.name ?? "hero-empty"}
          className="glass-surface glass-hero animate-hero-switch min-h-[44vh] md:min-h-[48vh] p-4 md:p-6 flex flex-col"
        >
          {heroTile ? (
            <>
              <header className="flex items-start justify-between gap-4">
                <div className="space-y-2">
                  <span className="inline-flex items-center rounded-full border border-white/35 bg-white/20 px-2.5 py-1 text-[10px] uppercase tracking-widest text-foreground/85 font-forgis-digit">
                    {heroTile.type}
                  </span>
                  <h2 className="forgis-text-title md:text-[20px] font-forgis-digit leading-tight break-words">
                    {heroTile.name}
                  </h2>
                </div>
                <span className={cn("rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-widest font-forgis-digit", statusClass(heroTile))}>
                  {statusLabel(heroTile)}
                </span>
              </header>

              <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2.5 text-[11px]">
                <div className="rounded-xl bg-white/25 border border-white/30 px-3 py-2">
                  <div className="text-muted-foreground uppercase tracking-wider text-[9px] font-forgis-digit">Start</div>
                  <div className="font-forgis-body mt-1">{formatTime(heroTile.startTime)}</div>
                </div>
                <div className="rounded-xl bg-white/25 border border-white/30 px-3 py-2">
                  <div className="text-muted-foreground uppercase tracking-wider text-[9px] font-forgis-digit">End</div>
                  <div className="font-forgis-body mt-1">{formatTime(heroTile.endTime)}</div>
                </div>
                <div className="rounded-xl bg-white/25 border border-white/30 px-3 py-2">
                  <div className="text-muted-foreground uppercase tracking-wider text-[9px] font-forgis-digit">Duration</div>
                  <div className="font-forgis-body mt-1">{formatDuration(heroTile.durationMs)}</div>
                </div>
                <div className="rounded-xl bg-white/25 border border-white/30 px-3 py-2">
                  <div className="text-muted-foreground uppercase tracking-wider text-[9px] font-forgis-digit">Artifacts</div>
                  <div className="font-forgis-body mt-1">{heroTile.hasArtifacts ? "Available" : "None"}</div>
                </div>
              </div>

              {heroArtifactSummary.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {heroArtifactSummary.map((item) => (
                    <span
                      key={item}
                      className="inline-flex items-center rounded-full border border-white/35 bg-white/20 px-2.5 py-1 text-[10px] font-forgis-digit text-foreground/80"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              )}

              {showLiveSection && (
                <div className="mt-4 rounded-2xl border border-white/30 bg-black/55 text-white p-4">
                  <p className="text-[10px] uppercase tracking-widest text-[var(--status-warning)] font-forgis-digit mb-2">
                    Gemini Live Commentary
                  </p>
                  <p className="forgis-text-label font-forgis-body leading-relaxed">
                    {liveText || "Listening and narrating robot motion..."}
                  </p>
                </div>
              )}
            </>
          ) : (
            <div className="h-full flex items-center justify-center text-muted-foreground forgis-text-label font-forgis-body">
              Waiting for orchestrator node focus...
            </div>
          )}
        </section>

        <section className="glass-surface rounded-2xl p-3 md:p-4 flex-1 min-h-[190px] relative overflow-hidden">
          <div className="flex items-center justify-between px-1">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-forgis-digit">Past</span>
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-forgis-digit">Upcoming</span>
          </div>

          <div className="relative mt-2 h-[calc(100%-24px)]">
            <div className="glass-divider absolute top-0 bottom-0 left-1/2 -translate-x-1/2 z-10" />

            <div
              ref={stripRef}
              className="h-full overflow-x-auto overflow-y-hidden scrollbar-hidden"
              onMouseDown={pauseAutoFollow}
              onWheel={pauseAutoFollow}
              onTouchStart={pauseAutoFollow}
            >
              <div className="inline-flex h-full items-center gap-3 px-[48vw] min-w-max">
                {orderedTiles.map((tile) => (
                  <button
                    key={tile.name}
                    ref={(el) => {
                      frameRefs.current[tile.name] = el;
                    }}
                    type="button"
                    onClick={() => onInspectTile(tile.name)}
                    className={cn(
                      "glass-frame text-left shrink-0 w-[190px] md:w-[210px] px-3 py-3 transition-all duration-200",
                      tile.phase === "past" && "opacity-85 saturate-75",
                      tile.phase === "future" && "opacity-70",
                      tile.isActive && "glass-frame-active animate-glass-frame-pulse",
                      statusClass(tile),
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-[9px] uppercase tracking-widest text-muted-foreground font-forgis-digit truncate">
                        {tile.type}
                      </p>
                      <span className="text-[9px] uppercase tracking-widest font-forgis-digit text-foreground/80">
                        {statusLabel(tile)}
                      </span>
                    </div>
                    <h3 className="mt-1.5 forgis-text-label font-forgis-digit leading-tight line-clamp-2 min-h-[32px]">
                      {tile.name}
                    </h3>
                    <div className="mt-2 text-[10px] text-muted-foreground font-forgis-body">
                      {tile.durationMs != null ? `${(tile.durationMs / 1000).toFixed(1)} s` : "Awaiting runtime"}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
