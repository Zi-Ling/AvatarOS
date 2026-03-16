"use client";

import {
  CheckCircle2, XCircle, Loader2, Circle, ChevronDown, ChevronRight,
  SkipForward, Zap, PauseCircle, Play, ShieldAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/stores/runStore";
import { useTaskStore } from "@/stores/taskStore";
import { useChatStore } from "@/stores/chatStore";
import { getSocket } from "@/lib/socket";
import type { RunStep, RunStatus } from "@/types/run";

interface AgentExecutionBlockProps {
  runId: string;
}

const StepStatusIcon = ({ status }: { status: RunStep["status"] }) => {
  switch (status) {
    case "completed": return <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />;
    case "failed":    return <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />;
    case "running":   return <Loader2 className="w-3.5 h-3.5 text-indigo-500 shrink-0 animate-spin" />;
    case "skipped":   return <SkipForward className="w-3.5 h-3.5 text-slate-400 shrink-0" />;
    default:          return <Circle className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 shrink-0" />;
  }
};

const statusLabel: Record<RunStatus, string> = {
  planning: "规划中", executing: "执行中", paused: "已暂停",
  completed: "已完成", failed: "执行失败", cancelled: "已取消",
};

const statusColor: Record<RunStatus, string> = {
  planning: "text-indigo-500", executing: "text-indigo-500", paused: "text-amber-500",
  completed: "text-green-500", failed: "text-red-500", cancelled: "text-slate-400",
};

export function AgentExecutionBlock({ runId }: AgentExecutionBlockProps) {
  const { runs, expandedStepKeys, toggleStepExpanded, updateRunStatus } = useRunStore();
  const { setControlStatus, pendingApprovals } = useTaskStore();
  const run = runs[runId];

  if (!run) {
    return (
      <div className="flex items-center gap-2 py-2 text-xs text-slate-400">
        <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-500" />
        <span>正在规划任务...</span>
      </div>
    );
  }

  const { steps, status } = run;
  const completedCount = steps.filter((s) => s.status === "completed").length;
  const totalCount = steps.length;
  const percent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
  const isActive = status === "executing" || status === "planning";
  const isPaused = status === "paused";

  // Approvals that belong to this run
  const runApprovals = pendingApprovals.filter((a) => !a.task_id || a.task_id === runId);
  const hasPendingApproval = runApprovals.length > 0;

  const handlePause = () => {
    const { sessionId } = useChatStore.getState();
    if (!sessionId) return;
    const socket = getSocket();
    socket.emit("cancel_task", { session_id: sessionId, task_id: runId });
    setControlStatus("paused");
  };

  const handleResume = () => {
    const { sessionId } = useChatStore.getState();
    if (!sessionId) return;
    const socket = getSocket();
    socket.emit("resume_task", { session_id: sessionId, task_id: runId });
    setControlStatus("running");
    updateRunStatus(runId, "executing");
    useChatStore.getState().setCanCancel(true);
  };

  return (
    <div className="space-y-2 w-full">
      {/* Header row */}
      <div className="flex items-center gap-2">
        {isActive ? (
          <Loader2 className="w-3.5 h-3.5 text-indigo-500 animate-spin shrink-0" />
        ) : (
          <Zap className={cn("w-3.5 h-3.5 shrink-0", statusColor[status])} />
        )}
        <span className={cn("text-xs font-medium", statusColor[status])}>
          {statusLabel[status]}
        </span>

        {/* Pending approval anchor */}
        {hasPendingApproval && (
          <span className="flex items-center gap-1 text-[10px] text-amber-500 font-medium ml-1">
            <ShieldAlert className="w-3 h-3" />
            待审批
          </span>
        )}

        {totalCount > 0 && (
          <span className="text-[10px] font-mono text-slate-400 ml-auto shrink-0">
            {completedCount}/{totalCount}
          </span>
        )}

        {/* Inline pause/resume controls */}
        {isActive && (
          <button
            onClick={handlePause}
            className="ml-1 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-slate-500 hover:text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950/30 transition-colors"
            title="暂停任务"
          >
            <PauseCircle className="w-3 h-3" />
          </button>
        )}
        {isPaused && (
          <button
            onClick={handleResume}
            className="ml-1 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-indigo-500 hover:bg-indigo-50 dark:hover:bg-indigo-950/30 transition-colors"
            title="继续执行"
          >
            <Play className="w-3 h-3" />
            继续
          </button>
        )}
      </div>

      {/* Progress bar */}
      {totalCount > 0 && (
        <div className="h-1 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all duration-500",
              status === "completed" ? "bg-green-500" :
              status === "failed" ? "bg-red-500" :
              status === "paused" ? "bg-amber-500" : "bg-indigo-500"
            )}
            style={{ width: `${percent}%` }}
          />
        </div>
      )}

      {/* Step list */}
      {steps.length > 0 && (
        <div className="space-y-0.5 mt-1">
          {steps.map((step) => {
            const key = `${runId}:${step.id}`;
            const isExpanded = expandedStepKeys.has(key);
            // 新字段优先，兼容旧字段
            const stepSummary = step.summary || step.output_summary;
            const stepDetails = step.details || step.output_detail;
            const stepTitle = step.title || step.description || step.step_name;
            const hasDetail = !!(stepDetails || stepSummary || step.description);
            const isRunning = step.status === "running";

            return (
              <div key={step.id} className={cn(
                "rounded-lg border transition-colors",
                isRunning
                  ? "border-indigo-200 dark:border-indigo-800/50 bg-indigo-50/50 dark:bg-indigo-950/20"
                  : step.status === "failed"
                  ? "border-red-200 dark:border-red-800/30 bg-red-50/30 dark:bg-red-950/10"
                  : "border-transparent bg-transparent hover:bg-slate-50 dark:hover:bg-slate-800/30"
              )}>
                <div
                  className={cn("flex items-center gap-2 px-2 py-1.5",
                    hasDetail ? "cursor-pointer" : "cursor-default"
                  )}
                  onClick={() => hasDetail && toggleStepExpanded(runId, step.id)}
                >
                  <StepStatusIcon status={step.status} />
                  <span className={cn(
                    "flex-1 text-xs truncate",
                    step.status === "pending" ? "text-slate-400 dark:text-slate-500" :
                    step.status === "running" ? "text-indigo-700 dark:text-indigo-300 font-medium" :
                    step.status === "failed" ? "text-red-600 dark:text-red-400" :
                    "text-slate-600 dark:text-slate-300"
                  )}>
                    {stepTitle}
                  </span>
                  {!isExpanded && stepSummary && step.status === "completed" && (
                    <span className="text-[10px] text-slate-400 truncate max-w-[120px] shrink-0">
                      {stepSummary}
                    </span>
                  )}
                  {hasDetail && (
                    isExpanded
                      ? <ChevronDown className="w-3 h-3 text-slate-400 shrink-0" />
                      : <ChevronRight className="w-3 h-3 text-slate-400 shrink-0" />
                  )}
                </div>

                {isExpanded && hasDetail && (
                  <div className="px-2 pb-2 pt-0">
                    <div className="rounded-md bg-slate-100 dark:bg-slate-900/60 p-2 text-[11px] text-slate-600 dark:text-slate-400 font-mono whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                      {stepDetails || stepSummary || step.description}
                    </div>
                    {/* artifacts 列表 */}
                    {step.artifacts && step.artifacts.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {step.artifacts.map((a, i) => (
                          <span key={i} className="text-[10px] font-mono text-indigo-500 bg-indigo-50 dark:bg-indigo-950/30 px-1.5 py-0.5 rounded truncate max-w-[200px]">
                            {a.split(/[\\/]/).pop()}
                          </span>
                        ))}
                      </div>
                    )}
                    {/* 时间戳 */}
                    {(step.startedAt || step.endedAt) && (
                      <div className="mt-1 flex gap-2 text-[10px] text-slate-400 font-mono">
                        {step.startedAt && <span>开始 {new Date(step.startedAt).toLocaleTimeString()}</span>}
                        {step.endedAt && <span>结束 {new Date(step.endedAt).toLocaleTimeString()}</span>}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {steps.length === 0 && isActive && (
        <div className="flex items-center gap-2 text-xs text-slate-400 px-1">
          <Loader2 className="w-3 h-3 animate-spin text-indigo-400" />
          <span>正在规划步骤...</span>
        </div>
      )}
    </div>
  );
}
