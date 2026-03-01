import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ClarificationModalProps {
  open: boolean;
  reason: string;
  timeoutSeconds: number;
  onAction: (action: "retry" | "replan" | "modify_goal" | "safe_stop", note?: string) => void;
}

export function ClarificationModal({
  open,
  reason,
  timeoutSeconds,
  onAction,
}: ClarificationModalProps) {
  const [note, setNote] = useState("");

  return (
    <Dialog open={open}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>Operator Clarification Required</DialogTitle>
          <DialogDescription>
            The orchestrator paused due to an infeasible or failed node.
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm font-forgis-body text-foreground">
          {reason}
        </div>

        <div className="text-xs text-muted-foreground font-forgis-body">
          Auto safe-stop in {timeoutSeconds}s if no decision is submitted.
        </div>

        <Input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Optional note for replanning..."
        />

        <DialogFooter className="flex gap-2">
          <Button variant="outline" onClick={() => onAction("retry", note)}>
            Retry
          </Button>
          <Button variant="outline" onClick={() => onAction("replan", note)}>
            Replan
          </Button>
          <Button variant="outline" onClick={() => onAction("modify_goal", note)}>
            Modify Goal
          </Button>
          <Button variant="destructive" onClick={() => onAction("safe_stop", note)}>
            Safe Stop
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
