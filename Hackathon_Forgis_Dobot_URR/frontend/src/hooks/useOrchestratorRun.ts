import { useCallback, useEffect, useRef, useState } from "react";

import { startCameraStream, stopCameraStream } from "@/api/cameraApi";
import { createFlowSocket } from "@/api/flowSocket";
import { submitOrchestratorDecision } from "@/api/orchestratorApi";
import type { ChatMessage, ServerMessage } from "@/types";

/** Build a concise skill name from the raw node name (e.g. "step_1_capture_image" ? "capture_image"). */
function cleanNodeName(rawName: string): string {
  return rawName
    .replace(/^(?:step|iter)\d+_(?:observe_)?/, "")
    .replace(/_/g, " ");
}

function extractNodeMedia(
  msg: Extract<ServerMessage, { type: "orchestrator_node_finished" }>,
): ChatMessage["media"] {
  const artifacts = msg.artifacts;
  const result = artifacts?.result;
  if (msg.node_type === "CAPTURE_IMAGE" && result && typeof result === "object") {
    const imageB64 = (result as Record<string, unknown>).image_b64;
    if (typeof imageB64 === "string" && imageB64.length > 0) {
      return [
        {
          type: "image",
          dataUrl: `data:image/jpeg;base64,${imageB64}`,
          label: cleanNodeName(msg.node_name),
        },
      ];
    }
  }

  return undefined;
}

export function useOrchestratorRun(activeFlowId: string | null) {
  const [runtimeMessages, setRuntimeMessages] = useState<ChatMessage[]>([]);
  const [liveText, setLiveText] = useState<string>("");
  const [latestFrame, setLatestFrame] = useState<string | null>(null);
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);
  const [clarification, setClarification] = useState<{
    flowId: string;
    nodeName: string;
    reason: string;
    timeoutSeconds: number;
    choices: Array<"retry" | "replan" | "modify_goal" | "safe_stop">;
  } | null>(null);

  const audioQueue = useRef<string[]>([]);
  const playingRef = useRef(false);
  const socketRef = useRef<{ close: () => void } | null>(null);

  const processAudioQueue = useCallback(async () => {
    if (playingRef.current) return;
    playingRef.current = true;

    while (audioQueue.current.length > 0) {
      const chunk = audioQueue.current.shift();
      if (!chunk) continue;

      try {
        const audio = new Audio(`data:audio/wav;base64,${chunk}`);
        await audio.play();
      } catch {
        setAutoplayBlocked(true);
        break;
      }
    }

    playingRef.current = false;
  }, []);

  const armAudio = useCallback(() => {
    setAutoplayBlocked(false);
    void processAudioQueue();
  }, [processAudioQueue]);

  const pushMessage = useCallback((message: ChatMessage) => {
    setRuntimeMessages((prev) => [...prev, message]);
  }, []);

  const handleMessage = useCallback(
    (msg: ServerMessage) => {
      if (msg.type === "camera_frame") {
        if (!activeFlowId) return;
        setLatestFrame(`data:image/jpeg;base64,${msg.frame}`);
        return;
      }

      if (!("flow_id" in msg) || !activeFlowId || msg.flow_id !== activeFlowId) {
        return;
      }

      switch (msg.type) {
        case "orchestrator_node_finished": {
          const name = cleanNodeName(msg.node_name);
          const message: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            kind: "node",
            content: name,
            timestamp: Date.now(),
            node: {
              flowId: msg.flow_id,
              name,
              type: msg.node_type,
              status: msg.status,
              durationMs: Math.max(0, msg.duration_ms),
            },
            artifacts: msg.artifacts,
            media: extractNodeMedia(msg),
          };
          pushMessage(message);
          break;
        }

        case "orchestrator_agentic_micro_plan": {
          const reasoning = msg.reasoning || "No reasoning provided.";
          const progress = msg.progress as Record<string, unknown> | undefined;
          const completed = typeof progress?.completed === "number" ? progress.completed : null;
          const remaining = typeof progress?.estimated_remaining === "number" ? progress.estimated_remaining : null;
          const progressNote = completed != null && remaining != null
            ? ` [${completed}/${completed + remaining}]`
            : "";

          const message: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            kind: "reasoning",
            content: `Iteration ${msg.iteration}${progressNote}: ${reasoning}${msg.scene_summary ? `\nScene: ${msg.scene_summary}` : ""}`,
            timestamp: Date.now(),
          };
          pushMessage(message);
          break;
        }

        case "orchestrator_live_chunk":
          setLiveText(msg.text);
          audioQueue.current.push(msg.audio_chunk);
          void processAudioQueue();
          break;

        case "orchestrator_clarification_requested":
          setClarification({
            flowId: msg.flow_id,
            nodeName: msg.node_name,
            reason: msg.reason,
            timeoutSeconds: msg.timeout_seconds,
            choices: msg.choices,
          });
          break;

        case "orchestrator_clarification_resolved":
        case "orchestrator_clarification_timeout":
          setClarification(null);
          break;

        case "orchestrator_run_completed": {
          void stopCameraStream().catch(() => undefined);
          const isSuccess = msg.final_status === "SUCCESS";
          const message: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            kind: isSuccess ? "success" : "error",
            content: msg.error
              ? `Run completed: ${msg.final_status} — ${msg.error}`
              : `Run completed: ${msg.final_status}`,
            timestamp: Date.now(),
          };
          pushMessage(message);
          break;
        }

        default:
          break;
      }
    },
    [activeFlowId, processAudioQueue, pushMessage],
  );

  useEffect(() => {
    setRuntimeMessages([]);
    setLiveText("");
    setLatestFrame(null);
    setClarification(null);
    audioQueue.current = [];
    playingRef.current = false;
  }, [activeFlowId]);

  useEffect(() => {
    socketRef.current?.close();
    socketRef.current = null;

    if (!activeFlowId) {
      void stopCameraStream().catch(() => undefined);
      return;
    }

    let closed = false;
    void startCameraStream(15).catch(() => undefined);

    void createFlowSocket(
      (msg) => {
        if (!closed) handleMessage(msg);
      },
      () => {
        socketRef.current = null;
      },
    )
      .then((socket) => {
        if (closed) {
          socket.close();
          return;
        }
        socketRef.current = socket;
      })
      .catch(() => {
        // No-op: runtime status is reported in chat when available.
      });

    return () => {
      closed = true;
      socketRef.current?.close();
      socketRef.current = null;
      void stopCameraStream().catch(() => undefined);
    };
  }, [activeFlowId, handleMessage]);

  const submitDecision = useCallback(
    async (action: "retry" | "replan" | "modify_goal" | "safe_stop", note?: string) => {
      if (!clarification) return;
      await submitOrchestratorDecision(clarification.flowId, { action, note });
      setClarification(null);
    },
    [clarification],
  );

  return {
    runtimeMessages,
    liveText,
    latestFrame,
    autoplayBlocked,
    armAudio,
    clarification,
    submitDecision,
  };
}
