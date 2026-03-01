import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { TopBar } from "@/components/layout/Topbar";
import { CoderSidebar } from "@/components/chat/CoderSidebar";
import { GlassTileThread } from "@/components/flow/GlassTileThread";
import { ClarificationModal } from "@/components/flow/ClarificationModal";
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
import { useOrchestratorRun } from "@/hooks/useOrchestratorRun";
import { LINES } from "@/constants/factoryData";
import { Button } from "@/components/ui/button";
import { getOverallHealth } from "@/api/healthApi";

import {
  MessageSquare,
  ShieldCheck,
} from "lucide-react";
import { DiagnosticDialog } from "@/components/diagnostics/DiagnosticDialog";
import { DeviceDetailDialog } from "@/components/devices/DeviceDetailDialog";
import type {
  SelectedStep,
  Device,
  OrchestratorNodeType,
  PlannedOrchestratorNode,
} from "@/types";

const ORCHESTRATOR_NODE_TYPES = new Set<OrchestratorNodeType>([
  "INPUT_NODE",
  "ORCHESTRATOR_PLANNER_NODE",
  "SUMMARY_NODE",
  "CAPTURE_IMAGE",
  "ANALYZE_SCENE",
  "ESTIMATE_GRASP_POSE",
  "DEPTH_ESTIMATION",
  "LLM_REASON",
  "LIVE_NARRATE",
  "MOVE_TO_POSE",
  "MOVE_JOINTS",
  "JOG_JOINTS",
  "GET_ROBOT_STATE",
  "SUCTION_ON",
  "SUCTION_OFF",
  "SET_DIGITAL_OUTPUT",
  "WAIT_DIGITAL_INPUT",
  "WAIT",
  "VERIFY_OUTCOME",
  // Legacy aliases retained for historical data compatibility
  "ER_1_5_ANALYSIS_NODE",
  "DEPTH_ESTIMATION_NODE",
  "ROBOT_EXECUTION_NODE",
  "GEMINI_LIVE_COMMENTARY_NODE",
  "VERIFICATION_NODE",
  "JOG_JOINTS_NODE",
]);

function resolveOrchestratorNodeType(value: string): OrchestratorNodeType {
  return ORCHESTRATOR_NODE_TYPES.has(value as OrchestratorNodeType)
    ? (value as OrchestratorNodeType)
    : "INPUT_NODE";
}

export function RobotControlPage() {
  const { lineId, cellId } = useParams<{ lineId: string; cellId: string }>();
  const line = LINES.find(l => l.id === lineId);
  const cell = line?.cells.find(c => c.id === cellId);
  const { flow, activeFlowId, messages, loading, sendMessage, updateStepParams } = useFlowGeneration();

  const plannedNodes = useMemo<PlannedOrchestratorNode[]>(() => {
    if (!flow) {
      return [];
    }

    return flow.nodes
      .filter((node) => node.type === "state")
      .map((node, order) => ({
        name: node.id,
        type: resolveOrchestratorNodeType(node.label),
        order,
      }));
  }, [flow]);

  const {
    orderedTiles,
    activeTile,
    activeNodeName,
    liveText,
    autoplayBlocked,
    armAudio,
    clarification,
    submitDecision,
    inspectTile,
  } = useOrchestratorRun(activeFlowId, plannedNodes);

  const [selectedStep, setSelectedStep] = useState<SelectedStep | null>(null);
  const [nodeCreatorOpen, setNodeCreatorOpen] = useState(false);
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);
  const [detailDevice, setDetailDevice] = useState<Device | null>(null);

  const [chatOpen, setChatOpen] = useState(true);
  const [leftSidebarWidth, setLeftSidebarWidth] = useState(260);
  const [rightSidebarWidth, setRightSidebarWidth] = useState(320);
  const [isResizingLeft, setIsResizingLeft] = useState(false);
  const [isResizingRight, setIsResizingRight] = useState(false);
  const leftSidebarRef = useRef<HTMLDivElement>(null);
  const rightSidebarRef = useRef<HTMLDivElement>(null);

  const startResizingLeft = useCallback(() => setIsResizingLeft(true), []);
  const startResizingRight = useCallback(() => setIsResizingRight(true), []);
  const stopResizing = useCallback(() => {
    setIsResizingLeft(false);
    setIsResizingRight(false);
  }, []);

  const resize = useCallback(
    (mouseMoveEvent: MouseEvent) => {
      if (isResizingLeft) {
        const newWidth = mouseMoveEvent.clientX;
        if (newWidth > 180 && newWidth < 500) {
          setLeftSidebarWidth(newWidth);
        }
      } else if (isResizingRight) {
        const newWidth = window.innerWidth - mouseMoveEvent.clientX;
        if (newWidth > 200 && newWidth < 800) {
          setRightSidebarWidth(newWidth);
        }
      }
    },
    [isResizingLeft, isResizingRight]
  );

  useEffect(() => {
    window.addEventListener("mousemove", resize);
    window.addEventListener("mouseup", stopResizing);
    return () => {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [resize, stopResizing]);

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

        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="sm"
            className={cn(
              "h-8 forgis-text-label font-forgis-digit uppercase text-[10px] gap-2 transition-colors",
              chatOpen ? "text-primary bg-primary/5" : "text-[var(--gunmetal-50)] hover:text-primary"
            )}
            disabled={loading}
            onClick={() => setChatOpen(!chatOpen)}
          >
            <MessageSquare size={14} />
            {loading ? "Thinking..." : "Assistant"}
          </Button>

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
        {/* Left Sidebar - Devices */}
        <aside
          ref={leftSidebarRef}
          style={{ width: `${leftSidebarWidth}px` }}
          className={cn(
            "border-r border-border bg-card/40 backdrop-blur-sm p-4 flex flex-col z-10 overflow-hidden relative group shrink-0",
            isResizingLeft && "select-none"
          )}
        >
          <DevicesSidebar
            selectedStep={selectedStep}
            onDeselectStep={() => setSelectedStep(null)}
            onParamChange={(nodeId, stepId, key, value) => updateStepParams(nodeId, stepId, { [key]: value })}
            nodeCreatorOpen={nodeCreatorOpen}
            onCloseNodeCreator={() => setNodeCreatorOpen(false)}
            onOpenDeviceDetail={setDetailDevice}
          />
          <div
            onMouseDown={startResizingLeft}
            className={cn(
              "absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-primary/40 transition-colors z-20",
              isResizingLeft && "bg-primary w-1.5"
            )}
          />
        </aside>

        {/* Main Workspace */}
        <div className="flex-1 relative bg-[var(--background)]">
          <GlassTileThread
            orderedTiles={orderedTiles}
            heroTile={activeTile}
            activeNodeName={activeNodeName}
            liveText={liveText}
            onInspectTile={inspectTile}
          />

          {autoplayBlocked && (
            <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-30 bg-card border border-[var(--status-warning)] rounded-xl px-4 py-2 flex items-center gap-3">
              <span className="text-xs font-forgis-body text-foreground">Live audio is blocked by browser autoplay policy.</span>
              <Button size="sm" onClick={armAudio}>Enable Audio</Button>
            </div>
          )}
        </div>

        {/* Right Sidebar - Assistant */}
        {chatOpen && (
          <aside
            ref={rightSidebarRef}
            style={{ width: `${rightSidebarWidth}px` }}
            className={cn(
              "border-l border-border bg-card/40 backdrop-blur-sm p-4 flex flex-col z-10 overflow-hidden relative group shrink-0",
              isResizingRight && "select-none"
            )}
          >
            <div
              onMouseDown={startResizingRight}
              className={cn(
                "absolute top-0 left-0 w-1 h-full cursor-col-resize hover:bg-primary/40 transition-colors z-20",
                isResizingRight && "bg-primary w-1.5"
              )}
            />
            <CoderSidebar messages={messages} loading={loading} onSend={sendMessage} />
          </aside>
        )}
      </div>
      <DiagnosticDialog open={diagnosticOpen} onOpenChange={setDiagnosticOpen} />
      <ClarificationModal
        open={!!clarification}
        reason={clarification?.reason ?? ""}
        timeoutSeconds={clarification?.timeoutSeconds ?? 45}
        onAction={submitDecision}
      />
      <DeviceDetailDialog
        device={detailDevice}
        open={!!detailDevice}
        onOpenChange={(open) => !open && setDetailDevice(null)}
      />
    </div>
  );
}
