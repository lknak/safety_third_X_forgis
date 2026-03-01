import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Check, ChevronRight, Loader2, X } from "lucide-react";

import { CHAT_TEXTAREA_MAX_HEIGHT } from "@/constants/chatConfig";
import type { ChatMessage } from "@/types";

interface CoderSidebarProps {
  messages: ChatMessage[];
  loading: boolean;
  onSend: (message: string) => void;
  liveText?: string;
  latestFrame?: string | null;
  autoplayBlocked?: boolean;
  onEnableAudio?: () => void;
}

/** Return a human-friendly skill label. */
function formatSkillName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Summarize duration for display. */
function formatDuration(ms?: number): string {
  if (ms == null || ms < 0) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Extract a short detail line from node artifacts. */
function extractDetail(msg: ChatMessage): string | null {
  const artifacts = msg.artifacts;
  if (!artifacts) return null;

  const error = artifacts.error;
  if (typeof error === "string" && error.trim()) return error.trim();

  const result = artifacts.result;
  if (typeof result === "object" && result) {
    const r = result as Record<string, unknown>;
    if (typeof r.commentary_text === "string") return r.commentary_text;
    if (typeof r.verified === "boolean") return `Verified: ${r.verified ? "yes" : "no"}`;
    if (typeof r.analysis === "object" && r.analysis) {
      const a = r.analysis as Record<string, unknown>;
      if (typeof a.answer === "string") return a.answer;
    }
  }

  if (typeof artifacts.plan_mode === "string") {
    const reasoning = typeof artifacts.reasoning === "string" ? artifacts.reasoning : "";
    return `Mode: ${artifacts.plan_mode}${reasoning ? ` — ${reasoning}` : ""}`;
  }

  return null;
}

function StatusIcon({ status }: { status?: string }) {
  switch (status) {
    case "SUCCESS":
      return <Check size={12} className="text-[var(--terminal-success)]" />;
    case "FAILURE":
      return <X size={12} className="text-[var(--terminal-error)]" />;
    case "TIMEOUT":
      return <Loader2 size={12} className="text-[var(--terminal-warning)]" />;
    case "RUNNING":
      return <span className="terminal-spinner" />;
    default:
      return <span className="terminal-spinner" />;
  }
}

function badgeClass(status?: string): string {
  switch (status) {
    case "SUCCESS":
      return "terminal-node-badge terminal-node-badge-success";
    case "FAILURE":
      return "terminal-node-badge terminal-node-badge-failure";
    case "TIMEOUT":
      return "terminal-node-badge terminal-node-badge-timeout";
    default:
      return "terminal-node-badge terminal-node-badge-running";
  }
}

function NodeMessage({ msg }: { msg: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const toggle = useCallback(() => setExpanded((p) => !p), []);
  const detail = extractDetail(msg);
  const hasDetail = detail || (msg.media && msg.media.length > 0);
  const status = msg.node?.status ?? "RUNNING";
  const skillName = msg.node?.name ?? "unknown";
  const nodeType = msg.node?.type ?? "";

  return (
    <div className="terminal-node-block">
      <div className="terminal-node-header" onClick={hasDetail ? toggle : undefined}>
        {hasDetail && (
          <span className={`terminal-expand-arrow ${expanded ? "terminal-expand-arrow-open" : ""}`}>
            <ChevronRight size={11} />
          </span>
        )}
        <StatusIcon status={status} />
        <span className={badgeClass(status)}>{status}</span>
        <span className="terminal-node-name">{skillName}</span>
        <span className="terminal-node-type">{String(nodeType).replace(/_/g, " ")}</span>
        <span className="terminal-node-duration">{formatDuration(msg.node?.durationMs)}</span>
      </div>
      {expanded && (
        <>
          {detail && <div className="terminal-node-detail">{detail}</div>}
          {msg.media?.map((media, idx) => (
            <div key={`${msg.id}-media-${idx}`} className="terminal-media">
              <img src={media.dataUrl} alt={media.label ?? media.type} />
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function PlanMessage({ msg }: { msg: ChatMessage }) {
  const steps = msg.planSteps;
  if (!steps || steps.length === 0) return null;

  return (
    <div className="terminal-plan">
      <div className="terminal-plan-title">Execution Plan</div>
      {steps.map((step, idx) => (
        <div key={idx} className="terminal-plan-step">
          <span className="terminal-plan-step-num">{idx + 1}.</span>
          <span className="terminal-plan-step-skill">{formatSkillName(step.skill)}</span>
          <span className="terminal-plan-step-desc">{step.description}</span>
        </div>
      ))}
    </div>
  );
}

function ReasoningMessage({ msg }: { msg: ChatMessage }) {
  return <div className="terminal-reasoning">{msg.content}</div>;
}

function StatusMessage({ msg }: { msg: ChatMessage }) {
  const isSuccess = msg.kind === "success" || msg.content.includes("SUCCESS");
  const isError = msg.kind === "error" || msg.content.includes("FAILURE") || msg.content.includes("failed");

  return (
    <div
      className={`terminal-status ${isSuccess ? "terminal-status-success" : ""} ${isError ? "terminal-status-error" : ""}`}
    >
      {isSuccess && <Check size={12} className="inline mr-1 -mt-0.5" />}
      {isError && <X size={12} className="inline mr-1 -mt-0.5" />}
      {msg.content}
    </div>
  );
}

function UserMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div className="terminal-msg-user flex items-start">
      <span className="terminal-prompt">&gt;</span>
      <span>{msg.content}</span>
    </div>
  );
}

function AssistantMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div className="terminal-msg-assistant">
      {msg.content}
      {msg.media?.map((media, idx) => (
        <div key={`${msg.id}-media-${idx}`} className="terminal-media" style={{ paddingLeft: 0 }}>
          <img src={media.dataUrl} alt={media.label ?? media.type} />
        </div>
      ))}
    </div>
  );
}

function renderMessage(msg: ChatMessage) {
  if (msg.role === "user") return <UserMessage key={msg.id} msg={msg} />;

  switch (msg.kind) {
    case "node":
      return <NodeMessage key={msg.id} msg={msg} />;
    case "reasoning":
      return <ReasoningMessage key={msg.id} msg={msg} />;
    case "plan":
      return <PlanMessage key={msg.id} msg={msg} />;
    case "status":
    case "success":
    case "error":
      return <StatusMessage key={msg.id} msg={msg} />;
    default:
      return <AssistantMessage key={msg.id} msg={msg} />;
  }
}

export function CoderSidebar({
  messages,
  loading,
  onSend,
  liveText,
  latestFrame,
  autoplayBlocked,
  onEnableAudio,
}: CoderSidebarProps) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, liveText, latestFrame]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    onSend(trimmed);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  return (
    <div className="terminal-chat flex flex-col h-full min-h-[500px] overflow-hidden rounded-lg">
      <div className="flex flex-col px-4 pb-0 overflow-hidden h-full">
        <div className="terminal-welcome">
          <div className="terminal-welcome-title">Forgis Orchestrator</div>
          <div>Describe a robot task in natural language. I&apos;ll plan and execute it step by step.</div>
          <div style={{ marginTop: 4 }}>
            Examples: <span style={{ color: "var(--terminal-fg)", opacity: 0.7 }}>&quot;Pick the red box and place it in Zone A&quot;</span>
            {" · "}
            <span style={{ color: "var(--terminal-fg)", opacity: 0.7 }}>&quot;Count objects on the table&quot;</span>
          </div>
        </div>

        {(latestFrame || liveText || autoplayBlocked) && (
          <div className="terminal-live-panel">
            {latestFrame && (
              <div>
                <div className="terminal-live-label">Live Stream</div>
                <img src={latestFrame} alt="Live stream" />
              </div>
            )}
            {liveText && (
              <div>
                <div className="terminal-live-label">Gemini Live</div>
                <div className="terminal-live-text">{liveText}</div>
              </div>
            )}
            {autoplayBlocked && onEnableAudio && (
              <button
                type="button"
                className="mt-2 px-2 py-1 rounded text-xs"
                style={{
                  border: "1px solid var(--terminal-warning)",
                  color: "var(--terminal-warning)",
                  background: "transparent",
                  cursor: "pointer",
                }}
                onClick={onEnableAudio}
              >
                Enable audio playback
              </button>
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto flex flex-col py-2">
          {messages.map(renderMessage)}

          {loading && (
            <div className="terminal-status flex items-center gap-2">
              <span className="terminal-spinner" />
              <span>Processing</span>
              <span className="terminal-cursor" />
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form className="terminal-input-area" onSubmit={handleSubmit}>
          <span className="terminal-input-prompt">
            <ArrowRight size={14} />
          </span>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, CHAT_TEXTAREA_MAX_HEIGHT)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
            placeholder="Describe the task..."
            disabled={loading}
            rows={1}
            style={{ maxHeight: CHAT_TEXTAREA_MAX_HEIGHT }}
          />
        </form>
      </div>
    </div>
  );
}
