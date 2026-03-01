import { useCallback, useState } from "react";
import { createOrchestratorTask } from "@/api/orchestratorApi";
import { layoutFlow } from "@/services/flowLayoutService";
import type { ChatMessage, Flow } from "@/types";

export function useFlowGeneration() {
  const [flow, setFlow] = useState<Flow | null>(null);
  const [activeFlowId, setActiveFlowId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);

  const sendMessage = useCallback(async (content: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const result = await createOrchestratorTask(content);
      setActiveFlowId(result.flow_id ?? null);
      if (result.preview_flow) {
        setFlow(layoutFlow(result.preview_flow as unknown as Flow));
      }

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: result.flow_id
          ? `Task queued for orchestrator run **${result.flow_id}**. Review the generated thread and monitor execution telemetry in real time.`
          : result.message,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "An unexpected alignment error occurred.";
      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `**Feasibility Check Failed**\n\n${errorMessage}`,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } finally {
      setLoading(false);
    }
  }, []);

  const updateStepParams = useCallback(
    (nodeId: string, stepId: string, params: Record<string, unknown>) => {
      setFlow((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          nodes: prev.nodes.map((node) =>
            node.id === nodeId
              ? {
                ...node,
                steps: node.steps?.map((s) =>
                  s.id === stepId ? { ...s, params } : s
                ),
              }
              : node
          ),
        };
      });
    },
    []
  );

  return { flow, activeFlowId, messages, loading, sendMessage, updateStepParams };
}
