"use client";

import { useRef, useEffect } from "react";
import { MessageContent } from "./MessageContent";
import { MessageActions } from "./MessageActions";
import { AgentExecutionBlock } from "./AgentExecutionBlock";
import { ApprovalCard } from "./ApprovalCard";
import { RunSummaryCard } from "./RunSummaryCard";
import { TaskPausedCard } from "./TaskPausedCard";
import { cn } from "@/lib/utils";
import { XCircle } from "lucide-react";
import { resolveKind, resolveRunSubtype, type Message } from "@/types/chat";

interface MessageListProps {
  messages: Message[];
  isTyping: boolean;
  onRegenerate: (id: string) => void;
  onLike: (id: string) => void;
  onDislike: (id: string) => void;
  onDelete: (id: string) => void;
  formatFileSize: (bytes: number) => string;
}

/** Renders the inner content of an assistant message bubble */
function AssistantBubbleContent({ message }: { message: Message }) {
  const kind = resolveKind(message);
  const subtype = resolveRunSubtype(message);

  // ── run kind ────────────────────────────────────────────────────────
  if (kind === "run") {
    if (subtype === "block") {
      return <AgentExecutionBlock runId={message.runId!} />;
    }
    if (subtype === "paused") {
      return (
        <TaskPausedCard
          runId={message.runId}
          pausedAtStep={message.pausedAtStep}
          pausedTotalSteps={message.pausedTotalSteps}
        />
      );
    }
    if (subtype === "cancelled") {
      return (
        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 py-1">
          <XCircle className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <span>{message.content || "任务已取消"}</span>
        </div>
      );
    }
    // legacy task_progress without subtype
    if (message.runId) return <AgentExecutionBlock runId={message.runId} />;
  }

  // ── approval kind ────────────────────────────────────────────────────
  if (kind === "approval") {
    return message.approvalRequest ? (
      <ApprovalCard
        messageId={message.id}
        request={message.approvalRequest}
        status={message.approvalStatus ?? "pending"}
        comment={message.approvalComment}
      />
    ) : null;
  }

  // ── summary kind ─────────────────────────────────────────────────────
  if (kind === "summary") {
    return (
      <>
        {message.runSummary ? (
          <RunSummaryCard data={message.runSummary} />
        ) : message.content ? (
          <MessageContent content={message.content} isStreaming={false} isUserMessage={false} />
        ) : null}
      </>
    );
  }

  // ── chat (default) ───────────────────────────────────────────────────
  return (
    <MessageContent
      content={message.content}
      isStreaming={message.isStreaming}
      isUserMessage={false}
    />
  );
}

function shouldShowActions(message: Message): boolean {
  if (message.isStreaming) return false;
  const kind = resolveKind(message);
  const subtype = resolveRunSubtype(message);
  if (kind === "approval") return false;
  if (kind === "run" && subtype !== undefined) return false; // paused/cancelled/block — no actions
  return true;
}

function bubbleStyle(message: Message): string {
  const kind = resolveKind(message);
  const subtype = resolveRunSubtype(message);
  if (kind === "approval" || (kind === "run" && subtype === "paused")) {
    return "border-amber-200 dark:border-amber-800/40 bg-amber-50/30 dark:bg-amber-950/10";
  }
  if (kind === "run" && subtype === "block") {
    return "border-indigo-100 dark:border-indigo-900/40 bg-slate-50 dark:bg-slate-900/60";
  }
  return "border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 text-slate-800 dark:text-slate-200";
}

export function MessageList({
  messages, isTyping, onRegenerate, onLike, onDislike, onDelete, formatFileSize,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const prevLengthRef = useRef<number>(messages.length);
  const isInitialMount = useRef(true);
  const userScrolledUpRef = useRef(false);

  // Track whether user has manually scrolled up
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handleScroll = () => {
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      userScrolledUpRef.current = distanceFromBottom > 80;
    };
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  // Derive a content fingerprint that changes during streaming
  const lastMsg = messages[messages.length - 1];
  const streamingContentLen = lastMsg?.isStreaming ? lastMsg.content.length : 0;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (isInitialMount.current) {
      el.scrollTop = el.scrollHeight;
      isInitialMount.current = false;
      prevLengthRef.current = messages.length;
      return;
    }
    // New message added — auto-scroll and reset user-scrolled flag
    if (messages.length > prevLengthRef.current) {
      userScrolledUpRef.current = false;
      el.scrollTop = el.scrollHeight;
    }
    // Streaming content update — keep scrolled to bottom unless user scrolled up
    if (!userScrolledUpRef.current) {
      el.scrollTop = el.scrollHeight;
    }
    prevLengthRef.current = messages.length;
  }, [messages, streamingContentLen, isTyping]);

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto p-6 space-y-3 scrollbar-thin scrollbar-thumb-slate-200 dark:scrollbar-thumb-white/10"
    >
      {messages.map((message) => (
        <div key={message.id} className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}>

          {/* ── Assistant message ── */}
          {message.role === "assistant" && (
            <div className="group flex items-start gap-2 max-w-[80%] min-w-0">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 text-xs font-bold text-white shadow-sm">
                AO
              </div>
              <div className="flex-1 min-w-0 space-y-1">
                {/* system-style messages skip the bubble wrapper */}
                {resolveKind(message) === "run" && resolveRunSubtype(message) === "cancelled" ? (
                  <AssistantBubbleContent message={message} />
                ) : (
                  <div className={cn(
                    "rounded-2xl rounded-tl-sm border px-3 py-2 shadow-sm dark:shadow-none",
                    bubbleStyle(message)
                  )}>
                    <AssistantBubbleContent message={message} />
                  </div>
                )}

                {shouldShowActions(message) && (
                  <MessageActions
                    messageId={message.id}
                    content={message.content}
                    liked={message.liked}
                    disliked={message.disliked}
                    onRegenerate={onRegenerate}
                    onLike={onLike}
                    onDislike={onDislike}
                    onDelete={onDelete}
                    isAssistant
                  />
                )}
              </div>
            </div>
          )}

          {/* ── User message ── */}
          {message.role === "user" && (
            <div className="group flex flex-row items-start gap-2 max-w-[75%]">
              <div className="flex-1 flex flex-col items-end space-y-2">
                {message.attachments && message.attachments.length > 0 && (
                  <div className="space-y-1">
                    {message.attachments.map((attachment) => (
                      <div
                        key={attachment.id}
                        className="flex items-center gap-2 rounded-lg bg-slate-100 dark:bg-black/20 px-3 py-2 text-sm text-slate-700 dark:text-white border border-slate-200 dark:border-transparent"
                      >
                        <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                        </svg>
                        <span className="flex-1 truncate">{attachment.name}</span>
                        <span className="text-xs text-slate-500 dark:text-white/60">
                          {formatFileSize(attachment.size)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {message.content && (
                  <div className="rounded-2xl rounded-tr-sm bg-gradient-to-r from-indigo-500 to-purple-600 px-3 py-2 text-white shadow-md shadow-indigo-500/20 dark:shadow-none">
                    <MessageContent content={message.content} isUserMessage={true} />
                  </div>
                )}
                <MessageActions
                  messageId={message.id}
                  content={message.content}
                  onDelete={onDelete}
                  isAssistant={false}
                />
              </div>
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-400 to-blue-500 text-xs font-bold text-white shadow-sm">
                U
              </div>
            </div>
          )}
        </div>
      ))}

      {isTyping && (
        <div className="flex justify-start">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 text-xs font-bold text-white">
              AO
            </div>
            <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 px-4 py-3">
              <div className="flex gap-1">
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 dark:bg-white/60 [animation-delay:0ms]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 dark:bg-white/60 [animation-delay:150ms]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 dark:bg-white/60 [animation-delay:300ms]" />
              </div>
              <span className="text-xs text-slate-400 dark:text-slate-500">正在分析任务...</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
