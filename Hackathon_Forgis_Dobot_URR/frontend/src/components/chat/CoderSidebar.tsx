import { useRef, useState, useEffect } from "react";
import { Send, ChevronDown, ChevronRight, Eye, Cpu, Move, Mic, CheckCircle2, AlertTriangle, Loader2, Wrench, Bot, Zap, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types";
import { CHAT_TEXTAREA_MAX_HEIGHT } from "@/constants/chatConfig";

// ── Skill icon mapping ───────────────────────────────────────

const SKILL_ICONS: Record<string, typeof Eye> = {
  capture_cell_state: Eye,
  decompose_task: Cpu,
  analyze_scene: Eye,
  estimate_depth: Zap,
  move_robot: Move,
  narrate_live: Mic,
  verify_motion: CheckCircle2,
  jog_joints: Move,
  summarize: Bot,
  retry: Wrench,
  done: CheckCircle2,
  advance_subgoal: ChevronRight,
};

const SKILL_LABELS: Record<string, string> = {
  capture_cell_state: "Cell State Capture",
  decompose_task: "Task Decomposition",
  analyze_scene: "Scene Analysis (ER)",
  estimate_depth: "Depth Estimation",
  move_robot: "Robot Motion",
  narrate_live: "Live Commentary",
  verify_motion: "Motion Verification",
  jog_joints: "Joint Jog",
  summarize: "Execution Summary",
  retry: "Retry",
  done: "Complete",
  advance_subgoal: "Next Subgoal",
};

// ── ASCII doodle ─────────────────────────────────────────────

const WELCOME_DOODLE = `
    ╭─────────────────────────╮
    │   ┌─┐  FORGIS           │
    │   │█│  Orchestrator      │
    │   └┬┘  ──────────────    │
    │  ──┼──  Ready to plan.   │
    │   / \\                    │
    ╰─────────────────────────╯
`.trimStart();

const WELCOME_PHRASES = [
  "What are we building today?",
  "Give me a task — I'll figure out the skills.",
  "Ready when you are. Describe the mission.",
  "Drop a task and I'll plan it node by node.",
];

// ── Sub-components ───────────────────────────────────────────

function WelcomeBlock({ onDemo, demoDisabled }: { onDemo?: () => void; demoDisabled?: boolean }) {
  const phrase = WELCOME_PHRASES[Math.floor(Math.random() * WELCOME_PHRASES.length)];
  return (
    <div className="mb-4 select-none">
      <pre className="text-[10px] leading-tight text-[var(--tiger)] font-mono opacity-80 mb-2">
        {WELCOME_DOODLE}
      </pre>
      <p className="text-xs text-muted-foreground font-forgis-body italic mb-3">
        {phrase}
      </p>
      {onDemo && (
        <button
          onClick={onDemo}
          disabled={demoDisabled}
          className={cn(
            "w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg border transition-all text-left group",
            demoDisabled
              ? "border-border/30 opacity-40 cursor-not-allowed"
              : "border-[var(--tiger)]/30 bg-[var(--tiger)]/5 hover:bg-[var(--tiger)]/10 hover:border-[var(--tiger)]/50 cursor-pointer"
          )}
        >
          <div className="w-7 h-7 rounded-md bg-[var(--tiger)]/10 flex items-center justify-center shrink-0">
            <Play size={12} className="text-[var(--tiger)]" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[11px] font-forgis-digit uppercase tracking-wider text-foreground leading-tight">
              Skill Demo
            </p>
            <p className="text-[9px] text-muted-foreground font-forgis-body mt-0.5 leading-snug">
              Tiny joints, camera, live video — one by one
            </p>
          </div>
        </button>
      )}
    </div>
  );
}

function ThinkingIndicator({ phrase }: { phrase?: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/30 border border-border/30">
      <Loader2 size={12} className="animate-spin text-[var(--tiger)]" />
      <span className="text-xs text-muted-foreground font-forgis-body italic">
        {phrase || "Thinking..."}
      </span>
    </div>
  );
}

function ToolCallBlock({ msg }: { msg: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const meta = msg.meta;
  if (!meta) return null;

  const Icon = SKILL_ICONS[meta.skillName] || Wrench;
  const label = SKILL_LABELS[meta.skillName] || meta.skillName;

  const statusColor =
    meta.status === "success" ? "text-[var(--status-healthy)]" :
    meta.status === "failure" || meta.status === "timeout" ? "text-[var(--status-critical)]" :
    meta.status === "running" ? "text-[var(--status-warning)]" :
    "text-muted-foreground";

  const borderColor =
    meta.status === "success" ? "border-[var(--status-healthy)]/30" :
    meta.status === "failure" || meta.status === "timeout" ? "border-[var(--status-critical)]/30" :
    meta.status === "running" ? "border-[var(--status-warning)]/30" :
    "border-border/30";

  const statusIcon =
    meta.status === "success" ? <CheckCircle2 size={10} className="text-[var(--status-healthy)]" /> :
    meta.status === "failure" || meta.status === "timeout" ? <AlertTriangle size={10} className="text-[var(--status-critical)]" /> :
    meta.status === "running" ? <Loader2 size={10} className="animate-spin text-[var(--status-warning)]" /> :
    null;

  return (
    <div className={cn("rounded-lg border bg-card/50 overflow-hidden transition-all", borderColor)}>
      {/* Header */}
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-muted/20 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <Icon size={12} className={statusColor} />
        <span className="text-[11px] font-forgis-digit uppercase tracking-wider text-foreground flex-1">
          {label}
        </span>
        {statusIcon}
        {meta.durationMs != null && (
          <span className="text-[9px] text-muted-foreground font-mono">
            {meta.durationMs}ms
          </span>
        )}
        {expanded ? <ChevronDown size={10} className="text-muted-foreground" /> : <ChevronRight size={10} className="text-muted-foreground" />}
      </button>

      {/* Thought / Reasoning */}
      {meta.thought && (
        <div className="px-3 pb-1.5 -mt-0.5">
          <p className="text-[10px] text-muted-foreground font-forgis-body italic leading-snug">
            {meta.thought}
          </p>
        </div>
      )}

      {/* Expanded content */}
      {expanded && (
        <div className="px-3 pb-2 border-t border-border/20 pt-2 space-y-1.5">
          {meta.catchyPhrase && (
            <p className="text-[10px] text-[var(--tiger)] font-forgis-body">
              {meta.catchyPhrase}
            </p>
          )}
          {meta.contextNote && (
            <p className="text-[10px] text-muted-foreground font-forgis-body">
              {meta.contextNote}
            </p>
          )}
          {meta.goalIndex != null && (
            <p className="text-[10px] text-muted-foreground font-mono">
              Subgoal: {meta.goalIndex + 1}
            </p>
          )}
          {meta.artifacts && Object.keys(meta.artifacts).length > 0 && (
            <pre className="text-[9px] font-mono text-foreground/70 bg-muted/30 rounded p-1.5 overflow-x-auto max-h-[120px] overflow-y-auto">
              {JSON.stringify(meta.artifacts, null, 2).slice(0, 500)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function PlanStepBlock({ msg }: { msg: ChatMessage }) {
  const meta = msg.meta;
  if (!meta) return null;

  if (meta.status === "running") {
    return <ThinkingIndicator phrase={meta.catchyPhrase || meta.thought} />;
  }

  return <ToolCallBlock msg={msg} />;
}

function SystemMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <div className="h-px flex-1 bg-border/40" />
      <span className="text-[9px] text-muted-foreground font-forgis-digit uppercase tracking-widest">
        {msg.content}
      </span>
      <div className="h-px flex-1 bg-border/40" />
    </div>
  );
}

function UserMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div
      className="self-end max-w-[90%] px-3 py-2 rounded-lg rounded-br-sm border forgis-text-body leading-snug break-words text-foreground font-forgis-body"
      style={{ background: "var(--chat-user-bg)", borderColor: "var(--chat-user-border)" }}
    >
      {msg.content}
    </div>
  );
}

function AssistantMessage({ msg }: { msg: ChatMessage }) {
  return (
    <div
      className="self-start max-w-[90%] px-3 py-2 rounded-lg rounded-bl-sm forgis-text-body leading-snug break-words text-foreground font-forgis-body"
      style={{ background: "var(--chat-assistant-bg)" }}
    >
      {msg.content}
    </div>
  );
}

function ToolResultBlock({ msg }: { msg: ChatMessage }) {
  const meta = msg.meta;
  if (!meta) return null;

  const isOk = meta.status === "success";
  const isFail = meta.status === "failure" || meta.status === "timeout";

  return (
    <div className={cn(
      "flex items-center gap-2 px-3 py-1 rounded-md text-[10px] font-mono",
      isOk ? "text-[var(--status-healthy)]/80" :
      isFail ? "text-[var(--status-critical)]/80" :
      "text-muted-foreground"
    )}>
      {isOk ? <CheckCircle2 size={9} /> : isFail ? <AlertTriangle size={9} /> : null}
      <span>{meta.nodeName || meta.skillName}</span>
      {meta.durationMs != null && (
        <span className="text-muted-foreground">
          {meta.durationMs > 1000 ? `${(meta.durationMs / 1000).toFixed(1)}s` : `${meta.durationMs}ms`}
        </span>
      )}
    </div>
  );
}

function MessageRenderer({ msg }: { msg: ChatMessage }) {
  switch (msg.type) {
    case "tool_call":
    case "skill_invocation":
      return <ToolCallBlock msg={msg} />;
    case "tool_result":
      return <ToolResultBlock msg={msg} />;
    case "plan_step":
      return <PlanStepBlock msg={msg} />;
    case "thinking":
      return <ThinkingIndicator phrase={msg.content} />;
    case "system":
      return <SystemMessage msg={msg} />;
    default:
      if (msg.role === "user") return <UserMessage msg={msg} />;
      return <AssistantMessage msg={msg} />;
  }
}

// ── Completion summary ───────────────────────────────────────

function CompletionBanner({ status, phrase }: { status: string; phrase?: string }) {
  const isSuccess = status === "SUCCESS";
  return (
    <div className={cn(
      "flex items-center gap-2 px-3 py-2 rounded-lg border",
      isSuccess
        ? "bg-[var(--status-healthy)]/5 border-[var(--status-healthy)]/30"
        : "bg-[var(--status-critical)]/5 border-[var(--status-critical)]/30"
    )}>
      {isSuccess
        ? <CheckCircle2 size={14} className="text-[var(--status-healthy)]" />
        : <AlertTriangle size={14} className="text-[var(--status-critical)]" />
      }
      <span className="text-xs font-forgis-body text-foreground">
        {phrase || (isSuccess ? "Task complete." : "Task failed.")}
      </span>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────

interface CoderSidebarProps {
  messages: ChatMessage[];
  loading: boolean;
  onSend: (message: string) => void;
  onDemo?: () => void;
}

export function CoderSidebar({ messages, loading, onSend, onDemo }: CoderSidebarProps) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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

  // Count skill invocations for a quick stat line
  const skillCount = messages.filter(m => m.type === "tool_call" || m.type === "skill_invocation").length;
  const successCount = messages.filter(m => (m.type === "tool_call" || m.type === "skill_invocation") && m.meta?.status === "success").length;

  return (
    <div className="flex flex-col h-full min-h-[500px] overflow-hidden">
      <div className="flex flex-col px-1 pb-0 overflow-hidden h-full">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <h2 className="forgis-text-title font-normal uppercase text-[var(--gunmetal-50)] leading-none font-forgis-digit">
            Orchestrator
          </h2>
          {skillCount > 0 && (
            <span className="text-[9px] font-mono text-muted-foreground bg-muted/30 px-1.5 py-0.5 rounded">
              {successCount}/{skillCount} skills
            </span>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto flex flex-col gap-2 pb-2 scrollbar-thin">
          <WelcomeBlock onDemo={onDemo} demoDisabled={loading} />

          {messages.map((msg) => (
            <MessageRenderer key={msg.id} msg={msg} />
          ))}

          {loading && !messages.some(m => m.type === "thinking") && (
            <ThinkingIndicator />
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input form */}
        <form className="flex items-end gap-1.5 py-2.5 border-t border-border" onSubmit={handleSubmit}>
          <textarea
            ref={textareaRef}
            className="flex-1 px-2.5 py-2 bg-input border border-border rounded-md text-foreground forgis-text-body outline-none focus:border-[var(--tiger)] placeholder:text-muted-foreground font-forgis-body resize-none overflow-hidden"
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
            className="px-3 py-2 bg-[var(--tiger)] text-white rounded-md forgis-text-body font-normal cursor-pointer border-none hover:bg-[var(--tiger)]/90 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            type="submit"
            disabled={loading || !input.trim()}
          >
            <Send size={14} />
          </button>
        </form>
      </div>
    </div>
  );
}
