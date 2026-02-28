import { useState, useMemo } from "react";
import {
    Activity,
    CheckCircle2,
    Timer,
    AlertCircle,
    Terminal,
    Scan,
    Maximize2
} from "lucide-react";
import type { Flow, NodeExecState } from "@/types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CameraFeed } from "@/components/camera/CameraFeed";
import { cn } from "@/lib/utils";

interface FlowStatePanelProps {
    flow: Flow | null;
    nodeStates: Record<string, NodeExecState>;
    cameraFrame: string | null;
    lastLabel: string | null;
    className?: string;
}

export function FlowStatePanel({
    flow,
    nodeStates,
    cameraFrame,
    lastLabel,
    className
}: FlowStatePanelProps) {
    const [manualExpandedNodeId, setManualExpandedNodeId] = useState<string | null>(null);

    // Filter actual state nodes
    const stateNodes = useMemo(() => {
        return flow?.nodes.filter(n => n.type === "state") || [];
    }, [flow]);

    // Find currently running node
    const activeNodeId = useMemo(() => {
        return Object.entries(nodeStates).find(([_, state]) => state.status === "running")?.[0] || null;
    }, [nodeStates]);

    // If no node is manually expanded, auto-expand the active one
    const displayNodeId = manualExpandedNodeId || activeNodeId;

    return (
        <div className={cn("flex flex-col h-full bg-[var(--panel)]", className)}>
            {/* State Tiles Grid (Phase 6: Small icon tiles with smooth transitions) */}
            <div className="p-4 grid grid-cols-6 gap-3 border-b border-border/40 bg-card/30">
                {stateNodes.map((node) => {
                    const state = nodeStates[node.id];
                    const status = state?.status || "idle";
                    const isActive = activeNodeId === node.id;
                    const isSelected = displayNodeId === node.id;

                    return (
                        <button
                            key={node.id}
                            onClick={() => setManualExpandedNodeId(node.id === manualExpandedNodeId ? null : node.id)}
                            className={cn(
                                "group relative flex flex-col items-center justify-center aspect-square rounded-xl border transition-all duration-300",
                                "hover:scale-105 active:scale-95",
                                status === "running" && "border-primary bg-primary/5 shadow-[0_0_15px_-3px_rgba(var(--primary-rgb),0.3)] animate-pulse",
                                status === "success" && "border-[var(--status-healthy)] bg-[var(--status-healthy)]/5",
                                status === "failure" && "border-[var(--status-critical)] bg-[var(--status-critical)]/5",
                                status === "idle" && "border-border/60 bg-white/5",
                                isSelected && "ring-2 ring-primary ring-offset-2 ring-offset-background"
                            )}
                        >
                            {/* Status Icon */}
                            <div className={cn(
                                "mb-1 group-hover:scale-110 transition-transform",
                                status === "success" ? "text-[var(--status-healthy)]" :
                                    status === "running" ? "text-primary" : "text-muted-foreground"
                            )}>
                                {status === "success" ? <CheckCircle2 size={16} /> :
                                    status === "running" ? <Activity size={16} /> :
                                        status === "failure" ? <AlertCircle size={16} className="text-critical" /> :
                                            <div className="w-4 h-4 rounded-full border-2 border-current opacity-20" />}
                            </div>

                            <span className="text-[10px] font-forgis-digit uppercase tracking-tighter truncate w-full px-1 text-center">
                                {node.label}
                            </span>

                            {/* Active Indicator */}
                            {isActive && (
                                <div className="absolute -top-1 -right-1 flex h-3 w-3">
                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                                    <span className="relative inline-flex rounded-full h-3 w-3 bg-primary"></span>
                                </div>
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Expanded State Detail & Cell Awareness (Phase 5 & 6) */}
            <div className="flex-1 min-h-0 p-4">
                {displayNodeId ? (
                    <div className="h-full flex flex-col gap-4 animate-in fade-in slide-in-from-bottom-2 duration-500">
                        {/* Header / Meta */}
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-primary/10 text-primary">
                                    <Activity size={20} />
                                </div>
                                <div>
                                    <h3 className="forgis-text-reading font-forgis-digit uppercase tracking-wide">
                                        {stateNodes.find(n => n.id === displayNodeId)?.label}
                                    </h3>
                                    <div className="flex items-center gap-4 text-[11px] text-muted-foreground font-forgis-body">
                                        <span className="flex items-center gap-1">
                                            <Timer size={12} /> {nodeStates[displayNodeId]?.durationMs ? `${(nodeStates[displayNodeId].durationMs! / 1000).toFixed(1)} s` : "Waiting..."}
                                        </span>
                                        <span className="flex items-center gap-1 capitalize">
                                            <span className={cn(
                                                "w-1.5 h-1.5 rounded-full",
                                                nodeStates[displayNodeId]?.status === "running" ? "bg-primary" :
                                                    nodeStates[displayNodeId]?.status === "success" ? "bg-[var(--status-healthy)]" : "bg-muted"
                                            )} />
                                            {nodeStates[displayNodeId]?.status || "Ready"}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            <button className="p-1 px-3 rounded-full border border-border text-[10px] font-forgis-body hover:bg-muted transition-colors flex items-center gap-1.5">
                                <Maximize2 size={12} /> Fullscreen
                            </button>
                        </div>

                        {/* Content Grid */}
                        <div className="flex-1 grid grid-cols-5 gap-4 min-h-0">
                            {/* Vision Feed (Expanded Tile Content) */}
                            <div className="col-span-3 rounded-2xl overflow-hidden bg-black border border-border/40 relative group">
                                {cameraFrame ? (
                                    <CameraFeed
                                        frameUrl={cameraFrame}
                                        streaming
                                        lastLabel={lastLabel ? { label: lastLabel, version: 1 } : null}
                                        bboxOverlay={null}
                                    />
                                ) : (
                                    <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground gap-3">
                                        <Scan size={48} className="opacity-20 animate-pulse" />
                                        <span className="forgis-text-label font-forgis-body">Awaiting Vision Signal...</span>
                                    </div>
                                )}
                                <div className="absolute top-4 left-4 flex items-center gap-2 px-3 py-1 rounded-full bg-black/50 backdrop-blur-md border border-white/10 text-[10px] font-forgis-digit text-white uppercase tracking-widest">
                                    <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                                    Live Feed: {stateNodes.find(n => n.id === displayNodeId)?.label}
                                </div>
                            </div>

                            {/* Data / Reasoning / Cell Awareness Panel */}
                            <div className="col-span-2 flex flex-col gap-4 min-h-0">
                                {/* Structured State Summary */}
                                <div className="bg-card/50 border border-border/40 rounded-xl p-4 space-y-3">
                                    <h3 className="forgis-text-reading font-forgis-digit uppercase tracking-wider text-[var(--gunmetal-50)]">
                                        Vision Summary
                                    </h3>
                                    <div className="grid grid-cols-2 gap-4 text-[11px] font-forgis-body">
                                        <div>
                                            <div className="text-[9px] uppercase tracking-tighter text-muted-foreground font-forgis-digit mb-1">
                                                Stream
                                            </div>
                                            <div className="text-foreground">
                                                {cameraFrame ? "Active" : "Offline"}
                                            </div>
                                        </div>
                                        <div>
                                            <div className="text-[9px] uppercase tracking-tighter text-muted-foreground font-forgis-digit mb-1">
                                                Last Label
                                            </div>
                                            <div className="text-foreground">
                                                {lastLabel || "None"}
                                            </div>
                                        </div>
                                    </div>
                                    <p className="text-[10px] text-muted-foreground font-forgis-body">
                                        AI diagnostics are disabled. Use chat for AI-assisted analysis.
                                    </p>
                                </div>

                                {/* Reasoning Trace (Phase 6: Detailed reasoning) */}
                                <div className="flex-1 rounded-2xl bg-card border border-border/40 p-4 flex flex-col overflow-hidden">
                                    <div className="flex items-center gap-2 mb-3 text-xs font-forgis-digit uppercase tracking-wider text-muted-foreground">
                                        <Terminal size={14} /> Reasoning Trace
                                    </div>
                                    <ScrollArea className="flex-1 font-mono text-[11px] text-foreground/80 leading-relaxed pr-2">
                                        <p className="text-primary italic opacity-70">Initializing execution timeline...</p>
                                        <p>[0ms] Analyzing scene geometry from primary sensor.</p>
                                        <p>[120ms] Detected candidate workspace features.</p>
                                        <p>[450ms] Mapping goal trajectory against kinematics constraints.</p>
                                        <p>[890ms] Optimized path generated. Submitting to RobotExecutor.</p>
                                        {nodeStates[displayNodeId]?.status === "running" && (
                                            <p className="animate-pulse">_</p>
                                        )}
                                    </ScrollArea>
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="h-full flex flex-col items-center justify-center text-center gap-4 opacity-50">
                        <div className="w-16 h-16 rounded-full border-2 border-dashed border-muted-foreground flex items-center justify-center">
                            <Activity size={32} />
                        </div>
                        <div>
                            <p className="forgis-text-reading font-forgis-digit uppercase">Ochestration Idle</p>
                            <p className="forgis-text-label font-forgis-body max-w-xs mx-auto">
                                Generate a flow to begin monitoring state transitions and model reasoning.
                            </p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
