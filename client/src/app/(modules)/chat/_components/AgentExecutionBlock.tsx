"use client";

import { useMemo } from "react";
import {
  CheckCircle2, XCircle, Loader2, Circle, SkipForward,
  PauseCircle, Play, X, ChevronDown, ChevronUp,
  Clock, AlertTriangle, FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/stores/runStore";
import { useTaskStore } from "@/stores/taskStore";
import { useChatStore } from "@/stores/chatStore";
import { cancelTask, pauseTask, resumeTask } from "@/lib/api/task";
import type { RunStep, RunStatus } from "@/types/run";
import { ApprovalCard } from "./ApprovalCard";

// ---------------------------------------------------------------------------
// Status config
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<RunStatus, { label: string; color: string; dotColor: string }> = {
  planning:  { label: "正在规划",   color: "text-indigo-500", dotColor: "bg-indigo-500" },
  executing: { label: "执行中",     color: "text-indigo-500", dotColor: "bg-indigo-500" },
  paused:    { label: "已暂停",     color: "text-amber-500",  dotColor: "bg-amber-500" },
  completed: { label: "执行完成",   color: "text-green-500",  dotColor: "bg-green-500" },
  failed:    { label: "执行失败",   color: "text-red-500",    dotColor: "bg-red-500" },
  cancelled: { label: "已取消",     color: "text-slate-400",  dotColor: "bg-slate-400" },
};

// ---------------------------------------------------------------------------
// Step icon
// ---------------------------------------------------------------------------

function StepStatusIcon({ status }: { status: RunStep["status"] }) {
  switch (status) {
    case "completed": return <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />;
    case "failed":    return <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />;
    case "running":   return <Loader2 className="w-3.5 h-3.5 text-indigo-500 shrink-0 animate-spin" />;
    case "skipped":   return <SkipForward className="w-3.5 h-3.5 text-slate-400 shrink-0" />;
    default:          return <Circle className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 shrink-0" />;
  }
}

// ---------------------------------------------------------------------------
// Single step row
// ---------------------------------------------------------------------------

function StepRow({ step, index, total, isExpanded, onToggle }: {
  step: RunStep; index: number; total: number;
  isExpanded: boolean; onToggle: () => void;
}) {
  const title = step.title || step.description || step.step_name;
  const hasDetail = !!(step.output_summary || step.output_detail || step.details || step.summary);
  const isTerminal = step.status === "completed" || step.status === "failed" || step.status === "skipped";

  return (
    <div className="group">
      <div
        className={cn(
          "flex items-start gap-2 px-2 py-1.5 rounded-lg transition-colors",
          hasDetail && "cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800/50",
        )}
        onClick={hasDetail ? onToggle : undefined}
      >
        {/* Timeline connector */}
        <div className="flex flex-col items-center pt-0.5">
          <StepStatusIcon status={step.status} />
          {index < total - 1 && (
            <div className={cn(
              "w-px flex-1 mt-1 min-h-[8px]",
              isTerminal ? "bg-slate-200 dark:bg-slate-700" : "bg-indigo-200 dark:bg-indigo-800",
            )} />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 pb-1">
          <div className="flex items-center gap-2">
            <span className={cn(
              "text-xs leading-snug",
              step.status === "running" ? "text-indigo-700 dark:text-indigo-300 font-medium" :
              step.status === "failed" ? "text-red-600 dark:text-red-400 font-medium" :
              step.status === "pending" ? "text-slate-400 dark:text-slate-500" :
              "text-slate-600 dark:text-slate-300",
            )}>
              {step.status === "running" ? `步骤 ${index + 1}/${total}: ${title}` : title}
            </span>
            {step.status === "completed" && step.output_summary && (
              <span className="text-[10px] text-slate-400 truncate max-w-[200px]">
                — {step.output_summary}
              </span>
            )}
            {hasDetail && (
              <span className="ml-auto shrink-0 text-slate-400">
                {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              </span>
            )}
          </div>

          {/* Failed step: always show error */}
          {step.status === "failed" && (step.output_detail || step.details) && (
            <div className="mt-1 text-[11px] text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-950/20 rounded px-2 py-1 font-mono whitespace-pre-wrap break-all max-h-24 overflow-auto">
              {step.output_detail || step.details}
            </div>
          )}

          {/* Expanded detail */}
          {isExpanded && step.status !== "failed" && (
            <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/50 rounded px-2 py-1.5 font-mono whitespace-pre-wrap break-all max-h-40 overflow-auto">
              {step.output_detail || step.details || step.summary || step.output_summary}
            </div>
          )}

          {/* Artifacts */}
          {step.artifacts && step.artifacts.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {step.artifacts.map((a, j) => (
                <span key={j} className="inline-flex items-center gap-1 text-[10px] font-mono text-indigo-500 bg-indigo-50 dark:bg-indigo-950/30 px-1.5 py-0.5 rounded">
                  <FileText className="w-2.5 h-2.5" />
                  {a.split(/[/\\]/).pop()}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline approval section
// ---------------------------------------------------------------------------

function InlineApprovals({ runId }: { runId: string }) {
  const pendingApprovals = useTaskStore((s) => s.pendingApprovals);
  const messages = useChatStore((s) => s.messages);

  // Pending approvals for this run
  const runApprovals = useMemo(
    () => pendingApprovals.filter((a) => !a.task_id || a.task_id === runId),
    [pendingApprovals, runId],
  );

  // Resolved approval messages for this run
  const resolvedApprovals = useMemo(
    () => messages.filter(
      (m) => (m.kind === "approval" || m.messageType === "approval")
        && m.approvalRequest
        && m.approvalStatus !== "pending"
        && m.approvalStatus !== "submitting"
    ),
    [messages],
  );

  if (runApprovals.length === 0 && resolvedApprovals.length === 0) return null;

  return (
    <div className="space-y-1.5 px-1">
      {/* Resolved approvals — compact */}
      {resolvedApprovals.map((m) => (
        <ApprovalCard
          key={m.id}
          messageId={m.id}
          request={m.approvalRequest!}
          status={m.approvalStatus ?? "pending"}
          comment={m.approvalComment}
        />
      ))}
      {/* Pending approvals — full interactive */}
      {runApprovals.map((req) => {
        const msg = messages.find(
          (m) => m.approvalRequest?.request_id === req.request_id,
        );
        return (
          <ApprovalCard
            key={req.request_id}
            messageId={msg?.id ?? `approval-${req.request_id}`}
            request={req}
            status={msg?.approvalStatus ?? "pending"}
            comment={msg?.approvalComment}
          />
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Completion summary (inline)
// ---------------------------------------------------------------------------

function InlineSummary({ run }: { run: { steps: RunStep[]; status: RunStatus; goal: string; startedAt: string; completedAt?: string } }) {
  const { status, steps } = run;
  if (status !== "completed" && status !== "failed" && status !== "cancelled") return null;

  const completed = steps.filter((s) => s.status === "completed").length;
  const failed = steps.filter((s) => s.status === "failed").length;
  const total = steps.length;
  const durationMs = run.completedAt
    ? new Date(run.completedAt).getTime() - new Date(run.startedAt).getTime()
    : 0;
  const durationSec = durationMs > 0 ? (durationMs / 1000).toFixed(1) : null;

  const failedSteps = steps.filter((s) => s.status === "failed");

  return (
    <div className={cn(
      "mt-1 rounded-lg border px-3 py-2 text-xs",
      status === "completed"
        ? "border-green-200 dark:border-green-800/40 bg-green-50/50 dark:bg-green-950/10"
        : status === "failed"
        ? "border-red-200 dark:border-red-800/40 bg-red-50/50 dark:bg-red-950/10"
        : "border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-900/30",
    )}>
      <div className="flex items-center gap-2">
        {status === "completed" && <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />}
        {status === "failed" && <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />}
        {status === "cancelled" && <X className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
        <span className={cn(
          "font-medium",
          status === "completed" ? "text-green-600 dark:text-green-400" :
          status === "failed" ? "text-red-600 dark:text-red-400" :
          "text-slate-500",
        )}>
          {status === "completed" ? "执行完成" : status === "failed" ? "执行失败" : "已取消"}
        </span>
        <span className="text-slate-400 font-mono ml-auto flex items-center gap-2">
          {total > 0 && <span>{completed}/{total} 步完成</span>}
          {failed > 0 && <span className="text-red-400">{failed} 步失败</span>}
          {durationSec && (
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />{durationSec}s
            </span>
          )}
        </span>
      </div>

      {/* Show failed step details */}
      {failedSteps.length > 0 && (
        <div className="mt-2 space-y-1">
          {failedSteps.map((s) => (
            <div key={s.id} className="flex items-start gap-1.5 text-red-500 dark:text-red-400">
              <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
              <div className="min-w-0">
                <span className="font-medium">{s.title || s.description || s.step_name}</span>
                {(s.output_detail || s.details) && (
                  <p className="text-[10px] font-mono text-red-400 dark:text-red-500 mt-0.5 line-clamp-2">
                    {s.output_detail || s.details}
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

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface AgentExecutionBlockProps {
  runId: string;
}

export function AgentExecutionBlock({ runId }: AgentExecutionBlockProps) {
  const run = useRunStore((s) => s.runs[runId]);
  const expandedKeys = useRunStore((s) => s.expandedStepKeys);
  const toggleStep = useRunStore((s) => s.toggleStepExpanded);
  const { activeTask } = useTaskStore();

  if (!run) {
    return (
      <div className="flex items-center gap-2 py-2 text-xs text-slate-400">
        <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-500" />
        <span>正在分析任务...</span>
      </div>
    );
  }

  const { steps, status, goal } = run;
  const completedCount = steps.filter((s) => s.status === "completed").length;
  const totalCount = steps.length;
  const percent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
  const isActive = status === "executing" || status === "planning";
  const isPaused = status === "paused";
  const cfg = STATUS_CONFIG[status];

  // Task control — use the proper API
  const isCurrentTask = activeTask?.id === runId;

  const handlePause = async () => {
    if (!isCurrentTask || !activeTask) return;
    try { await pauseTask(activeTask.id); } catch (e) { console.error("pause failed", e); }
  };

  const handleResume = async () => {
    if (!isCurrentTask || !activeTask) return;
    try {
      await resumeTask(activeTask.id);
      useChatStore.getState().setCanCancel(true);
    } catch (e) { console.error("resume failed", e); }
  };

  const handleCancel = async () => {
    if (!isCurrentTask || !activeTask) return;
    try {
      await cancelTask(activeTask.id);
      useTaskStore.getState().setIsCancelling(true);
    } catch (e) { console.error("cancel failed", e); }
  };

  return (
    <div className="space-y-2 w-full">
      {/* ── Header: status + goal + controls ── */}
      <div className="flex items-center gap-2">
        {/* Status dot */}
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          {isActive && (
            <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", cfg.dotColor)} />
          )}
          <span className={cn("relative inline-flex rounded-full h-2.5 w-2.5", cfg.dotColor)} />
        </span>

        <span className={cn("text-xs font-medium", cfg.color)}>
          {cfg.label}
        </span>

        {totalCount > 0 && (
          <span className="text-[10px] font-mono text-slate-400">
            {completedCount}/{totalCount}
          </span>
        )}

        {/* Controls — right aligned */}
        <div className="ml-auto flex items-center gap-1">
          {isActive && isCurrentTask && (
            <>
              <button
                onClick={handlePause}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-slate-500 hover:text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950/30 transition-colors"
                title="暂停"
              >
                <PauseCircle className="w-3 h-3" />
                暂停
              </button>
              <button
                onClick={handleCancel}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-slate-500 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                title="取消"
              >
                <X className="w-3 h-3" />
                取消
              </button>
            </>
          )}
          {isPaused && isCurrentTask && (
            <>
              <button
                onClick={handleResume}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-indigo-500 hover:bg-indigo-50 dark:hover:bg-indigo-950/30 transition-colors"
                title="继续执行"
              >
                <Play className="w-3 h-3" />
                继续
              </button>
              <button
                onClick={handleCancel}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-slate-500 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                title="放弃"
              >
                <X className="w-3 h-3" />
                放弃
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── Goal text ── */}
      {goal && (
        <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed px-0.5">
          {goal}
        </p>
      )}

      {/* ── Progress bar ── */}
      {totalCount > 0 && (
        <div className="h-1 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all duration-500",
              status === "completed" ? "bg-green-500" :
              status === "failed" ? "bg-red-500" :
              isPaused ? "bg-amber-500" : "bg-indigo-500"
            )}
            style={{ width: `${percent}%` }}
          />
        </div>
      )}

      {/* ── Planning state ── */}
      {status === "planning" && steps.length === 0 && (
        <div className="flex items-center gap-2 text-xs text-slate-400 px-1 py-1">
          <Loader2 className="w-3 h-3 animate-spin text-indigo-400" />
          <span>正在分析需求，规划执行步骤...</span>
        </div>
      )}

      {/* ── Step list ── */}
      {steps.length > 0 && (
        <div className="space-y-0">
          {steps.map((step, i) => (
            <StepRow
              key={step.id}
              step={step}
              index={i}
              total={steps.length}
              isExpanded={expandedKeys.has(`${runId}:${step.id}`)}
              onToggle={() => toggleStep(runId, step.id)}
            />
          ))}
        </div>
      )}

      {/* ── Inline approvals ── */}
      <InlineApprovals runId={runId} />

      {/* ── Inline summary (terminal states) ── */}
      <InlineSummary run={run} />
    </div>
  );
}
