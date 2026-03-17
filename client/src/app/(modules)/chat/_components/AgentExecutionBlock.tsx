"use client";

import {
  CheckCircle2, XCircle, Loader2, Circle,
  SkipForward, Zap, PauseCircle, Play, ShieldAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/stores/runStore";
import { useTaskStore } from "@/stores/taskStore";
import { useChatStore } from "@/stores/chatStore";
import { getSocket } from "@/lib/socket";
import type { RunStep, RunStatus } from "@/types/run";
import { PhaseIndicator } from "@/components/ui/PhaseIndicator";
import { StepTimeline } from "@/components/ui/StepTimeline";

interface AgentExecutionBlockProps {
  runId: string;
}

const statusLabel: Record<RunStatus, string> = {
  planning: "规划中", executing: "执行中", paused: "已暂停",
  completed: "已完成", failed: "执行失败", cancelled: "已取消",
};

const statusColor: Record<RunStatus, string> = {
  planning: "text-indigo-500", executing: "text-indigo-500", paused: "text-amber-500",
  completed: "text-green-500", failed: "text-red-500", cancelled: "text-slate-400",
};

// ---------------------------------------------------------------------------
// Legacy step list — fallback when narrative layer has no data
// ---------------------------------------------------------------------------

const LegacyStepIcon = ({ status }: { status: RunStep["status"] }) => {
  switch (status) {
    case "completed": return <CheckCircle2 className="w-3 h-3 text-green-500 shrink-0" />;
    case "failed":    return <XCircle className="w-3 h-3 text-red-500 shrink-0" />;
    case "running":   return <Loader2 className="w-3 h-3 text-indigo-500 shrink-0 animate-spin" />;
    case "skipped":   return <SkipForward className="w-3 h-3 text-slate-400 shrink-0" />;
    default:          return <Circle className="w-3 h-3 text-slate-300 dark:text-slate-600 shrink-0" />;
  }
};

function LegacyStepList({ steps }: { steps: RunStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="space-y-0.5">
      {steps.map((step) => {
        const title = step.title || step.description || step.step_name;
        return (
          <div key={step.id} className="flex items-center gap-2 px-1 py-1 text-xs">
            <LegacyStepIcon status={step.status} />
            <span className={cn(
              "truncate",
              step.status === "running" ? "text-indigo-700 dark:text-indigo-300 font-medium" :
              step.status === "failed" ? "text-red-600 dark:text-red-400" :
              step.status === "pending" ? "text-slate-400" :
              "text-slate-600 dark:text-slate-300"
            )}>
              {title}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AgentExecutionBlock({ runId }: AgentExecutionBlockProps) {
  const run = useRunStore((s) => s.runs[runId]);
  const hasNarrative = useRunStore((s) => {
    const ns = s.narrativeStates[runId];
    return !!ns && Object.keys(ns.stepViews).length > 0;
  });
  const { setControlStatus, pendingApprovals } = useTaskStore();

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
  const runApprovals = pendingApprovals.filter((a) => !a.task_id || a.task_id === runId);
  const hasPendingApproval = runApprovals.length > 0;

  const handlePause = () => {
    const { sessionId } = useChatStore.getState();
    if (!sessionId) return;
    getSocket().emit("cancel_task", { session_id: sessionId, task_id: runId });
    setControlStatus("paused");
  };

  const handleResume = () => {
    const { sessionId } = useChatStore.getState();
    if (!sessionId) return;
    getSocket().emit("resume_task", { session_id: sessionId, task_id: runId });
    setControlStatus("running");
    useRunStore.getState().updateRunStatus(runId, "executing");
    useChatStore.getState().setCanCancel(true);
  };

  return (
    <div className="space-y-1.5 w-full">
      {/* ── Header: status + controls ── */}
      <div className="flex items-center gap-2">
        {isActive ? (
          <Loader2 className="w-3.5 h-3.5 text-indigo-500 animate-spin shrink-0" />
        ) : (
          <Zap className={cn("w-3.5 h-3.5 shrink-0", statusColor[status])} />
        )}
        <span className={cn("text-xs font-medium", statusColor[status])}>
          {statusLabel[status]}
        </span>

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

      {/* ── Progress bar ── */}
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

      {/* ── Narrative layer (primary view when available) ── */}
      {hasNarrative ? (
        <>
          {isActive && <PhaseIndicator runId={runId} />}
          <StepTimeline runId={runId} />
        </>
      ) : (
        <>
          {/* ── Legacy fallback ── */}
          {steps.length > 0 && <LegacyStepList steps={steps} />}
          {steps.length === 0 && isActive && (
            <div className="flex items-center gap-2 text-xs text-slate-400 px-1">
              <Loader2 className="w-3 h-3 animate-spin text-indigo-400" />
              <span>正在规划步骤...</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
