import { useCallback, useState } from "react";

import { createOrchestratorTask } from "@/api/orchestratorApi";
import type { ChatMessage } from "@/types";

export function useFlowGeneration() {
  const [activeFlowId, setActiveFlowId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);

  const sendMessage = useCallback(async (content: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      timestamp: Date.now(),
      kind: "text",
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const result = await createOrchestratorTask(content);

      if (result.mode === "cell_manager") {
        setActiveFlowId(null);

        const assistantMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          kind: "text",
          content: result.message,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else {
        setActiveFlowId(result.flow_id ?? null);

        if (result.plan?.reasoning) {
          const reasoningMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            kind: "reasoning",
            content: result.plan.reasoning,
            timestamp: Date.now(),
          };
          setMessages((prev) => [...prev, reasoningMsg]);
        }

        if (result.plan && result.plan.steps.length > 0) {
          const planMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            kind: "plan",
            content: result.plan.is_agentic
              ? "Agentic mode — will observe and plan each step dynamically."
              : `Static plan with ${result.plan.steps.length} steps. Executing now...`,
            timestamp: Date.now(),
            planSteps: result.plan.is_agentic ? undefined : result.plan.steps,
          };
          setMessages((prev) => [...prev, planMsg]);
        } else if (result.plan?.is_agentic) {
          const agenticMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            kind: "status",
            content: "Agentic mode — will observe, reason, and act iteratively until the task is complete.",
            timestamp: Date.now(),
          };
          setMessages((prev) => [...prev, agenticMsg]);
        } else {
          const statusMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            kind: "status",
            content: result.flow_id
              ? `Task queued (${result.flow_id}). Executing...`
              : result.message,
            timestamp: Date.now(),
          };
          setMessages((prev) => [...prev, statusMsg]);
        }
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "An unexpected error occurred.";
      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        kind: "error",
        content: `Error: ${errorMessage}`,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setActiveFlowId(null);
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    activeFlowId,
    messages,
    loading,
    sendMessage,
  };
}
