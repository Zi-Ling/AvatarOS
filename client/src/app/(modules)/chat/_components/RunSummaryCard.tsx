"use client";

import React, { useState } from "react";
import { CheckCircle2, Clock, ChevronDown, ChevronUp, ExternalLink, AlertCircle, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWorkbenchStore } from "@/stores/workbenchStore";
import type { RunSummaryData } from "@/types/chat";

interface RunSummaryCardProps {
  data: RunSummaryData;
}

export function RunSummaryCard({ data }: RunSummaryCardProps) {
  const [expanded, setExpanded] = useState(false);
  const { setActiveTab } = useWorkbenchStore();

  const durationSec = (data.durationMs / 1000).toFixed(1);
  const allOk = data.success !== false && data.failedSteps === 0;

  return (
    <div className="mt-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 overflow-hidden">
      {/* Summary row */}
      <div className="flex items-center gap-3 px-3 py-2.5">
        <CheckCircle2 className={cn("w-4 h-4 shrink-0", allOk ? "text-green-500" : "text-amber-500")} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">
            {allOk ? "任务完成" : `完成（${data.failedSteps} 步失败）`}
          </p>
          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-400 font-mono">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />{durationSec}s
            </span>
            <span>·</span>
            <span>{data.completedSteps}/{data.totalSteps} 步</span>
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
          {data.keyOutputs.length > 0 && (
            <button
              onClick={() => setExpanded(v => !v)}
              className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            >
              {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>
      </div>

      {/* Expandable key outputs */}
      {expanded && data.keyOutputs.length > 0 && (
        <div className="border-t border-slate-200 dark:border-slate-700 divide-y divide-slate-100 dark:divide-slate-800">
          {data.keyOutputs.map((output, i) => (
            <div key={i} className="px-3 py-2 flex items-start gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-[10px] font-mono text-indigo-500 dark:text-indigo-400 truncate">
                  {output.skillName ?? output.stepName}
                </p>
                {output.summary && (
                  <p className="text-xs text-slate-600 dark:text-slate-400 line-clamp-2 mt-0.5">
                    {output.summary}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
