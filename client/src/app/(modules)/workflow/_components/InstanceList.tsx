"use client";

import { useState } from "react";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  Ban,
  Clock,
  ChevronDown,
  ChevronRight,
  Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { workflowApi, WorkflowInstance } from "@/lib/api/workflow";
import { useToast } from "@/lib/hooks/useToast";

interface InstanceListProps {
  instances: WorkflowInstance[];
  onRefresh: () => void;
}

const STATUS_CONFIG: Record<string, { icon: any; color: string; label: string }> = {
  created:   { icon: Clock,        color: "text-slate-400",   label: "已创建" },
  running:   { icon: Loader2,      color: "text-blue-500",    label: "运行中" },
  paused:    { icon: Pause,        color: "text-amber-500",   label: "已暂停" },
  completed: { icon: CheckCircle2, color: "text-emerald-500", label: "已完成" },
  failed:    { icon: XCircle,      color: "text-red-500",     label: "失败" },
  cancelled: { icon: Ban,          color: "text-slate-400",   label: "已取消" },
};

export function InstanceList({ instances, onRefresh }: InstanceListProps) {
  const toast = useToast();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleAction = async (id: string, action: string) => {
    try {
      if (action === "pause") await workflowApi.pauseInstance(id);
      else if (action === "resume") await workflowApi.resumeInstance(id);
      else if (action === "cancel") await workflowApi.cancelInstance(id);
      else if (action === "retry") await workflowApi.retryInstance(id);
      else if (action === "rerun") await workflowApi.rerunInstance(id);
      toast.success("操作成功", `${action} 已执行`);
      onRefresh();
    } catch (e) {
      toast.error("操作失败", e instanceof Error ? e.message : "未知错误");
    }
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return "-";
    if (seconds < 60) return `${Math.round(seconds)}s`;
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  };

  if (instances.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-slate-500">
        <Layers className="w-12 h-12 mb-4 opacity-30" />
        <p className="text-sm font-medium">暂无执行记录</p>
        <p className="text-xs mt-1">从模板页面启动工作流</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto p-6">
      <div className="space-y-3">
        {instances.map((inst) => {
          const cfg = STATUS_CONFIG[inst.status] || STATUS_CONFIG.created;
          const StatusIcon = cfg.icon;
          const isExpanded = expandedId === inst.id;
          const isRunning = inst.status === "running";
          const isPaused = inst.status === "paused";
          const isFailed = inst.status === "failed";
          const isDone = inst.status === "completed" || inst.status === "cancelled";

          return (
            <div key={inst.id} className="rounded-xl border border-slate-200 dark:border-white/5 bg-white dark:bg-slate-900/50 overflow-hidden">
              {/* Instance Header */}
              <div
                onClick={() => setExpandedId(isExpanded ? null : inst.id)}
                className="flex items-center gap-3 p-4 cursor-pointer hover:bg-slate-50 dark:hover:bg-white/5 transition-colors"
              >
                <StatusIcon className={cn("w-4 h-4 shrink-0", cfg.color, isRunning && "animate-spin")} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-800 dark:text-white truncate">{inst.workflow_name}</span>
                    <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full", {
                      "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400": isRunning,
                      "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400": isPaused,
                      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400": inst.status === "completed",
                      "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400": isFailed,
                      "bg-slate-100 text-slate-500 dark:bg-white/5 dark:text-slate-400": inst.status === "created" || inst.status === "cancelled",
                    })}>
                      {cfg.label}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-[10px] text-slate-400">
                    {inst.created_at && <span>{new Date(inst.created_at).toLocaleString("zh-CN")}</span>}
                    <span>耗时 {formatDuration(inst.duration)}</span>
                    <span>{inst.step_runs.length} 步骤</span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                  {isRunning && (
                    <button onClick={() => handleAction(inst.id, "pause")} className="p-1.5 rounded-lg hover:bg-amber-100 dark:hover:bg-amber-500/10 text-amber-600 transition-colors" title="暂停">
                      <Pause className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {isPaused && (
                    <button onClick={() => handleAction(inst.id, "resume")} className="p-1.5 rounded-lg hover:bg-blue-100 dark:hover:bg-blue-500/10 text-blue-600 transition-colors" title="恢复">
                      <Play className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {(isRunning || isPaused) && (
                    <button onClick={() => handleAction(inst.id, "cancel")} className="p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-500/10 text-red-500 transition-colors" title="取消">
                      <Ban className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {isFailed && (
                    <button onClick={() => handleAction(inst.id, "retry")} className="p-1.5 rounded-lg hover:bg-orange-100 dark:hover:bg-orange-500/10 text-orange-600 transition-colors" title="重试">
                      <RotateCcw className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {isDone && (
                    <button onClick={() => handleAction(inst.id, "rerun")} className="p-1.5 rounded-lg hover:bg-blue-100 dark:hover:bg-blue-500/10 text-blue-600 transition-colors" title="重新执行">
                      <Play className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-300" /> : <ChevronRight className="w-4 h-4 text-slate-300" />}
              </div>

              {/* Step Runs (Expanded) */}
              {isExpanded && inst.step_runs.length > 0 && (
                <div className="border-t border-slate-100 dark:border-white/5 px-4 py-3 bg-slate-50/50 dark:bg-black/10">
                  <div className="space-y-2">
                    {inst.step_runs.map((sr, idx) => {
                      const stepCfg = STATUS_CONFIG[sr.status] || STATUS_CONFIG.created;
                      const StepIcon = stepCfg.icon;
                      return (
                        <div key={sr.step_id} className="flex items-center gap-3 py-1.5">
                          <div className="w-5 h-5 rounded-full bg-slate-100 dark:bg-white/5 flex items-center justify-center text-[10px] font-mono text-slate-400">
                            {idx + 1}
                          </div>
                          <StepIcon className={cn("w-3.5 h-3.5 shrink-0", stepCfg.color, sr.status === "running" && "animate-spin")} />
                          <span className="text-xs font-medium text-slate-700 dark:text-slate-300 flex-1 truncate">{sr.step_name}</span>
                          <span className="text-[10px] text-slate-400">{formatDuration(sr.duration)}</span>
                          {sr.error && (
                            <span className="text-[10px] text-red-500 truncate max-w-[200px]" title={sr.error}>{sr.error}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Error Display */}
              {isExpanded && inst.error && (
                <div className="border-t border-red-100 dark:border-red-500/10 px-4 py-3 bg-red-50/50 dark:bg-red-500/5">
                  <p className="text-xs text-red-600 dark:text-red-400 font-mono">{inst.error}</p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
