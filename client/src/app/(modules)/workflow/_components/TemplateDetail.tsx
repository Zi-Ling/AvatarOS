"use client";

import { useState, useEffect } from "react";
import { X, ArrowRight, Loader2, Play, Cpu, Globe, Terminal, Route, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";
import { workflowApi, WorkflowVersion, WorkflowStepDef } from "@/lib/api/workflow";

interface TemplateDetailProps {
  templateId: string;
  onClose: () => void;
  onRefresh: () => void;
}

const EXECUTOR_ICONS: Record<string, any> = {
  skill: Wrench,
  task_session: Cpu,
  browser_automation: Globe,
  native_adapter: Terminal,
  routed: Route,
};

const EXECUTOR_LABELS: Record<string, string> = {
  skill: "Skill",
  task_session: "Agent 任务",
  browser_automation: "浏览器自动化",
  native_adapter: "原生适配器",
  routed: "智能路由",
};

export function TemplateDetail({ templateId, onClose, onRefresh }: TemplateDetailProps) {
  const [template, setTemplate] = useState<any>(null);
  const [version, setVersion] = useState<WorkflowVersion | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    workflowApi.getTemplate(templateId)
      .then(async (tpl) => {
        setTemplate(tpl);
        if (tpl.latest_version_id) {
          const v = await workflowApi.getVersion(templateId, tpl.latest_version_id);
          setVersion(v);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [templateId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-5 h-5 text-orange-500 animate-spin" />
      </div>
    );
  }

  if (!template || !version) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-sm">
        模板加载失败
      </div>
    );
  }

  // Build dependency map from edges
  const depMap = new Map<string, string[]>();
  for (const edge of version.edges) {
    const deps = depMap.get(edge.target_step_id) || [];
    deps.push(edge.source_step_id);
    depMap.set(edge.target_step_id, deps);
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h3 className="text-lg font-bold text-slate-800 dark:text-white">{template.name}</h3>
          {template.description && (
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{template.description}</p>
          )}
          <div className="flex items-center gap-2 mt-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-100 dark:bg-white/5 text-slate-500">
              v{version.version_number}
            </span>
            <span className="text-[10px] text-slate-400">
              {version.steps.length} 步骤 · {version.edges.length} 依赖
            </span>
          </div>
        </div>
        <button onClick={onClose} className="p-1.5 hover:bg-slate-100 dark:hover:bg-white/10 rounded-lg transition-colors">
          <X className="w-4 h-4 text-slate-400" />
        </button>
      </div>

      {/* Pipeline View */}
      <div className="space-y-3">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest">执行管线</h4>
        <div className="space-y-2">
          {version.steps.map((step, idx) => {
            const Icon = EXECUTOR_ICONS[step.executor_type] || Cpu;
            const deps = depMap.get(step.step_id) || [];
            return (
              <div key={step.step_id}>
                {idx > 0 && (
                  <div className="flex justify-center py-1">
                    <ArrowRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 rotate-90" />
                  </div>
                )}
                <div className="p-3 rounded-lg border border-slate-200 dark:border-white/5 bg-white dark:bg-slate-900/50">
                  <div className="flex items-center gap-2 mb-1">
                    <div className="w-6 h-6 rounded-md bg-orange-500/10 flex items-center justify-center">
                      <Icon className="w-3.5 h-3.5 text-orange-500" />
                    </div>
                    <span className="text-sm font-medium text-slate-800 dark:text-white">{step.name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-white/5 text-slate-400 font-mono">
                      {EXECUTOR_LABELS[step.executor_type]}
                    </span>
                  </div>
                  {step.goal && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 ml-8">{step.goal}</p>
                  )}
                  {step.capability_name && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 ml-8 font-mono">{step.capability_name}</p>
                  )}
                  {deps.length > 0 && (
                    <p className="text-[10px] text-slate-400 ml-8 mt-1">
                      依赖: {deps.join(", ")}
                    </p>
                  )}
                  <div className="flex items-center gap-3 ml-8 mt-1 text-[10px] text-slate-400">
                    <span>超时 {step.timeout_seconds}s</span>
                    {step.failure_policy && <span>失败策略: {step.failure_policy}</span>}
                    {step.retry_max > 0 && <span>重试 {step.retry_max}次</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Parameters */}
      {version.parameters.length > 0 && (
        <div className="mt-6 space-y-3">
          <h4 className="text-xs font-bold text-slate-400 uppercase tracking-widest">参数</h4>
          <div className="space-y-1">
            {version.parameters.map((p) => (
              <div key={p.name} className="flex items-center justify-between p-2 rounded-lg bg-slate-50 dark:bg-white/5 text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-medium text-slate-700 dark:text-slate-300">{p.name}</span>
                  <span className="text-slate-400">{p.type}</span>
                  {p.required && <span className="text-red-400">*</span>}
                </div>
                {p.default !== undefined && p.default !== null && (
                  <span className="font-mono text-slate-400">= {String(p.default)}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
