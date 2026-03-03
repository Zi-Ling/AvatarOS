"use client";

import React, { useRef, useEffect } from "react";
import { MessageContent } from "./MessageContent";
import { CopyButton } from "@/components/ui/CopyButton";
import { TaskProgress } from "./TaskProgress";
import { MessageActions } from "./MessageActions";
import { cn } from "@/lib/utils";
import { Message } from "@/stores/chatStore";
import type { ExecutionFlowData } from "@/components/ui/ExecutionFlow";

interface MessageListProps {
  messages: Message[];
  isTyping: boolean;
  executionFlow?: ExecutionFlowData;
  onRegenerate: (id: string) => void;
  onLike: (id: string) => void;
  onDislike: (id: string) => void;
  onDelete: (id: string) => void;
  formatFileSize: (bytes: number) => string;
}

export function MessageList({
  messages,
  isTyping,
  executionFlow,
  onRegenerate,
  onLike,
  onDislike,
  onDelete,
  formatFileSize,
}: MessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fix #8: 用 debounce 替代 throttle，确保流式输出最后一条消息也能滚动到
  useEffect(() => {
    if (scrollTimerRef.current) {
      clearTimeout(scrollTimerRef.current);
    }
    scrollTimerRef.current = setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 150);

    return () => {
      if (scrollTimerRef.current) {
        clearTimeout(scrollTimerRef.current);
      }
    };
  }, [messages]);

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-3 scrollbar-thin scrollbar-thumb-slate-200 dark:scrollbar-thumb-white/10">
      {messages.map((message) => (
        <div
          key={message.id}
          className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
        >
          {/* AI 消息 */}
          {message.role === "assistant" && (
            <div className="group flex items-start gap-2 max-w-[75%]">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 text-xs font-bold text-white shadow-sm">
                IA
              </div>
              <div className="flex-1 space-y-2">
                <div className="rounded-2xl rounded-tl-sm border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 px-3 py-2 text-slate-800 dark:text-slate-200 shadow-sm dark:shadow-none">
                  <MessageContent
                    content={message.content}
                    isStreaming={message.isStreaming}
                    isUserMessage={false}
                    executionFlow={message.isStreaming ? executionFlow : undefined}
                  />
                  {message.isTask && message.taskSteps && message.taskSteps.length > 0 && (
                    <TaskProgress steps={message.taskSteps} taskStatus={message.taskStatus} />
                  )}
                </div>
                {!message.isStreaming && (
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

          {/* 用户消息 */}
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

      {/* AI 输入中提示 */}
      {isTyping && (
        <div className="flex justify-start">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 text-xs font-bold text-white">
              IA
            </div>
            <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 px-4 py-3">
              <div className="flex gap-1">
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 dark:bg-white/60 [animation-delay:0ms]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 dark:bg-white/60 [animation-delay:150ms]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 dark:bg-white/60 [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
}
