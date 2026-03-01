import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Check, ChevronRight, Loader2, X, Zap, Eye, Cpu, Move, Bot, Wrench } from "lucide-react";

import { CHAT_TEXTAREA_MAX_HEIGHT } from "@/constants/chatConfig";
import type { ChatMessage } from "@/types";

// ── ASCII art welcome ────────────────────────────────────────

const WELCOME_ART = `
    ┌──────────────────────┐
    │  ╭─╮   F O R G I S   │
    │  │▓│   Orchestrator   │
    │  └┬┘   ───────────    │
    │ ──┼──  Ready.         │
    │  / \\                  │
    └──────────────────────┘
`.trimStart();

const TIPS = [
  "\"Pick the red box and place it in Zone A\"",
  "\"Count all objects on the table\"",
  "\"Move robot to home position\"",
  "\"Scan the workspace and describe what you see\"",
];

// ── Skill icons ──────────────────────────────────────────────

const SKILL_ICON_MAP: Record<string, typeof Eye> = {
  capture: Eye,
  analyze: Eye,
  er_1_5: Eye,
  depth: Zap,
  robot: Move,
  execution: Move,
  move: Move,
  jog: Move,
  plan: Cpu,
  orchestrator: Cpu,
  input: Cpu,
  summary: Bot,
  verification: Check,
  live: Bot,
  commentary: Bot,
};

function getSkillIcon(name: string) {
  const lower = name.toLowerCase();
  for (const [key, Icon] of Object.entries(SKILL_ICON_MAP)) {
    if (lower.includes(key)) return Icon;
  }
  return Wrench;
}

interface CoderSidebarProps {
  messages: ChatMessage[];
  loading: boolean;
  isOrchestrating?: boolean;
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

// ── Status helpers ───────────────────────────────────────────

function StatusDot({ status }: { status?: string }) {
  const color =
    status === "SUCCESS" ? "bg-emerald-400" :
    status === "FAILURE" ? "bg-red-400" :
    status === "TIMEOUT" ? "bg-amber-400" :
    "bg-sky-400 animate-pulse";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

function statusLabel(status?: string): string {
  if (status === "SUCCESS") return "Done";
  if (status === "FAILURE") return "Failed";
  if (status === "TIMEOUT") return "Timeout";
  return "Running";
}

function statusColor(status?: string): string {
  if (status === "SUCCESS") return "text-emerald-400";
  if (status === "FAILURE") return "text-red-400";
  if (status === "TIMEOUT") return "text-amber-400";
  return "text-sky-400";
}

// ── Message components ───────────────────────────────────────

function MediaGrid({ media, msgId }: { media: ChatMessage["media"]; msgId: string }) {
  if (!media || media.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {media.map((m, idx) => (
        <div
          key={`${msgId}-media-${idx}`}
          className="relative rounded-lg overflow-hidden border border-[var(--terminal-border)] bg-black/20 max-w-[200px]"
        >
          <img
            src={m.dataUrl}
            alt={m.label ?? m.type}
            className="block w-auto h-auto max-w-full max-h-[160px] object-contain"
          />
          {m.label && (
            <span className="absolute bottom-1 left-1.5 text-[9px] px-1.5 py-0.5 rounded bg-black/60 text-white/80">
              {m.label}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function NodeMessage({ msg }: { msg: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const toggle = useCallback(() => setExpanded((p) => !p), []);
  const detail = extractDetail(msg);
  const hasDetail = detail || (msg.media && msg.media.length > 0);
  const status = msg.node?.status ?? "RUNNING";
  const skillName = msg.node?.name ?? "unknown";
  const SkillIcon = getSkillIcon(skillName);

  return (
    <div className="cc-node-block group">
      <button
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left hover:bg-white/[0.02] transition-colors rounded-lg"
        onClick={hasDetail ? toggle : undefined}
      >
        {hasDetail && (
          <span className={`transition-transform duration-150 text-[var(--terminal-muted)] ${expanded ? "rotate-90" : ""}`}>
            <ChevronRight size={11} />
          </span>
        )}
        <span className="w-5 h-5 rounded-md bg-[var(--terminal-panel)] flex items-center justify-center shrink-0">
          <SkillIcon size={11} className={statusColor(status)} />
        </span>
        <span className="flex-1 min-w-0 truncate text-[12px] text-[var(--terminal-fg)]">
          {formatSkillName(skillName)}
        </span>
        <StatusDot status={status} />
        <span className={`text-[10px] font-mono ${statusColor(status)}`}>
          {statusLabel(status)}
        </span>
        {msg.node?.durationMs != null && (
          <span className="text-[10px] font-mono text-[var(--terminal-muted)]">
            {formatDuration(msg.node.durationMs)}
          </span>
        )}
      </button>
      {expanded && (
        <div className="px-3 pb-3 pt-0.5 border-t border-[var(--terminal-border)]/30 mx-3">
          {detail && <p className="text-[11px] text-[var(--terminal-muted)] mt-2 leading-relaxed whitespace-pre-wrap">{detail}</p>}
          <MediaGrid media={msg.media} msgId={msg.id} />
        </div>
      )}
    </div>
  );
}

function PlanMessage({ msg }: { msg: ChatMessage }) {
  const steps = msg.planSteps;
  if (!steps || steps.length === 0) return null;

  return (
    <div className="cc-plan-block">
      <div className="flex items-center gap-2 mb-2">
        <Cpu size={12} className="text-[var(--terminal-accent)]" />
        <span className="text-[10px] uppercase tracking-wider text-[var(--terminal-accent)] font-mono">
          Execution Plan
        </span>
      </div>
      <div className="space-y-1">
        {steps.map((step, idx) => (
          <div key={idx} className="flex items-baseline gap-2 text-[12px]">
            <span className="text-[var(--terminal-muted)] font-mono text-[10px] w-4 text-right shrink-0">
              {idx + 1}.
            </span>
            <span className="text-[var(--terminal-fg)]">{formatSkillName(step.skill)}</span>
            <span className="text-[var(--terminal-muted)] text-[11px] truncate">{step.description}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReasoningMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div className="cc-reasoning-block">
      <div className="flex items-center gap-1.5 mb-1">
        <span className="w-1 h-1 rounded-full bg-[var(--terminal-accent)]" />
        <span className="text-[9px] uppercase tracking-wider text-[var(--terminal-accent)] font-mono">thinking</span>
      </div>
      <p className="text-[12px] text-[var(--terminal-muted)] leading-relaxed whitespace-pre-wrap italic">{msg.content}</p>
    </div>
  );
}

function StatusMessage({ msg }: { msg: ChatMessage }) {
  const isSuccess = msg.kind === "success" || msg.content.includes("SUCCESS");
  const isError = msg.kind === "error" || msg.content.includes("FAILURE") || msg.content.includes("failed");

  return (
    <div className={`cc-status-block ${isSuccess ? "cc-status-success" : ""} ${isError ? "cc-status-error" : ""}`}>
      {isSuccess && <Check size={12} className="inline mr-1.5 -mt-0.5" />}
      {isError && <X size={12} className="inline mr-1.5 -mt-0.5" />}
      {msg.content}
    </div>
  );
}

function UserMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div className="cc-msg-user">
      <span className="cc-user-avatar">You</span>
      <p>{msg.content}</p>
    </div>
  );
}

function AssistantMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div className="cc-msg-assistant">
      <p className="whitespace-pre-wrap">{msg.content}</p>
      <MediaGrid media={msg.media} msgId={msg.id} />
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

// ── Main component ───────────────────────────────────────────

export function CoderSidebar({
  messages,
  loading,
  isOrchestrating = false,
  onSend,
  liveText,
  latestFrame,
  autoplayBlocked,
  onEnableAudio,
}: CoderSidebarProps) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [randomTip] = useState(() => TIPS[Math.floor(Math.random() * TIPS.length)]);

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
    <div className="cc-chat flex flex-col h-full overflow-hidden rounded-xl">
      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 cc-scrollbar">
        {/* Welcome */}
        {messages.length === 0 && (
          <div className="cc-welcome select-none">
            <pre className="text-[10px] leading-tight font-mono text-[var(--terminal-accent)] opacity-70 mb-3">
              {WELCOME_ART}
            </pre>
            <p className="text-[13px] text-[var(--terminal-fg)] font-medium mb-1">
              What should the robot do?
            </p>
            <p className="text-[11px] text-[var(--terminal-muted)] leading-relaxed">
              Describe a task in natural language. I'll plan the skills and execute them step by step.
            </p>
            <div className="mt-3 px-3 py-2 rounded-lg border border-[var(--terminal-border)]/50 bg-[var(--terminal-panel)]/40">
              <span className="text-[9px] uppercase tracking-wider text-[var(--terminal-muted)] font-mono">try</span>
              <p className="text-[11px] text-[var(--terminal-fg)]/70 mt-0.5 italic">{randomTip}</p>
            </div>
          </div>
        )}

        {/* Live panel */}
        {(latestFrame || liveText || autoplayBlocked) && (
          <div className="cc-live-panel">
            {latestFrame && (
              <div>
                <div className="cc-section-label">Live Stream</div>
                <div className="rounded-lg overflow-hidden border border-[var(--terminal-border)] bg-black/30 inline-block max-w-full">
                  <img
                    src={latestFrame}
                    alt="Live stream"
                    className="block w-auto h-auto max-w-full max-h-[200px] object-contain"
                  />
                </div>
              </div>
            )}
            {liveText && (
              <div>
                <div className="cc-section-label">Gemini Live</div>
                <p className="text-[12px] text-[var(--terminal-fg)] leading-relaxed whitespace-pre-wrap">{liveText}</p>
              </div>
            )}
            {autoplayBlocked && onEnableAudio && (
              <button
                type="button"
                className="mt-1 px-3 py-1.5 rounded-lg text-[11px] border border-[var(--terminal-warning)]/50 text-[var(--terminal-warning)] bg-[var(--terminal-warning)]/5 hover:bg-[var(--terminal-warning)]/10 transition-colors cursor-pointer"
                onClick={onEnableAudio}
              >
                Enable audio playback
              </button>
            )}
          </div>
        )}

        {/* Messages */}
        {messages.map(renderMessage)}

        {/* Orchestrator doodle */}
        {isOrchestrating && (
          <div className="cc-doodle-wrap" aria-live="polite" aria-label="Orchestrator is running">
            <div className="cc-doodle-bot" aria-hidden="true">
              <span className="cc-doodle-eye cc-doodle-eye-left" />
              <span className="cc-doodle-eye cc-doodle-eye-right" />
              <span className="cc-doodle-mouth" />
              <span className="cc-doodle-antenna" />
              <span className="cc-doodle-arm cc-doodle-arm-left" />
              <span className="cc-doodle-arm cc-doodle-arm-right" />
            </div>
            <span className="cc-doodle-text">Orchestrating</span>
          </div>
        )}

        {/* Loading indicator */}
        {loading && (
          <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg border border-[var(--terminal-border)]/40 bg-[var(--terminal-panel)]/50">
            <Loader2 size={13} className="animate-spin text-[var(--terminal-accent)]" />
            <span className="text-[12px] text-[var(--terminal-muted)]">Processing</span>
            <span className="cc-cursor" />
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="px-4 pb-3 pt-2">
        <form className="cc-input-area" onSubmit={handleSubmit}>
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
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="cc-send-btn"
          >
            <ArrowUp size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
