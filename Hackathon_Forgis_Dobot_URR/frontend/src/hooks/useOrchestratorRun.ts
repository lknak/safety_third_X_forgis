import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createFlowSocket } from "@/api/flowSocket";
import { submitOrchestratorDecision } from "@/api/orchestratorApi";
import type {
  OrchestratorTile,
  OrchestratorNodeType,
  OrchestratorNodeStatus,
  OrchestratorTimelineTile,
  PlannedOrchestratorNode,
  ServerMessage,
} from "@/types";

const DEFAULT_NODE_TYPE_ORDER: OrchestratorNodeType[] = [
  "INPUT_NODE",
  "ORCHESTRATOR_PLANNER_NODE",
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
  "SUMMARY_NODE",
  // Legacy aliases retained for historical data compatibility
  "ER_1_5_ANALYSIS_NODE",
  "DEPTH_ESTIMATION_NODE",
  "ROBOT_EXECUTION_NODE",
  "GEMINI_LIVE_COMMENTARY_NODE",
  "VERIFICATION_NODE",
  "JOG_JOINTS_NODE",
];

function statusFromNode(status: OrchestratorNodeStatus): OrchestratorTile["status"] {
  if (status === "SUCCESS") return "SUCCESS";
  if (status === "FAILURE") return "FAILURE";
  return "TIMEOUT";
}

function typeOrder(type: OrchestratorNodeType): number {
  const idx = DEFAULT_NODE_TYPE_ORDER.indexOf(type);
  return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
}

function seedTiles(plannedNodes: PlannedOrchestratorNode[]): OrchestratorTile[] {
  return [...plannedNodes]
    .sort((a, b) => a.order - b.order)
    .map((node) => ({
      name: node.name,
      type: node.type,
      status: "PENDING",
    }));
}

export function useOrchestratorRun(
  activeFlowId: string | null,
  plannedNodes: PlannedOrchestratorNode[],
) {
  const [tiles, setTiles] = useState<OrchestratorTile[]>([]);
  const [activeNodeName, setActiveNodeName] = useState<string | null>(null);
  const [inspectionNodeName, setInspectionNodeName] = useState<string | null>(null);
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
  const runtimeOrderMapRef = useRef<Map<string, number>>(new Map());
  const nextRuntimeOrderRef = useRef(0);

  const plannedOrderMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const planned of plannedNodes) {
      map.set(planned.name, planned.order);
    }
    return map;
  }, [plannedNodes]);

  const initialTiles = useMemo(() => seedTiles(plannedNodes), [plannedNodes]);

  const getOrder = useCallback((name: string, type: OrchestratorNodeType): number => {
    const plannedOrder = plannedOrderMap.get(name);
    if (plannedOrder !== undefined) {
      return plannedOrder;
    }

    const orderMap = runtimeOrderMapRef.current;
    const existing = orderMap.get(name);
    if (existing !== undefined) {
      return existing;
    }

    const fallback = nextRuntimeOrderRef.current + typeOrder(type);
    nextRuntimeOrderRef.current += 1;
    orderMap.set(name, fallback);
    return fallback;
  }, [plannedOrderMap]);

  const sortTiles = useCallback((items: OrchestratorTile[]): OrchestratorTile[] => {
    const next = [...items];
    next.sort((a, b) => {
      const aOrder = getOrder(a.name, a.type);
      const bOrder = getOrder(b.name, b.type);
      if (aOrder !== bOrder) {
        return aOrder - bOrder;
      }
      return typeOrder(a.type) - typeOrder(b.type);
    });
    return next;
  }, [getOrder]);

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

      return sortTiles(next);
    });
  }, [sortTiles]);

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
        setInspectionNodeName(null);
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
        setActiveNodeName((current) => (current === msg.node_name ? null : current));
        break;

      case "orchestrator_tile_focus":
        setActiveNodeName(msg.active_node);
        setInspectionNodeName(null);
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
  }, [activeFlowId, processAudioQueue, updateTile]);

  useEffect(() => {
    runtimeOrderMapRef.current.clear();
    nextRuntimeOrderRef.current = initialTiles.length;
    setTiles(activeFlowId ? initialTiles : []);
    setActiveNodeName(null);
    setInspectionNodeName(null);
    setLiveText("");
    setClarification(null);
    audioQueue.current = [];
    playingRef.current = false;
  }, [activeFlowId, initialTiles]);

  useEffect(() => {
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

  const orderedTilesBase = useMemo(() => sortTiles(tiles), [sortTiles, tiles]);

  const tileByName = useMemo(() => {
    const map = new Map<string, OrchestratorTile>();
    for (const tile of orderedTilesBase) {
      map.set(tile.name, tile);
    }
    return map;
  }, [orderedTilesBase]);

  const completedTiles = useMemo(
    () =>
      orderedTilesBase.filter(
        (tile) => tile.status === "SUCCESS" || tile.status === "FAILURE" || tile.status === "TIMEOUT",
      ),
    [orderedTilesBase],
  );

  const heroNodeName = useMemo(() => {
    if (inspectionNodeName && tileByName.has(inspectionNodeName)) {
      return inspectionNodeName;
    }
    if (activeNodeName && tileByName.has(activeNodeName)) {
      return activeNodeName;
    }
    if (completedTiles.length > 0) {
      return completedTiles[completedTiles.length - 1].name;
    }
    return orderedTilesBase[0]?.name ?? null;
  }, [activeNodeName, completedTiles, inspectionNodeName, orderedTilesBase, tileByName]);

  const phaseAnchorName = activeNodeName ?? heroNodeName;
  const phaseAnchorIndex = orderedTilesBase.findIndex((tile) => tile.name === phaseAnchorName);

  const orderedTiles = useMemo<OrchestratorTimelineTile[]>(
    () =>
      orderedTilesBase.map((tile, index) => {
        let phase: OrchestratorTimelineTile["phase"] = "future";
        if (phaseAnchorIndex >= 0) {
          if (index < phaseAnchorIndex) phase = "past";
          else if (index === phaseAnchorIndex) phase = "active";
        }

        return {
          ...tile,
          order: getOrder(tile.name, tile.type),
          phase,
          isActive: phase === "active",
          durationMs: tile.startTime && tile.endTime ? Math.max(0, (tile.endTime - tile.startTime) * 1000) : null,
          hasArtifacts: !!tile.artifacts && Object.keys(tile.artifacts).length > 0,
        };
      }),
    [getOrder, orderedTilesBase, phaseAnchorIndex],
  );

  const activeTile = heroNodeName
    ? orderedTiles.find((tile) => tile.name === heroNodeName) ?? null
    : null;

  const pastTiles = useMemo(
    () => orderedTiles.filter((tile) => tile.phase === "past"),
    [orderedTiles],
  );

  const futureTiles = useMemo(
    () => orderedTiles.filter((tile) => tile.phase === "future"),
    [orderedTiles],
  );

  const inspectTile = useCallback((nodeName: string) => {
    setInspectionNodeName((current) => (current === nodeName ? null : nodeName));
  }, []);

  return {
    tiles,
    orderedTiles,
    activeTile,
    pastTiles,
    futureTiles,
    tileByName,
    activeNodeName,
    heroNodeName,
    liveText,
    autoplayBlocked,
    armAudio,
    clarification,
    submitDecision,
    inspectTile,
  };
}
