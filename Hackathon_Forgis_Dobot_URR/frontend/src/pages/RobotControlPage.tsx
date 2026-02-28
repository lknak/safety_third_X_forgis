import { useState, useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { TopBar } from "@/components/layout/Topbar";
import { CoderSidebar } from "@/components/chat/CoderSidebar";
import { FlowCanvas } from "@/components/flow/FlowCanvas";
import { FlowStatePanel } from "@/components/flow/FlowStatePanel";
import { DevicesSidebar } from "@/components/devices/DevicesSidebar";
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbSeparator,
  BreadcrumbPage,
} from "@/components/ui/breadcrumb";
import { useFlowGeneration } from "@/hooks/useFlowGeneration";
import { useCamera } from "@/hooks/useCamera";
import { useFlowExecution } from "@/hooks/useFlowExecution";
import { LINES } from "@/constants/factoryData";
import { Button } from "@/components/ui/button";
import { getOverallHealth } from "@/api/healthApi";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  MessageSquare,
  Cpu,
  ShieldCheck,
  Pause,
  Play,
  RotateCcw
} from "lucide-react";
import { DiagnosticDialog } from "@/components/diagnostics/DiagnosticDialog";
import { DeviceDetailDialog } from "@/components/devices/DeviceDetailDialog";
import type { SelectedStep, Device } from "@/types";

export function RobotControlPage() {
  const { lineId, cellId } = useParams<{ lineId: string; cellId: string }>();
  const line = LINES.find(l => l.id === lineId);
  const cell = line?.cells.find(c => c.id === cellId);
  const { flow, messages, loading, sendMessage, updateStepParams } = useFlowGeneration();
  const { cameraFrame, lastLabel, callbacks: cameraCallbacks } = useCamera();
  const { flowStatus, nodeStates, finishing, startFlow, pauseFlow, resumeFlow, finishFlow, resetFlow } = useFlowExecution(flow, cameraCallbacks);

  const [selectedStep, setSelectedStep] = useState<SelectedStep | null>(null);
  const [nodeCreatorOpen, setNodeCreatorOpen] = useState(false);
  const [viewMode, setViewMode] = useState<"canvas" | "panel">("canvas");
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);
  const [detailDevice, setDetailDevice] = useState<Device | null>(null);
  const [devicesOpen, setDevicesOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  // Auto-connect hardware on mount
  useEffect(() => {
    const checkInitialHealth = async () => {
      try {
        const health = await getOverallHealth();
        if (health.overall_status !== "healthy") {
          setDiagnosticOpen(true);
        }
      } catch (error) {
        console.error("Initial health check failed:", error);
      }
    };
    checkInitialHealth();
  }, []);

  // Auto-switch to panel view when flow starts
  useEffect(() => {
    if (flowStatus !== "idle" && viewMode === "canvas") {
      setViewMode("panel");
    }
  }, [flowStatus, viewMode]);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-background">
      <TopBar />
      <div className="flex items-center justify-between px-4 py-1.5 border-b border-border bg-card/80 backdrop-blur-panel">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild className="forgis-text-label font-forgis-body text-[var(--gunmetal-50)] no-underline">
                <Link to="/">Forgis Factory</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbLink asChild className="forgis-text-label font-forgis-body text-[var(--gunmetal-50)] no-underline">
                <Link to={`/line/${lineId}`}>{line?.name || "Line"}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage className="forgis-text-label font-forgis-body text-[var(--gunmetal-50)]">
                {cell?.name || "Cell"}
              </BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        {flow && (
          <div className="flex items-center gap-2 rounded-lg bg-muted/30 p-1 border border-border/40">
            <button
              onClick={() => setViewMode("canvas")}
              className={cn(
                "px-3 py-1 text-[10px] font-forgis-digit uppercase tracking-wider rounded-md transition-all",
                viewMode === "canvas" ? "bg-white text-primary shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              Logical Canvas
            </button>
            <button
              onClick={() => setViewMode("panel")}
              className={cn(
                "px-3 py-1 text-[10px] font-forgis-digit uppercase tracking-wider rounded-md transition-all",
                viewMode === "panel" ? "bg-white text-primary shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              State Panel
            </button>
          </div>
        )}

        <div className="flex items-center gap-4">
          <Dialog open={devicesOpen} onOpenChange={setDevicesOpen}>
            <DialogTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 forgis-text-label font-forgis-digit uppercase text-[10px] gap-2 text-[var(--gunmetal-50)] hover:text-primary transition-colors"
              >
                <Cpu size={14} />
                Devices
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md h-[80vh] flex flex-col p-4 bg-card border-border">
              <DialogHeader className="mb-4">
                <DialogTitle>Robot Control & Devices</DialogTitle>
              </DialogHeader>
              <DevicesSidebar
                selectedStep={selectedStep}
                onDeselectStep={() => setSelectedStep(null)}
                onParamChange={(nodeId, stepId, key, value) => updateStepParams(nodeId, stepId, { [key]: value })}
                nodeCreatorOpen={nodeCreatorOpen}
                onCloseNodeCreator={() => setNodeCreatorOpen(false)}
                onOpenDeviceDetail={setDetailDevice}
              />
            </DialogContent>
          </Dialog>

          <Dialog open={chatOpen} onOpenChange={setChatOpen}>
            <DialogTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 forgis-text-label font-forgis-digit uppercase text-[10px] gap-2 text-[var(--gunmetal-50)] hover:text-primary transition-colors"
                disabled={loading}
              >
                <MessageSquare size={14} />
                {loading ? "Thinking..." : "Assistant"}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md h-[80vh] flex flex-col p-4 bg-card border-border">
              <DialogHeader className="mb-4">
                <DialogTitle>Forgis AI Assistant</DialogTitle>
              </DialogHeader>
              <CoderSidebar messages={messages} loading={loading} onSend={sendMessage} />
            </DialogContent>
          </Dialog>

          <Button
            variant="ghost"
            size="sm"
            className="h-8 forgis-text-label font-forgis-digit uppercase text-[10px] gap-2 text-[var(--gunmetal-50)] hover:text-primary transition-colors"
            onClick={() => setDiagnosticOpen(true)}
          >
            <ShieldCheck size={14} />
            Diagnostics
          </Button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden relative">
        {/* Main Workspace */}
        <div className="flex-1 relative bg-[var(--background)]">
          {viewMode === "canvas" ? (
            <FlowCanvas
              flow={flow}
              flowStatus={flowStatus}
              nodeStates={nodeStates}
              onStart={startFlow}
              onPause={pauseFlow}
              onResume={resumeFlow}
              onFinish={finishFlow}
              finishing={finishing}
              onReset={resetFlow}
              onSelectStep={(nodeId, step) => setSelectedStep({ nodeId, step })}
              onAddNode={() => setNodeCreatorOpen(true)}
            />
          ) : (
            <FlowStatePanel
              flow={flow}
              nodeStates={nodeStates}
              cameraFrame={cameraFrame}
              lastLabel={lastLabel?.label || null}
            />
          )}

          {/* Floating Action Bar */}
          <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-3 bg-card/80 backdrop-blur-md border border-border/40 p-1.5 rounded-2xl shadow-2xl z-20">
            <Button
              variant={flowStatus === "idle" ? "default" : "secondary"}
              className="h-10 px-6 rounded-xl font-forgis-digit uppercase tracking-wider"
              onClick={startFlow}
              disabled={!flow || flowStatus !== "idle"}
            >
              Initialize Sequence
            </Button>

            {flowStatus !== "idle" && (
              <>
                {flowStatus === "running" ? (
                  <Button variant="outline" className="h-10 w-10 p-0 rounded-xl" onClick={pauseFlow}>
                    <Pause size={18} />
                  </Button>
                ) : (
                  <Button variant="outline" className="h-10 w-10 p-0 rounded-xl" onClick={resumeFlow}>
                    <Play size={18} />
                  </Button>
                )}
                <Button variant="destructive" className="h-10 w-10 p-0 rounded-xl" onClick={resetFlow}>
                  <RotateCcw size={18} />
                </Button>
              </>
            )}

            {flowStatus === ("finished" as any) && (
              <Button
                variant="default"
                className="h-10 px-6 rounded-xl bg-[var(--status-healthy)] hover:bg-[var(--status-healthy)]/90"
                onClick={finishFlow}
                disabled={finishing}
              >
                Complete Mission
              </Button>
            )}
          </div>
        </div>
      </div>
      <DiagnosticDialog open={diagnosticOpen} onOpenChange={setDiagnosticOpen} />
      <DeviceDetailDialog
        device={detailDevice}
        open={!!detailDevice}
        onOpenChange={(open) => !open && setDetailDevice(null)}
      />
    </div>
  );
}
