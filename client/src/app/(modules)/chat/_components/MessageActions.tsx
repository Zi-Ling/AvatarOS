"use client";

import React from "react";
import { CopyButton } from "@/components/ui/CopyButton";
import { cn } from "@/lib/utils";

interface MessageActionsProps {
  messageId: string;
  content: string;
  liked?: boolean;
  disliked?: boolean;
  isAssistant: boolean;
  onRegenerate?: (id: string) => void;
  onLike?: (id: string) => void;
  onDislike?: (id: string) => void;
  onDelete: (id: string) => void;
}

export function MessageActions({
  messageId,
  content,
  liked,
  disliked,
  isAssistant,
  onRegenerate,
  onLike,
  onDislike,
  onDelete,
}: MessageActionsProps) {
  return (
    <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <CopyButton text={content} />

      {isAssistant && onRegenerate && (
        <button
          type="button"
          onClick={() => onRegenerate(messageId)}
          className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 dark:text-white/50 transition hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white"
          title="重新生成"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      )}

      {isAssistant && onLike && (
        <button
          type="button"
          onClick={() => onLike(messageId)}
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-lg transition",
            liked
              ? "bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400"
              : "text-slate-400 dark:text-white/50 hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white"
          )}
          title="点赞"
        >
          <svg className="h-4 w-4" fill={liked ? "currentColor" : "none"} stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5" />
          </svg>
        </button>
      )}

      {isAssistant && onDislike && (
        <button
          type="button"
          onClick={() => onDislike(messageId)}
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-lg transition",
            disliked
              ? "bg-red-100 dark:bg-red-500/20 text-red-600 dark:text-red-400"
              : "text-slate-400 dark:text-white/50 hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white"
          )}
          title="踩"
        >
          <svg className="h-4 w-4" fill={disliked ? "currentColor" : "none"} stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14H5.236a2 2 0 01-1.789-2.894l3.5-7A2 2 0 018.736 3h4.018a2 2 0 01.485.06l3.76.94m-7 10v5a2 2 0 002 2h.096c.5 0 .905-.405.905-.904 0-.715.211-1.413.608-2.008L17 13V4m-7 10h2m5-10h2a2 2 0 012 2v6a2 2 0 01-2 2h-2.5" />
          </svg>
        </button>
      )}

      <button
        type="button"
        onClick={() => onDelete(messageId)}
        className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 dark:text-white/50 transition hover:bg-red-100 dark:hover:bg-red-500/20 hover:text-red-600 dark:hover:text-red-400"
        title="删除"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      </button>
    </div>
  );
}
