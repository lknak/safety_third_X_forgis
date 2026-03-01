import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createFlowSocket } from "@/api/flowSocket";
import { submitOrchestratorDecision } from "@/api/orchestratorApi";
import type { OrchestratorTile, OrchestratorNodeType, OrchestratorNodeStatus, ServerMessage } from "@/types";

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

export function useOrchestratorRun(activeFlowId: string | null) {
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

      case "orchestrator_node_finished":
        updateTile(msg.node_name, {
          type: msg.node_type,
          status: statusFromNode(msg.status),
          endTime: msg.timestamp,
          artifacts: msg.artifacts,
        });
        if (activeNodeName === msg.node_name) {
          setActiveNodeName(null);
        }
        break;

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

      default:
        break;
    }
  }, [activeFlowId, activeNodeName, processAudioQueue, updateTile]);

  useEffect(() => {
    setTiles([]);
    setActiveNodeName(null);
    setLiveText("");
    setClarification(null);
    audioQueue.current = [];

    socketRef.current?.close();
    socketRef.current = null;

    if (!activeFlowId) {
      return;
    }

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
      // Handled by existing telemetry UI and fallback states.
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
