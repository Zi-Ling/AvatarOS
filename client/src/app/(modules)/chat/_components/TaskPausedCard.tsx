"use client";

import { PauseCircle, Play, XCircle } from "lucide-react";
import { getSocket } from "@/lib/socket";
import { useChatStore } from "@/stores/chatStore";
import { useTaskStore } from "@/stores/taskStore";
import { useRunStore } from "@/stores/runStore";

interface TaskPausedCardProps {
  /** The specific run this paused card belongs to */
  runId?: string;
  pausedAtStep?: number;
  pausedTotalSteps?: number;
}

export function TaskPausedCard({ runId, pausedAtStep, pausedTotalSteps }: TaskPausedCardProps) {
  const { setControlStatus, setIsCancelling } = useTaskStore();
  const { runs, updateRunStatus } = useRunStore();

  // Resolve task id: prefer runId → fall back to activeTask for legacy messages
  const resolveTaskId = (): string | null => {
    if (runId) {
      // runId IS the taskId in our model
      return runId;
    }
    return useTaskStore.getState().activeTask?.id ?? null;
  };

  const handleResume = () => {
    const sessionId = useChatStore.getState().sessionId;
    const taskId = resolveTaskId();
    if (!taskId || !sessionId) return;

    const socket = getSocket();
    socket.emit("resume_task", { session_id: sessionId, task_id: taskId });
    setControlStatus("running");
    if (runId) updateRunStatus(runId, "executing");
    useChatStore.getState().setCanCancel(true);
  };

  const handleAbandon = () => {
    const sessionId = useChatStore.getState().sessionId;
    const taskId = resolveTaskId();
    if (!taskId || !sessionId) return;

    const socket = getSocket();
    socket.emit("cancel_task", { session_id: sessionId, task_id: taskId });
    setIsCancelling(true);
  };

  // Use live run data if available, fall back to snapshot props
  const run = runId ? runs[runId] : null;
  const liveCompleted = run ? run.steps.filter((s) => s.status === "completed").length : undefined;
  const liveTotal = run ? run.steps.length : undefined;
  const displayCompleted = liveCompleted ?? pausedAtStep;
  const displayTotal = liveTotal ?? pausedTotalSteps;
  const stepInfo = displayCompleted !== undefined && displayTotal !== undefined
    ? `已完成 ${displayCompleted}/${displayTotal} 步`
    : null;

  return (
    <div className="mt-2 rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-950/20 p-3 space-y-3">
      <div className="flex items-center gap-2">
        <PauseCircle className="w-4 h-4 text-amber-500 shrink-0" />
        <span className="text-xs font-semibold text-amber-600 dark:text-amber-400">任务已暂停</span>
        {stepInfo && (
          <span className="ml-auto text-[10px] font-mono text-amber-500/70">{stepInfo}</span>
        )}
      </div>
      <p className="text-xs text-slate-600 dark:text-slate-400">
        任务已停止，你可以继续执行或放弃本次任务。
      </p>
      <div className="flex gap-2">
        <button
          onClick={handleAbandon}
          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs font-medium rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
        >
          <XCircle className="w-3.5 h-3.5" />
          放弃任务
        </button>
        <button
          onClick={handleResume}
          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs font-medium rounded-lg bg-indigo-500 text-white hover:bg-indigo-600 transition-colors"
        >
          <Play className="w-3.5 h-3.5" />
          继续执行
        </button>
      </div>
    </div>
  );
}
