"use client";

import { useMemo, useState } from "react";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  RotateCw,
  Clock,
  SkipForward,
  Circle,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/stores/runStore";
import { TechDetailPanel } from "@/components/ui/TechDetailPanel";
import { ArtifactPreview } from "@/components/ui/ArtifactPreview";
import type { NarrativeStepView, NarrativeStepStatus, ArtifactMeta } from "@/types/narrative";

interface StepTimelineProps {
  runId: string;
  /** When true, timeline starts expanded (used in Workbench detailed view) */
  defaultExpanded?: boolean;
}

/** Format duration_ms to human-readable string */
function formatDuration(ms: number | null): string | null {
  if (ms == null || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  const secs = ms / 1000;
  if (secs < 60) return `${secs.toFixed(1)}s`;
  const mins = Math.floor(secs / 60);
  const remainSecs = Math.round(secs % 60);
  return remainSecs > 0 ? `${mins}m ${remainSecs}s` : `${mins}m`;
}

const STATUS_ICON_MAP: Record<
  NarrativeStepStatus,
  { icon: typeof CheckCircle2; className: string }
> = {
  completed: { icon: CheckCircle2, className: "text-green-500" },
  running:   { icon: Loader2,     className: "text-indigo-500 animate-spin" },
  failed:    { icon: XCircle,     className: "text-red-500" },
  retrying:  { icon: RotateCw,    className: "text-amber-500 animate-spin" },
  waiting:   { icon: Clock,       className: "text-amber-500" },
  skipped:   { icon: SkipForward, className: "text-slate-400" },
  pending:   { icon: Circle,      className: "text-slate-400" },
};

function StepStatusIcon({ status }: { status: NarrativeStepStatus }) {
  const config = STATUS_ICON_MAP[status] ?? STATUS_ICON_MAP.pending;
  const Icon = config.icon;
  return <Icon className={cn("w-3.5 h-3.5 shrink-0", config.className)} />;
}

function StepNode({
  step,
  runId,
  isDetailExpanded,
  onToggleDetail,
}: {
  step: NarrativeStepView;
  runId: string;
  isDetailExpanded: boolean;
  onToggleDetail: () => void;
}) {
  const isFailed = step.status === "failed";
  const isRetrying = step.status === "retrying";
  const isWaiting = step.status === "waiting";
  const isRunning = step.status === "running";
  const duration = formatDuration(step.duration_ms);

  return (
    <div
      className={cn(
        "rounded-md text-xs transition-colors",
        isFailed && "bg-red-50/50 dark:bg-red-950/10",
        isRunning && "bg-indigo-50/30 dark:bg-indigo-950/10",
      )}
    >
      <div
        className="flex items-start gap-2 px-2 py-1.5 cursor-pointer"
        onClick={onToggleDetail}
      >
        <div className="mt-0.5">
          <StepStatusIcon status={step.status} />
        </div>

        <div className="flex-1 min-w-0 space-y-0.5">
          {/* Title row */}
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "truncate font-medium",
                isFailed
                  ? "text-red-600 dark:text-red-400"
                  : isRunning
                    ? "text-indigo-700 dark:text-indigo-300"
                    : "text-slate-700 dark:text-slate-300",
              )}
            >
              {step.title}
            </span>

            {isRetrying && step.retry_count > 0 && (
              <span className="shrink-0 text-[10px] font-mono text-amber-500">
                重试 ×{step.retry_count}
              </span>
            )}

            {isWaiting && (
              <span className="shrink-0 text-[10px] font-medium text-amber-500">
                等待确认
              </span>
            )}

            {duration && (
              <span className="shrink-0 ml-auto text-[10px] font-mono text-slate-400">
                {duration}
              </span>
            )}
          </div>

          {/* Summary / failure reason */}
          {step.summary && (
            <p
              className={cn(
                "text-[11px] truncate",
                isFailed
                  ? "text-red-500/80 dark:text-red-400/70"
                  : "text-slate-500 dark:text-slate-400",
              )}
            >
              {step.summary}
            </p>
          )}

          {/* Blocking point marker for failed steps */}
          {isFailed && (
            <span className="inline-flex items-center gap-1 text-[10px] font-medium text-red-500 mt-0.5">
              <XCircle className="w-2.5 h-2.5" />
              阻塞点
            </span>
          )}

          {/* Feedback action marker */}
          {step.events.some((e) => e.event_type === "agent_feedback") && (() => {
            const fbEvent = step.events.find((e) => e.event_type === "agent_feedback");
            const action = fbEvent?.metadata?.action as string | undefined;
            if (!action || action === "NONE" || action === "") return null;
            const actionLabels: Record<string, { label: string; color: string }> = {
              RETRY_SEARCH: { label: "重试搜索", color: "text-amber-600" },
              RETRY_TASK: { label: "重试任务", color: "text-amber-600" },
              REPLAN_DOWNSTREAM: { label: "下游重规划", color: "text-blue-600" },
              ABORT_DOWNSTREAM: { label: "下游中止", color: "text-red-600" },
            };
            const info = actionLabels[action] || { label: action, color: "text-slate-500" };
            return (
              <span className={cn("inline-flex items-center gap-1 text-[10px] font-medium mt-0.5", info.color)}>
                <RotateCw className="w-2.5 h-2.5" />
                反馈: {info.label}
              </span>
            );
          })()}
        </div>
      </div>

      {/* Tech Detail Panel — secondary expand */}
      {isDetailExpanded && (
        <div className="px-2 pb-2">
          <TechDetailPanel runId={runId} stepId={step.step_id} />
        </div>
      )}

      {/* Artifact Preview — shown when step has artifacts */}
      {step.has_artifact && (() => {
        const artifactMetas: ArtifactMeta[] = step.events
          .filter((e) => e.event_type === "artifact_created")
          .map((e) => ({
            type: (e.metadata?.artifact_type as ArtifactMeta["type"]) ?? "file",
            label: (e.metadata?.artifact_label as string) ?? "产物",
            path: e.metadata?.artifact_path as string | undefined,
            preview_data: e.metadata?.preview_data,
          }));
        if (artifactMetas.length === 0) return null;
        return (
          <div className="px-2 pb-1.5">
            <ArtifactPreview runId={runId} stepId={step.step_id} artifacts={artifactMetas} />
          </div>
        );
      })()}
    </div>
  );
}

export function StepTimeline({ runId, defaultExpanded = false }: StepTimelineProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [expandedDetailId, setExpandedDetailId] = useState<string | null>(null);
  const stepViewsMap = useRunStore((s) => s.narrativeStates[runId]?.stepViews);

  // Derive sorted array via useMemo to keep stable reference
  const steps = useMemo(() => {
    if (!stepViewsMap) return [];
    return Object.values(stepViewsMap)
      .filter((sv) => sv.step_id !== "__run__")
      .sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime());
  }, [stepViewsMap]);

  if (steps.length === 0) return null;

  const completedCount = steps.filter((s) => s.status === "completed").length;
  const allCompleted = completedCount === steps.length;

  const summaryText = allCompleted
    ? `${steps.length} 个步骤已完成`
    : `${steps.length} 个步骤`;

  return (
    <div className="mt-1">
      {/* Toggle button */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors py-0.5"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 shrink-0" />
        )}
        <span>{summaryText}</span>
      </button>

      {/* Expanded timeline */}
      {expanded && (
        <div className="mt-1 space-y-0.5">
          {steps.map((step) => (
            <StepNode
              key={step.step_id}
              step={step}
              runId={runId}
              isDetailExpanded={expandedDetailId === step.step_id}
              onToggleDetail={() =>
                setExpandedDetailId((prev) =>
                  prev === step.step_id ? null : step.step_id,
                )
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
