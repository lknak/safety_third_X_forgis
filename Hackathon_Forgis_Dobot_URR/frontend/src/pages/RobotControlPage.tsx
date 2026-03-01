import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { TopBar } from "@/components/layout/Topbar";
import { CoderSidebar } from "@/components/chat/CoderSidebar";
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
import { Button } from "@/components/ui/button";
import { DiagnosticDialog } from "@/components/diagnostics/DiagnosticDialog";
import { DeviceDetailDialog } from "@/components/devices/DeviceDetailDialog";
import { ShieldCheck } from "lucide-react";

import { useFlowGeneration } from "@/hooks/useFlowGeneration";
import { useOrchestratorRun } from "@/hooks/useOrchestratorRun";
import { LINES } from "@/constants/factoryData";
import { getOverallHealth } from "@/api/healthApi";
import type { Device } from "@/types";

export function RobotControlPage() {
  const { lineId, cellId } = useParams<{ lineId: string; cellId: string }>();
  const line = LINES.find((l) => l.id === lineId);
  const cell = line?.cells.find((c) => c.id === cellId);

  const { activeFlowId, messages, loading, sendMessage } = useFlowGeneration();
  const {
    runtimeMessages,
    liveText,
    latestFrame,
    autoplayBlocked,
    armAudio,
    clarification,
    submitDecision,
  } = useOrchestratorRun(activeFlowId);

  const [diagnosticOpen, setDiagnosticOpen] = useState(false);
  const [detailDevice, setDetailDevice] = useState<Device | null>(null);

  const combinedMessages = useMemo(() => [...messages, ...runtimeMessages], [messages, runtimeMessages]);

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
    void checkInitialHealth();
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
            className="h-8 forgis-text-label font-forgis-digit uppercase text-[10px] gap-2 text-[var(--gunmetal-50)] hover:text-primary transition-colors"
            onClick={() => setDiagnosticOpen(true)}
          >
            <ShieldCheck size={14} />
            Diagnostics
          </Button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[320px] border-r border-border bg-card/40 backdrop-blur-sm p-4 overflow-hidden shrink-0">
          <DevicesSidebar onOpenDeviceDetail={setDetailDevice} />
        </aside>

        <main className="flex-1 bg-[var(--background)] p-4">
          <CoderSidebar
            messages={combinedMessages}
            loading={loading}
            onSend={sendMessage}
            liveText={liveText}
            latestFrame={latestFrame}
            autoplayBlocked={autoplayBlocked}
            onEnableAudio={armAudio}
          />
        </main>
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
