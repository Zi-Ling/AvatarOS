"use client";

import { useMemo } from "react";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Circle,
  GitBranch,
  ArrowDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/stores/runStore";

interface SubtaskProgressProps {
  runId: string;
}

type SubtaskStatus = "pending" | "running" | "completed" | "failed";

const STATUS_CONFIG: Record<SubtaskStatus, { icon: typeof Circle; color: string; bg: string; dot: string }> = {
  pending:   { icon: Circle,       color: "text-slate-400",  bg: "bg-slate-100 dark:bg-slate-800",       dot: "bg-slate-300" },
  running:   { icon: Loader2,      color: "text-indigo-500", bg: "bg-indigo-50 dark:bg-indigo-950/20",   dot: "bg-indigo-500" },
  completed: { icon: CheckCircle2, color: "text-green-500",  bg: "bg-green-50 dark:bg-green-950/20",     dot: "bg-green-500" },
  failed:    { icon: XCircle,      color: "text-red-500",    bg: "bg-red-50 dark:bg-red-950/20",         dot: "bg-red-500" },
};

interface Subtask {
  id: string;
  name: string;
  description?: string;
  status: SubtaskStatus;
  role?: string;
  depends_on?: string[];
  order: number;
}

/** Group subtasks into parallel layers based on dependencies. */
function buildLayers(subtasks: Subtask[]): Subtask[][] {
  const byId = new Map(subtasks.map((s) => [s.id, s]));
  const placed = new Set<string>();
  const layers: Subtask[][] = [];

  // Check if any subtask has depends_on info
  const hasDeps = subtasks.some((s) => s.depends_on && s.depends_on.length > 0);
  if (!hasDeps) {
    // No dependency info — single layer (flat)
    return [subtasks];
  }

  // Topological layering
  for (let safety = 0; safety < subtasks.length + 1; safety++) {
    const layer: Subtask[] = [];
    for (const st of subtasks) {
      if (placed.has(st.id)) continue;
      const deps = st.depends_on || [];
      if (deps.every((d) => placed.has(d) || !byId.has(d))) {
        layer.push(st);
      }
    }
    if (layer.length === 0) break;
    layer.forEach((s) => placed.add(s.id));
    layers.push(layer);
  }

  // Add any remaining (cycle or orphan)
  const remaining = subtasks.filter((s) => !placed.has(s.id));
  if (remaining.length > 0) layers.push(remaining);

  return layers;
}

export function SubtaskProgress({ runId }: SubtaskProgressProps) {
  const run = useRunStore((s) => s.runs[runId]);

  const subtasks: Subtask[] = useMemo(() => {
    if (!run?.steps) return [];
    return run.steps.map((step, i) => ({
      id: step.id,
      name: step.step_name || step.description?.slice(0, 30) || step.id,
      description: step.description,
      status: (step.status || "pending") as SubtaskStatus,
      role: step.skill_name,
      depends_on: (step as any).depends_on,
      order: i,
    }));
  }, [run?.steps]);

  const layers = useMemo(() => buildLayers(subtasks), [subtasks]);

  if (subtasks.length < 2) return null;

  const completed = subtasks.filter((s) => s.status === "completed").length;
  const running = subtasks.filter((s) => s.status === "running").length;
  const failed = subtasks.filter((s) => s.status === "failed").length;
  const total = subtasks.length;
  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const isMultiLayer = layers.length > 1;

  return (
    <div className="mt-2 rounded-lg border border-slate-200 dark:border-slate-700 p-3">
      <div className="flex items-center gap-2 mb-2">
        <GitBranch className="w-3.5 h-3.5 text-indigo-500" />
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
          {isMultiLayer ? "多阶段并行执行" : "多任务并行执行"}
        </span>
        <span className="ml-auto text-[10px] text-slate-400">
          {completed}/{total} 完成
          {running > 0 && ` · ${running} 执行中`}
          {failed > 0 && ` · ${failed} 失败`}
        </span>
      </div>

      <div className="h-1.5 w-full rounded-full bg-slate-100 dark:bg-slate-800 mb-2">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            failed > 0 ? "bg-red-400" : "bg-indigo-500",
          )}
          style={{ width: `${progressPct}%` }}
        />
      </div>

      <div className="space-y-1">
        {layers.map((layer, layerIdx) => (
          <div key={layerIdx}>
            {/* Layer connector arrow (between layers) */}
            {layerIdx > 0 && (
              <div className="flex justify-center py-0.5">
                <ArrowDown className="w-3 h-3 text-slate-300" />
              </div>
            )}

            {/* Layer label for multi-layer DAG */}
            {isMultiLayer && (
              <div className="text-[10px] text-slate-400 mb-0.5 px-1">
                {layer.length > 1
                  ? `阶段 ${layerIdx + 1} (${layer.length} 个并行)`
                  : `阶段 ${layerIdx + 1}`}
              </div>
            )}

            {/* Nodes in this layer */}
            <div className={cn(
              layer.length > 1 ? "grid gap-1" : "space-y-1",
              layer.length === 2 && "grid-cols-2",
              layer.length >= 3 && "grid-cols-3",
            )}>
              {layer.map((st) => {
                const cfg = STATUS_CONFIG[st.status] || STATUS_CONFIG.pending;
                const Icon = cfg.icon;
                return (
                  <div
                    key={st.id}
                    className={cn("flex items-center gap-1.5 rounded px-2 py-1 text-xs", cfg.bg)}
                  >
                    <Icon
                      className={cn(
                        "w-3 h-3 shrink-0",
                        cfg.color,
                        st.status === "running" && "animate-spin",
                      )}
                    />
                    <span className="truncate font-medium text-slate-700 dark:text-slate-300">
                      {st.name}
                    </span>
                    {st.role && (
                      <span className="ml-auto shrink-0 text-[10px] text-slate-400">
                        {st.role}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
