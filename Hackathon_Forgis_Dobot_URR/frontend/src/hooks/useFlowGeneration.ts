import { useCallback, useState } from "react";
import { createOrchestratorTask, startSkillDemo } from "@/api/orchestratorApi";
import { layoutFlow } from "@/services/flowLayoutService";
import type { ChatMessage, Flow } from "@/types";

// ── Catchy response phrases ──────────────────────────────────

const QUEUED_PHRASES = [
  "Roger that. Task is queued and I'm on it.",
  "Got it — planning the approach now.",
  "Locked in. Watch the thread for real-time progress.",
  "Mission accepted. Executing node by node.",
];

const ERROR_PHRASES = [
  "Hmm, that didn't land.",
  "Hit a snag on that one.",
  "Something's off — let me explain.",
];

function pickRandom(arr: string[]): string {
  return arr[Math.floor(Math.random() * arr.length)];
}

export function useFlowGeneration() {
  const [flow, setFlow] = useState<Flow | null>(null);
  const [activeFlowId, setActiveFlowId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);

  const addMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateMessage = useCallback((id: string, update: Partial<ChatMessage>) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, ...update } : m))
    );
  }, []);

  const sendMessage = useCallback(async (content: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      timestamp: Date.now(),
      type: "text",
    };
    addMessage(userMsg);
    setLoading(true);

    try {
      const result = await createOrchestratorTask(content);
      setActiveFlowId(result.flow_id ?? null);
      if (result.preview_flow) {
        setFlow(layoutFlow(result.preview_flow as unknown as Flow));
      }

      if (result.flow_id) {
        // Task accepted — add a system message and the assistant response
        addMessage({
          id: crypto.randomUUID(),
          role: "system",
          content: `Flow ${result.flow_id}`,
          timestamp: Date.now(),
          type: "system",
        });
        addMessage({
          id: crypto.randomUUID(),
          role: "assistant",
          content: pickRandom(QUEUED_PHRASES),
          timestamp: Date.now(),
          type: "text",
        });
      } else {
        addMessage({
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.message,
          timestamp: Date.now(),
          type: "text",
        });
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "An unexpected alignment error occurred.";
      addMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: `${pickRandom(ERROR_PHRASES)}\n\n${errorMessage}`,
        timestamp: Date.now(),
        type: "text",
      });
    } finally {
      setLoading(false);
    }
  }, [addMessage]);

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

  const launchDemo = useCallback(async () => {
    addMessage({
      id: crypto.randomUUID(),
      role: "system",
      content: "Skill Demo",
      timestamp: Date.now(),
      type: "system",
    });
    addMessage({
      id: crypto.randomUUID(),
      role: "assistant",
      content: "Launching the skill demo — I'll walk through every capability one by one.",
      timestamp: Date.now(),
      type: "text",
    });
    setLoading(true);

    try {
      const result = await startSkillDemo();
      setActiveFlowId(result.flow_id ?? null);
      if (result.preview_flow) {
        setFlow(layoutFlow(result.preview_flow as unknown as Flow));
      }

      if (result.flow_id) {
        addMessage({
          id: crypto.randomUUID(),
          role: "system",
          content: `Demo flow ${result.flow_id}`,
          timestamp: Date.now(),
          type: "system",
        });
      } else {
        addMessage({
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.message,
          timestamp: Date.now(),
          type: "text",
        });
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Demo failed to launch.";
      addMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: `${pickRandom(ERROR_PHRASES)}\n\n${errorMessage}`,
        timestamp: Date.now(),
        type: "text",
      });
    } finally {
      setLoading(false);
    }
  }, [addMessage]);

  return { flow, activeFlowId, messages, loading, sendMessage, updateStepParams, addMessage, updateMessage, launchDemo };
}
