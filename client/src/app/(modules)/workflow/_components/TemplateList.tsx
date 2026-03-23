"use client";

import { useState } from "react";
import {
  Play,
  Copy,
  Trash2,
  MoreVertical,
  Tag,
  Clock,
  ChevronRight,
  Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { workflowApi, WorkflowTemplate } from "@/lib/api/workflow";
import { useToast } from "@/lib/hooks/useToast";
import { TemplateDetail } from "./TemplateDetail";

interface TemplateListProps {
  templates: WorkflowTemplate[];
  onRefresh: () => void;
}

export function TemplateList({ templates, onRefresh }: TemplateListProps) {
  const toast = useToast();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);

  const handleRun = async (tpl: WorkflowTemplate) => {
    try {
      await workflowApi.createInstance({ template_version_id: tpl.latest_version_id });
      toast.success("已启动", `工作流 "${tpl.name}" 开始执行`);
      onRefresh();
    } catch (e) {
      toast.error("启动失败", e instanceof Error ? e.message : "未知错误");
    }
  };

  const handleClone = async (tpl: WorkflowTemplate) => {
    try {
      await workflowApi.cloneTemplate(tpl.id, `${tpl.name} (副本)`);
      toast.success("克隆成功", "模板已复制");
      onRefresh();
    } catch (e) {
      toast.error("克隆失败", e instanceof Error ? e.message : "未知错误");
    }
    setMenuOpen(null);
  };

  const handleDelete = async (tpl: WorkflowTemplate) => {
    try {
      await workflowApi.deleteTemplate(tpl.id);
      toast.success("已删除", `模板 "${tpl.name}" 已移除`);
      if (selectedId === tpl.id) setSelectedId(null);
      onRefresh();
    } catch (e) {
      toast.error("删除失败", e instanceof Error ? e.message : "未知错误");
    }
    setMenuOpen(null);
  };

  if (templates.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400 dark:text-slate-500">
        <Layers className="w-12 h-12 mb-4 opacity-30" />
        <p className="text-sm font-medium">暂无工作流模板</p>
        <p className="text-xs mt-1">点击左侧"创建工作流"开始</p>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Template List */}
      <div className={cn("overflow-y-auto p-6", selectedId ? "w-1/2 border-r border-slate-200 dark:border-white/5" : "w-full")}>
        <div className="grid gap-3">
          {templates.map((tpl) => (
            <div
              key={tpl.id}
              onClick={() => setSelectedId(tpl.id)}
              className={cn(
                "group relative p-4 rounded-xl border transition-all cursor-pointer",
                selectedId === tpl.id
                  ? "border-orange-300 dark:border-orange-500/40 bg-orange-50/50 dark:bg-orange-500/5"
                  : "border-slate-200 dark:border-white/5 bg-white dark:bg-slate-900/50 hover:border-slate-300 dark:hover:border-white/10 hover:shadow-sm"
              )}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-semibold text-slate-800 dark:text-white truncate">{tpl.name}</h3>
                    <ChevronRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                  {tpl.description && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2 mb-2">{tpl.description}</p>
                  )}
                  <div className="flex items-center gap-3 text-[10px] text-slate-400">
                    {tpl.tags?.length > 0 && (
                      <span className="flex items-center gap-1">
                        <Tag className="w-3 h-3" />
                        {tpl.tags.slice(0, 3).join(", ")}
                      </span>
                    )}
                    {tpl.created_at && (
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {new Date(tpl.created_at).toLocaleDateString("zh-CN")}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-1 ml-3 shrink-0">
                  <button
                    onClick={(e) => { e.stopPropagation(); handleRun(tpl); }}
                    className="p-1.5 rounded-lg hover:bg-emerald-100 dark:hover:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 transition-colors"
                    title="执行"
                  >
                    <Play className="w-3.5 h-3.5" />
                  </button>
                  <div className="relative">
                    <button
                      onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === tpl.id ? null : tpl.id); }}
                      className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 text-slate-400 transition-colors"
                    >
                      <MoreVertical className="w-3.5 h-3.5" />
                    </button>
                    {menuOpen === tpl.id && (
                      <div className="absolute right-0 top-8 w-32 bg-white dark:bg-slate-800 border border-slate-200 dark:border-white/10 rounded-lg shadow-lg z-10 py-1">
                        <button onClick={(e) => { e.stopPropagation(); handleClone(tpl); }} className="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/5">
                          <Copy className="w-3 h-3" /> 克隆
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); handleDelete(tpl); }} className="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10">
                          <Trash2 className="w-3 h-3" /> 删除
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Detail Panel */}
      {selectedId && (
        <div className="w-1/2 overflow-y-auto">
          <TemplateDetail templateId={selectedId} onClose={() => setSelectedId(null)} onRefresh={onRefresh} />
        </div>
      )}
    </div>
  );
}
