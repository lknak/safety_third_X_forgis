import { useCallback, useState } from "react";
import { generateFlow } from "@/api/flowApi";
import { layoutFlow } from "@/services/flowLayoutService";
import type { ChatMessage, Flow } from "@/types";

export function useFlowGeneration() {
  const [flow, setFlow] = useState<Flow | null>(null);
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
      const result = await generateFlow(content);
      setFlow(layoutFlow(result));

      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `I've prepared the automation flow: **${result.name}**. It contains ${result.nodes.length - 2} states. You can review and execute it now.`,
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

  return { flow, messages, loading, sendMessage, updateStepParams };
}
