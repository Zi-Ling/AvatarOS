"use client";

import { Clock, AlertTriangle, RotateCw, FileCode2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/stores/runStore";

interface TechDetailPanelProps {
  runId: string;
  stepId: string;
}

/** Extract basename from a file path */
function basename(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || path;
}

/** Format duration from two ISO timestamps */
function calcDuration(startedAt?: string, endedAt?: string): string | null {
  if (!startedAt) return null;
  const end = endedAt ? new Date(endedAt).getTime() : Date.now();
  const start = new Date(startedAt).getTime();
  const ms = end - start;
  if (ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  const secs = ms / 1000;
  if (secs < 60) return `${secs.toFixed(1)}s`;
  const mins = Math.floor(secs / 60);
  const remainSecs = Math.round(secs % 60);
  return remainSecs > 0 ? `${mins}m ${remainSecs}s` : `${mins}m`;
}

/** Truncate text to maxLen characters */
function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 3)}...`;
}

/** Summarize params object into a short string */
function summarizeParams(params: unknown): string | null {
  if (params == null) return null;
  if (typeof params === "string") return params;
  try {
    const str = JSON.stringify(params);
    return truncate(str, 120);
  } catch {
    return null;
  }
}

export function TechDetailPanel({ runId, stepId }: TechDetailPanelProps) {
  const step = useRunStore((s) => {
    const run = s.runs[runId];
    return run?.steps.find((st) => st.id === stepId) ?? null;
  });

  // Supplement retry_count from narrative StepView (RunStep doesn't carry it)
  const retryCount = useRunStore((s) => {
    const ns = s.narrativeStates[runId];
    return ns?.stepViews[stepId]?.retry_count ?? 0;
  });

  if (!step) return null;

  const duration = calcDuration(step.startedAt, step.endedAt ?? step.completedAt);
  const outputSummary = step.output_summary ?? step.summary ?? null;
  const truncatedOutput = outputSummary ? truncate(outputSummary, 200) : null;
  const paramsSummary = summarizeParams(step.params);
  const errorInfo =
    step.status === "failed" ? (step.details ?? step.output_detail ?? null) : null;
  const artifacts = step.artifacts ?? [];

  return (
    <div
      className={cn(
        "mt-1.5 rounded-md border border-slate-200 dark:border-slate-700/60",
        "bg-slate-100 dark:bg-slate-900/60",
        "font-mono text-[11px] leading-relaxed",
        "p-2.5 space-y-2",
      )}
    >
      {/* Skill name */}
      {step.skill_name && (
        <Row label="工具">
          <span className="text-indigo-600 dark:text-indigo-400">{step.skill_name}</span>
        </Row>
      )}

      {/* Input params summary */}
      {paramsSummary && (
        <Row label="输入">
          <code className="text-slate-600 dark:text-slate-300 break-all">{paramsSummary}</code>
        </Row>
      )}

      {/* Output summary (≤200 chars) */}
      {truncatedOutput && (
        <Row label="输出">
          <span className="text-slate-600 dark:text-slate-300">{truncatedOutput}</span>
        </Row>
      )}

      {/* Duration */}
      {duration && (
        <Row label="耗时">
          <span className="inline-flex items-center gap-1 text-slate-500">
            <Clock className="w-3 h-3" />
            {duration}
          </span>
        </Row>
      )}

      {/* Retry count */}
      {retryCount > 0 && (
        <Row label="重试">
          <span className="inline-flex items-center gap-1 text-amber-500">
            <RotateCw className="w-3 h-3" />
            {retryCount} 次
          </span>
        </Row>
      )}

      {/* Error info */}
      {errorInfo && (
        <Row label="错误">
          <span className="inline-flex items-start gap-1 text-red-500 dark:text-red-400">
            <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
            <span className="break-all">{truncate(errorInfo, 300)}</span>
          </span>
        </Row>
      )}

      {/* Artifact file paths */}
      {artifacts.length > 0 && (
        <Row label="产物">
          <div className="flex flex-wrap gap-1">
            {artifacts.map((filePath) => (
              <span
                key={filePath}
                title={filePath}
                className={cn(
                  "inline-flex items-center gap-1 px-1.5 py-0.5 rounded",
                  "bg-slate-200/80 dark:bg-slate-700/60",
                  "text-[10px] text-slate-600 dark:text-slate-300",
                  "border border-slate-300/50 dark:border-slate-600/50",
                )}
              >
                <FileCode2 className="w-2.5 h-2.5 shrink-0" />
                {basename(filePath)}
              </span>
            ))}
          </div>
        </Row>
      )}
    </div>
  );
}

/** Label-value row helper */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="shrink-0 w-8 text-slate-400 dark:text-slate-500 text-right select-none">
        {label}
      </span>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}
