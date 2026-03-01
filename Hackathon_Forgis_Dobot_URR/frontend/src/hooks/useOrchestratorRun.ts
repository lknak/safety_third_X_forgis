import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createFlowSocket } from "@/api/flowSocket";
import { submitOrchestratorDecision } from "@/api/orchestratorApi";
import type { ChatMessage, OrchestratorTile, OrchestratorNodeType, OrchestratorNodeStatus, ServerMessage, ToolCallMeta } from "@/types";

const ORDERED_NODE_TYPES: OrchestratorNodeType[] = [
  "INPUT_NODE",
  "ORCHESTRATOR_PLANNER_NODE",
  "ER_1_5_ANALYSIS_NODE",
  "DEPTH_ESTIMATION_NODE",
  "ROBOT_EXECUTION_NODE",
  "GEMINI_LIVE_COMMENTARY_NODE",
  "VERIFICATION_NODE",
  "SUMMARY_NODE",
];

function statusFromNode(status: OrchestratorNodeStatus): OrchestratorTile["status"] {
  if (status === "SUCCESS") return "SUCCESS";
  if (status === "FAILURE") return "FAILURE";
  return "TIMEOUT";
}

interface UseOrchestratorRunOptions {
  /** Callback to inject chat messages from planning events. */
  onChatMessage?: (msg: ChatMessage) => void;
  /** Callback to update an existing chat message by id. */
  onUpdateChatMessage?: (id: string, update: Partial<ChatMessage>) => void;
}

export function useOrchestratorRun(
  activeFlowId: string | null,
  options?: UseOrchestratorRunOptions,
) {
  const [tiles, setTiles] = useState<OrchestratorTile[]>([]);
  const [activeNodeName, setActiveNodeName] = useState<string | null>(null);
  const [liveText, setLiveText] = useState<string>("");
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

  // Track which planning thoughts have been emitted as chat messages
  const emittedNodes = useRef<Set<string>>(new Set());

  const updateTile = useCallback((name: string, update: Partial<OrchestratorTile>) => {
    setTiles((prev) => {
      const next = [...prev];
      const idx = next.findIndex((tile) => tile.name === name);
      if (idx >= 0) {
        next[idx] = { ...next[idx], ...update };
      } else {
        next.push({
          name,
          type: (update.type as OrchestratorNodeType) ?? "INPUT_NODE",
          status: "PENDING",
          ...update,
        });
      }
      next.sort((a, b) => ORDERED_NODE_TYPES.indexOf(a.type) - ORDERED_NODE_TYPES.indexOf(b.type));
      return next;
    });
  }, []);

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

  const handleMessage = useCallback((msg: ServerMessage) => {
    // Planning thoughts use a separate guard
    if (msg.type === "orchestrator_planning_thought") {
      if (!("flow_id" in msg) || msg.flow_id !== activeFlowId) return;

      const nodeName = msg.node_name ?? msg.chosen_skill;
      const msgKey = `${msg.flow_id}_${nodeName}_${msg.chosen_skill}`;

      // Don't duplicate
      if (emittedNodes.current.has(msgKey)) return;
      emittedNodes.current.add(msgKey);

      // Skip advance_subgoal — it's just flow control
      if (msg.chosen_skill === "advance_subgoal") return;

      // "done" → text message
      if (msg.is_complete) {
        options?.onChatMessage?.({
          id: crypto.randomUUID(),
          role: "assistant",
          content: msg.catchy_phrase || "All done!",
          timestamp: Date.now(),
          type: "text",
        });
        return;
      }

      // Create a tool_call chat message
      const meta: ToolCallMeta = {
        skillName: msg.chosen_skill,
        status: "running",
        thought: msg.thought,
        catchyPhrase: msg.catchy_phrase,
        contextNote: msg.context_note,
        goalIndex: msg.goal_index,
        confidence: msg.confidence,
        nodeName: nodeName,
      };

      options?.onChatMessage?.({
        id: crypto.randomUUID(),
        role: "assistant",
        content: msg.thought,
        timestamp: Date.now(),
        type: "tool_call",
        meta,
      });
      return;
    }

    // All other messages need flow_id match
    if (!("flow_id" in msg) || !activeFlowId || msg.flow_id !== activeFlowId) {
      return;
    }

    switch (msg.type) {
      case "orchestrator_node_started":
        setActiveNodeName(msg.node_name);
        updateTile(msg.node_name, {
          type: msg.node_type,
          status: "RUNNING",
          startTime: msg.timestamp,
        });
        break;

      case "orchestrator_node_finished": {
        updateTile(msg.node_name, {
          type: msg.node_type,
          status: statusFromNode(msg.status),
          endTime: msg.timestamp,
          artifacts: msg.artifacts,
        });
        if (activeNodeName === msg.node_name) {
          setActiveNodeName(null);
        }

        // Emit a tool_result chat message with final status
        const chatStatus: ToolCallMeta["status"] =
          msg.status === "SUCCESS" ? "success" :
          msg.status === "FAILURE" ? "failure" :
          "timeout";

        options?.onChatMessage?.({
          id: crypto.randomUUID(),
          role: "assistant",
          content: "",
          timestamp: Date.now(),
          type: "tool_result",
          meta: {
            skillName: msg.node_name,
            status: chatStatus,
            durationMs: msg.duration_ms,
            artifacts: msg.artifacts,
            nodeName: msg.node_name,
          },
        });
        break;
      }

      case "orchestrator_tile_focus":
        setActiveNodeName(msg.active_node);
        break;

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

      case "orchestrator_run_completed":
        setActiveNodeName(null);
        break;

      case "orchestrator_replanned":
        options?.onChatMessage?.({
          id: crypto.randomUUID(),
          role: "system",
          content: "Plan updated",
          timestamp: Date.now(),
          type: "system",
        });
        break;

      default:
        break;
    }
  }, [activeFlowId, activeNodeName, processAudioQueue, updateTile, options]);

  useEffect(() => {
    setTiles([]);
    setActiveNodeName(null);
    setLiveText("");
    setClarification(null);
    audioQueue.current = [];
    emittedNodes.current = new Set();

    socketRef.current?.close();
    socketRef.current = null;

    if (!activeFlowId) return;

    let closed = false;

    void createFlowSocket(
      (msg) => {
        if (!closed) handleMessage(msg);
      },
      () => {
        socketRef.current = null;
      },
    ).then((socket) => {
      if (closed) {
        socket.close();
        return;
      }
      socketRef.current = socket;
    }).catch(() => {
      // Handled by existing telemetry UI
    });

    return () => {
      closed = true;
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [activeFlowId, handleMessage]);

  const submitDecision = useCallback(async (
    action: "retry" | "replan" | "modify_goal" | "safe_stop",
    note?: string,
  ) => {
    if (!clarification) return;
    await submitOrchestratorDecision(clarification.flowId, { action, note });
    setClarification(null);
  }, [clarification]);

  const tileByName = useMemo(() => {
    const map = new Map<string, OrchestratorTile>();
    for (const tile of tiles) {
      map.set(tile.name, tile);
    }
    return map;
  }, [tiles]);

  return {
    tiles,
    tileByName,
    activeNodeName,
    liveText,
    autoplayBlocked,
    armAudio,
    clarification,
    submitDecision,
  };
}
