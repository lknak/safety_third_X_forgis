import {
    Activity,
    AlertTriangle,
    Box,
    ShieldCheck,
    BrainCircuit,
    Eye
} from "lucide-react";
import { type CellStateSummary as CellStateSummaryType } from "@/api/cellApi";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface CellStateSummaryProps {
    summary: CellStateSummaryType | null;
    loading: boolean;
}

export function CellStateSummary({ summary, loading }: CellStateSummaryProps) {
    if (!summary && !loading) return null;

    const getSafetyColor = (status: string) => {
        switch (status) {
            case "Clear": return "text-[var(--status-healthy)]";
            case "Warning": return "text-[var(--orange)]";
            case "Hazard": return "text-[var(--status-critical)]";
            default: return "text-muted-foreground";
        }
    };

    return (
        <div className="bg-card/50 border border-border/40 rounded-xl p-4 space-y-4 backdrop-blur-sm shadow-sm relative overflow-hidden group">
            <div className="absolute top-0 left-0 w-1 h-full bg-primary/20 group-hover:bg-primary/40 transition-colors" />

            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <div className="p-1.5 rounded-lg bg-primary/10 text-primary">
                        <BrainCircuit size={18} />
                    </div>
                    <h3 className="forgis-text-reading font-forgis-digit uppercase tracking-wider text-[var(--gunmetal-50)]">
                        Cell Intelligence
                    </h3>
                </div>
                {loading && (
                    <div className="flex items-center gap-1.5 text-[10px] text-primary animate-pulse font-forgis-body">
                        <Eye size={12} />
                        Inference Active
                    </div>
                )}
            </div>

            <div className="grid grid-cols-2 gap-4">
                {/* Current State */}
                <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-tighter text-muted-foreground font-forgis-digit">
                        <Activity size={10} />
                        Operating Mode
                    </div>
                    <p className="text-sm font-forgis-body text-foreground leading-tight">
                        {summary?.state || "Initializing..."}
                    </p>
                </div>

                {/* Safety Status */}
                <div className="space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-tighter text-muted-foreground font-forgis-digit">
                        <ShieldCheck size={10} />
                        Safety Protocol
                    </div>
                    <div className={cn("text-sm font-forgis-body font-bold flex items-center gap-1.5", getSafetyColor(summary?.safety_status || ""))}>
                        {summary?.safety_status || "Checking..."}
                        {summary?.safety_status === "Clear" && <span className="w-1.5 h-1.5 rounded-full bg-[var(--status-healthy)]" />}
                    </div>
                </div>
            </div>

            {/* Identified Objects */}
            <div className="space-y-2">
                <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-tighter text-muted-foreground font-forgis-digit">
                    <Box size={10} />
                    Active Workspace Assets
                </div>
                <div className="flex flex-wrap gap-1.5">
                    {summary?.active_objects.map((obj, i) => (
                        <Badge
                            key={i}
                            variant="secondary"
                            className="text-[9px] font-forgis-body py-0 px-2 bg-muted/50 text-foreground/80 border-none"
                        >
                            {obj}
                        </Badge>
                    )) || <span className="text-[10px] text-muted-foreground italic">Detecting...</span>}
                </div>
            </div>

            {/* Anomalies */}
            {summary?.anomalies && summary.anomalies.length > 0 && (
                <div className="p-3 rounded-lg bg-critical/5 border border-critical/20 space-y-1.5">
                    <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-tighter text-[var(--status-critical)] font-forgis-digit font-bold">
                        <AlertTriangle size={10} />
                        Anomalies Detected
                    </div>
                    <ul className="space-y-1">
                        {summary.anomalies.map((anomaly, i) => (
                            <li key={i} className="text-[11px] text-foreground/90 font-forgis-body list-disc ml-3">
                                {anomaly}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {!summary && !loading && (
                <div className="py-2 text-center text-[10px] text-muted-foreground font-forgis-body italic">
                    Awaiting vision telemetry for state inference...
                </div>
            )}
        </div>
    );
}
