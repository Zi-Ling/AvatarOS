"use client";

import React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface TaskProgressBarProps {
  currentStepName?: string;
  completedCount?: number;
  totalCount?: number;
}

export function TaskProgressBar({ currentStepName, completedCount, totalCount }: TaskProgressBarProps) {
  const hasTotal = totalCount && totalCount > 0;
  const percent = hasTotal ? Math.round(((completedCount ?? 0) / totalCount) * 100) : null;

  return (
    <div className="mt-2 space-y-1.5">
      {/* Step name + count */}
      <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <Loader2 className="w-3 h-3 animate-spin shrink-0 text-indigo-500" />
        <span className="truncate">
          {currentStepName ?? "正在执行..."}
        </span>
        {hasTotal && (
          <span className="shrink-0 font-mono text-[10px] text-slate-400">
            {completedCount}/{totalCount}
          </span>
        )}
      </div>

      {/* Progress bar — only when we know total */}
      {hasTotal && percent !== null && (
        <div className="h-1 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              percent === 100 ? "bg-green-500" : "bg-indigo-500"
            )}
            style={{ width: `${percent}%` }}
          />
        </div>
      )}

      {/* Indeterminate bar when no total */}
      {!hasTotal && (
        <div className="h-1 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
          <div className="h-full w-1/3 rounded-full bg-indigo-500 animate-[slide_1.5s_ease-in-out_infinite]" />
        </div>
      )}
    </div>
  );
}
