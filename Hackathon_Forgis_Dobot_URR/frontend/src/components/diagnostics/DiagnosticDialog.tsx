import { useState, useEffect } from "react";
import {
    AlertCircle,
    CheckCircle2,
    RefreshCcw,
    ShieldCheck,
    Power
} from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getOverallHealth, retryInitialisation, type OverallHealth } from "@/api/healthApi";
import { cn } from "@/lib/utils";

interface DiagnosticDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function DiagnosticDialog({ open, onOpenChange }: DiagnosticDialogProps) {
    const [health, setHealth] = useState<OverallHealth | null>(null);
    const [loading, setLoading] = useState(false);
    const [retrying, setRetrying] = useState<string | null>(null);

    const fetchHealth = async () => {
        setLoading(true);
        try {
            const data = await getOverallHealth();
            setHealth(data);
        } catch (error) {
            console.error("Failed to fetch health:", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (open) {
            fetchHealth();
        }
    }, [open]);

    const handleRetry = async (deviceName?: string) => {
        setRetrying(deviceName || "all");
        try {
            await retryInitialisation(deviceName);
            await fetchHealth();
        } catch (error) {
            console.error("Retry failed:", error);
        } finally {
            setRetrying(null);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl bg-[var(--panel)] border-border/40">
                <DialogHeader>
                    <div className="flex items-center gap-3 mb-2">
                        <div className="p-2 rounded-lg bg-primary/10 text-primary">
                            <ShieldCheck size={24} />
                        </div>
                        <div>
                            <DialogTitle className="forgis-text-reading font-forgis-digit uppercase tracking-wider">
                                System Diagnostics
                            </DialogTitle>
                            <DialogDescription className="forgis-text-detail font-forgis-body">
                                Real-time hardware status and reconnect troubleshooting.
                            </DialogDescription>
                        </div>
                    </div>
                </DialogHeader>

                <div className="py-4 space-y-4 max-h-[60vh] overflow-y-auto custom-scrollbar pr-2">
                    {loading && !health ? (
                        <div className="flex flex-col items-center justify-center py-12 gap-3 opacity-50">
                            <RefreshCcw className="animate-spin" size={32} />
                            <span className="forgis-text-label font-forgis-body">Scanning Cell Infrastructure...</span>
                        </div>
                    ) : (
                        Object.entries(health?.devices || {}).map(([name, data]) => (
                            <div
                                key={name}
                                className={cn(
                                    "p-4 rounded-xl border transition-all duration-300",
                                    data.status === "connected" ? "bg-card/50 border-border/40" : "bg-critical/5 border-critical/30"
                                )}
                            >
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <h4 className="forgis-text-label font-forgis-digit uppercase tracking-tight font-medium">
                                                {name.replace("_", " ")}
                                            </h4>
                                            <Badge
                                                variant={data.status === "connected" ? "default" : "destructive"}
                                                className={cn(
                                                    "text-[9px] uppercase tracking-tighter px-1.5 h-4 flex items-center",
                                                    data.status === "connected" ? "bg-[var(--status-healthy)]/20 text-[var(--status-healthy)] hover:bg-[var(--status-healthy)]/20" : ""
                                                )}
                                            >
                                                {data.status === "connected" ? <CheckCircle2 size={8} className="mr-1" /> : <AlertCircle size={8} className="mr-1" />}
                                                {data.status}
                                            </Badge>
                                        </div>

                                        {data.status !== "connected" ? (
                                            <div className="space-y-3 animate-in fade-in slide-in-from-top-1 duration-500">
                                                <p className="text-[11px] text-muted-foreground font-forgis-body italic">
                                                    "{data.error}"
                                                </p>
                                                <div className="p-3 rounded-lg bg-primary/5 border border-primary/10">
                                                    <span className="text-[10px] font-forgis-digit uppercase text-primary block mb-1">Operator Guidance</span>
                                                    <p className="text-[11px] text-foreground/90 font-forgis-body leading-relaxed">
                                                        {data.suggestion || "Check power, network connectivity, and driver initialization for this device."}
                                                    </p>
                                                </div>
                                            </div>
                                        ) : (
                                            <p className="text-[11px] text-muted-foreground font-forgis-body">
                                                Device is fully operational and reporting telemetry.
                                            </p>
                                        )}
                                    </div>

                                    <Button
                                        size="sm"
                                        variant="outline"
                                        className="h-8 forgis-text-label font-forgis-digit uppercase text-[10px] gap-2 border-border/60 hover:bg-muted"
                                        onClick={() => handleRetry(name)}
                                        disabled={retrying !== null}
                                    >
                                        {retrying === name ? <RefreshCcw size={12} className="animate-spin" /> : <Power size={12} />}
                                        Reconnect
                                    </Button>
                                </div>
                            </div>
                        ))
                    )}
                </div>

                <DialogFooter className="flex items-center justify-between border-t border-border/40 pt-4 mt-2">
                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground font-forgis-body">
                        <span className="w-1.5 h-1.5 rounded-full bg-[var(--status-healthy)] animate-pulse" />
                        Hardware diagnostics active
                    </div>
                    <div className="flex items-center gap-2">
                        <Button variant="ghost" onClick={() => onOpenChange(false)} className="h-9 px-4 forgis-text-label font-forgis-body">
                            Close
                        </Button>
                        <Button
                            onClick={() => handleRetry()}
                            disabled={retrying !== null}
                            className="h-9 px-6 forgis-text-label font-forgis-digit uppercase gap-2 bg-primary hover:bg-primary/90"
                        >
                            {retrying === "all" ? <RefreshCcw size={14} className="animate-spin" /> : <RefreshCcw size={14} />}
                            Refresh All
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
