import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
} from "@/components/ui/dialog";
import { DeviceControlPanel } from "./DeviceControlPanel";
import type { Device } from "@/types";
import { Bot, Info } from "lucide-react";

interface DeviceDetailDialogProps {
    device: Device | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function DeviceDetailDialog({ device, open, onOpenChange }: DeviceDetailDialogProps) {
    if (!device) return null;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl bg-[var(--panel)] border-border/40 p-0 overflow-hidden">
                <div className="flex flex-col h-[80vh]">
                    <DialogHeader className="p-6 border-b border-border/40 bg-muted/20">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-primary/10 text-primary">
                                <Bot size={24} />
                            </div>
                            <div className="min-w-0 flex-1">
                                <DialogTitle className="forgis-text-reading font-forgis-digit uppercase tracking-wider">
                                    {device.name}
                                </DialogTitle>
                                <DialogDescription className="forgis-text-detail font-forgis-body truncate">
                                    {device.vendor} · {device.ip} · {device.type}
                                </DialogDescription>
                            </div>
                        </div>
                    </DialogHeader>

                    <div className="flex-1 overflow-y-auto custom-scrollbar">
                        <DeviceControlPanel device={device} className="border-none" />
                    </div>

                    <div className="p-4 border-t border-border/40 bg-muted/10 flex items-center justify-between text-[10px] text-muted-foreground font-forgis-body">
                        <div className="flex items-center gap-2">
                            <Info size={12} className="text-primary" />
                            <span>Direct hardware control enabled. Use with caution.</span>
                        </div>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
