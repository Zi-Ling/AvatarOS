"use client";

import { useState } from "react";
import {
  Zap,
  Clock,
  MousePointer,
  Globe,
  Link2,
  Trash2,
  Play,
  ToggleLeft,
  ToggleRight,
  Plus,
  Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { workflowApi, WorkflowTrigger, WorkflowTemplate } from "@/lib/api/workflow";
import { useToast } from "@/lib/hooks/useToast";
import { CreateTriggerDialog } from "./CreateTriggerDialog";

interface TriggerListProps {
  triggers: WorkflowTrigger[];
  templates: WorkflowTemplate[];
  onRefresh: () => void;
}

const TRIGGER_ICONS: Record<string, any> = {
  manual: MousePointer,
  cron: Clock,
  api: Globe,
  workflow_completed: Link2,
};

const TRIGGER_LABELS: Record<string, string> = {
  manual: "手动触发",
  cron: "定时触发",
  api: "API 触发",
  workflow_completed: "级联触发",
};

export function TriggerList({ triggers, templates, onRefresh }: TriggerListProps) {
  const toast = useToast();
  const [showCreate, setShowCreate] = useState(false);

  const getTemplateName = (id: string) => templates.find(t => t.id === id)?.name || "Unknown";

  const handleToggle = async (trigger: WorkflowTrigger) => {
    try {
      await workflowApi.updateTrigger(trigger.id, { is_active: !trigger.is_active });
      toast.success(trigger.is_active ? "已禁用" : "已启用", "触发器状态已更新");
      onRefresh();
    } catch (e) {
      toast.error("操作失败", e instanceof Error ? e.message : "未知错误");
    }
  };

  const handleFire = async (trigger: WorkflowTrigger) => {
    try {
      await workflowApi.fireTrigger(trigger.id);
      toast.success("已触发", "工作流开始执行");
      onRefresh();
    } catch (e) {
      toast.error("触发失败", e instanceof Error ? e.message : "未知错误");
    }
  };

  const handleDelete = async (trigger: WorkflowTrigger) => {
    try {
      await workflowApi.deleteTrigger(trigger.id);
      toast.success("已删除", "触发器已移除");
      onRefresh();
    } catch (e) {
      toast.error("删除失败", e instanceof Error ? e.message : "未知错误");
    }
  };

  return (
    <div className="overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-slate-400">{triggers.length} 个触发器</span>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-600 text-white text-xs font-medium hover:bg-orange-500 transition-colors"
        >
          <Plus className="w-3 h-3" /> 新建触发器
        </button>
      </div>

      {triggers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500">
          <Layers className="w-12 h-12 mb-4 opacity-30" />
          <p className="text-sm font-medium">暂无触发器</p>
          <p className="text-xs mt-1">为工作流模板配置自动触发规则</p>
        </div>
      ) : (
        <div className="space-y-3">
          {triggers.map((trigger) => {
            const Icon = TRIGGER_ICONS[trigger.trigger_type] || Zap;
            return (
              <div key={trigger.id} className="p-4 rounded-xl border border-slate-200 dark:border-white/5 bg-white dark:bg-slate-900/50">
                <div className="flex items-center gap-3">
                  <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", trigger.is_active ? "bg-orange-500/10" : "bg-slate-100 dark:bg-white/5")}>
                    <Icon className={cn("w-4 h-4", trigger.is_active ? "text-orange-500" : "text-slate-400")} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-800 dark:text-white">
                        {TRIGGER_LABELS[trigger.trigger_type]}
                      </span>
                      <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", trigger.is_active ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : "bg-slate-100 text-slate-500 dark:bg-white/5 dark:text-slate-400")}>
                        {trigger.is_active ? "活跃" : "禁用"}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-[10px] text-slate-400">
                      <span>模板: {getTemplateName(trigger.template_id)}</span>
                      <span>版本: {trigger.version_mode}</span>
                      {trigger.cron_expression && <span className="font-mono">cron: {trigger.cron_expression}</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button onClick={() => handleToggle(trigger)} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 transition-colors" title={trigger.is_active ? "禁用" : "启用"}>
                      {trigger.is_active ? <ToggleRight className="w-4 h-4 text-emerald-500" /> : <ToggleLeft className="w-4 h-4 text-slate-400" />}
                    </button>
                    <button onClick={() => handleFire(trigger)} className="p-1.5 rounded-lg hover:bg-emerald-100 dark:hover:bg-emerald-500/10 text-emerald-600 transition-colors" title="手动触发">
                      <Play className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => handleDelete(trigger)} className="p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-500/10 text-red-500 transition-colors" title="删除">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <CreateTriggerDialog open={showCreate} templates={templates} onClose={() => setShowCreate(false)} onSuccess={onRefresh} />
    </div>
  );
}
