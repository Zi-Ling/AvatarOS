"use client";

import React, { useState } from "react";
import {
  CheckCircle2, XCircle, Clock, ChevronDown, ChevronUp,
  ExternalLink, ShieldCheck, PauseCircle, Ban, AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useWorkbenchStore } from "@/stores/workbenchStore";
import { MessageContent } from "./MessageContent";
import type { RunSummaryData } from "@/types/chat";

interface RunSummaryCardProps {
  data: RunSummaryData;
}

type TerminalStatus = NonNullable<RunSummaryData["terminalStatus"]>;

const STATUS_CONFIG: Record<TerminalStatus, {
  icon: React.ReactNode;
  label: string;
  border: string;
  bg: string;
}> = {
  completed: {
    icon: <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />,
    label: "任务完成",
    border: "border-slate-200 dark:border-slate-700",
    bg: "bg-slate-50 dark:bg-slate-900/50",
  },
  failed: {
    icon: <XCircle className="w-4 h-4 text-red-500 shrink-0" />,
    label: "任务失败",
    border: "border-red-200 dark:border-red-800/40",
    bg: "bg-red-50/40 dark:bg-red-950/20",
  },
  partial: {
    icon: <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />,
    label: "部分完成",
    border: "border-amber-200 dark:border-amber-800/40",
    bg: "bg-amber-50/40 dark:bg-amber-950/20",
  },
  paused: {
    icon: <PauseCircle className="w-4 h-4 text-amber-500 shrink-0" />,
    label: "已暂停",
    border: "border-amber-200 dark:border-amber-800/40",
    bg: "bg-amber-50/40 dark:bg-amber-950/20",
  },
  cancelled: {
    icon: <Ban className="w-4 h-4 text-slate-400 shrink-0" />,
    label: "已取消",
    border: "border-slate-200 dark:border-slate-700",
    bg: "bg-slate-50 dark:bg-slate-900/50",
  },
};

export function RunSummaryCard({ data }: RunSummaryCardProps) {
  const [expanded, setExpanded] = useState(false);
  const { setActiveTab } = useWorkbenchStore();

  const terminalStatus: TerminalStatus =
    data.terminalStatus ??
    (data.success ? "completed" : data.failedSteps > 0 ? "failed" : "partial");

  const cfg = STATUS_CONFIG[terminalStatus];
  const durationSec = data.durationMs > 0 ? (data.durationMs / 1000).toFixed(1) : null;
  const hasKeyOutputs = data.keyOutputs.length > 0;

  return (
    <div className={cn("mt-3 rounded-xl border overflow-hidden", cfg.border, cfg.bg)}>
      {data.finalAnswer && (
        <div className="px-3 pt-3 pb-2 text-sm text-slate-700 dark:text-slate-200">
          <MessageContent content={data.finalAnswer} isStreaming={false} isUserMessage={false} />
        </div>
      )}
      <div className="flex items-center gap-3 px-3 py-2.5">
        {cfg.icon}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">
            {cfg.label}
            {terminalStatus === "partial" && data.failedSteps > 0 && (
              <span className="ml-1 text-amber-500">（{data.failedSteps} 步失败）</span>
            )}
          </p>
          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-400 font-mono">
            {durationSec && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />{durationSec}s
              </span>
            )}
            {data.totalSteps > 0 && (
              <>
                {durationSec && <span>·</span>}
                <span>{data.completedSteps}/{data.totalSteps} 步</span>
              </>
            )}
            {data.hadApproval && (
              <>
                <span>·</span>
                <span className="flex items-center gap-1 text-amber-500">
                  <ShieldCheck className="w-3 h-3" />审批
                </span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setActiveTab("history")}
            className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            title="查看历史"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
          {hasKeyOutputs && (
            <button
              onClick={() => setExpanded(v => !v)}
              className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            >
              {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>
      </div>
      {expanded && hasKeyOutputs && (
        <div className="border-t border-slate-200 dark:border-slate-700 divide-y divide-slate-100 dark:divide-slate-800">
          {data.keyOutputs.map((output, i) => (
            <div key={i} className="px-3 py-2 flex items-start gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-mono text-indigo-500 dark:text-indigo-400 truncate">
                  {output.skillName ?? output.stepName}
                </p>
                {output.summary && (
                  <p className="text-xs text-slate-600 dark:text-slate-400 line-clamp-2 mt-0.5">
                    {output.summary}
                  </p>
                )}
                {output.artifacts && output.artifacts.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {output.artifacts.map((a, j) => (
                      <span key={j} className="text-[10px] font-mono text-indigo-500 bg-indigo-50 dark:bg-indigo-950/30 px-1.5 py-0.5 rounded truncate max-w-[180px]">
                        {a.split(/[/\\]/).pop()}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
