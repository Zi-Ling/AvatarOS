"use client";

import { useState, useEffect } from "react";
import {
  Workflow,
  Plus,
  Play,
  LayoutList,
  History,
  Zap,
  RefreshCw,
  AlertCircle,
  XCircle,
  BarChart3,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { TemplateList } from "./_components/TemplateList";
import { InstanceList } from "./_components/InstanceList";
import { TriggerList } from "./_components/TriggerList";
import { CreateTemplateDialog } from "./_components/CreateTemplateDialog";
import { workflowApi, WorkflowTemplate, WorkflowInstance, WorkflowTrigger } from "@/lib/api/workflow";

type ViewTab = "templates" | "instances" | "triggers";

export default function WorkflowPage() {
  const [viewTab, setViewTab] = useState<ViewTab>("templates");
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [instances, setInstances] = useState<WorkflowInstance[]>([]);
  const [triggers, setTriggers] = useState<WorkflowTrigger[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [tpls, insts, trigs] = await Promise.all([
        workflowApi.listTemplates().catch(() => []),
        workflowApi.listInstances({ limit: 50 }).catch(() => []),
        workflowApi.listTriggers().catch(() => []),
      ]);
      setTemplates(tpls);
      setInstances(insts);
      setTriggers(trigs);
    } catch (e) {
      setError("无法连接到后端服务");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, []);

  const stats = {
    templates: templates.length,
    running: instances.filter(i => i.status === "running").length,
    completed: instances.filter(i => i.status === "completed").length,
    failed: instances.filter(i => i.status === "failed").length,
    activeTriggers: triggers.filter(t => t.is_active).length,
  };

  const tabs: { key: ViewTab; label: string; icon: any }[] = [
    { key: "templates", label: "模板", icon: LayoutList },
    { key: "instances", label: "执行记录", icon: History },
    { key: "triggers", label: "触发器", icon: Zap },
  ];

  return (
    <div className="flex h-full bg-slate-50 dark:bg-slate-950 overflow-hidden">
      {/* Left Sidebar */}
      <div className="w-72 border-r border-slate-200 dark:border-white/5 bg-white dark:bg-slate-900/50 p-6 flex flex-col backdrop-blur-xl z-20 overflow-y-auto">
        <div className="flex items-center gap-3 mb-8">
          <div className="p-2 rounded-lg bg-orange-500/10 text-orange-600 dark:text-orange-400">
            <Workflow className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-800 dark:text-white tracking-tight">Workflow</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">Task Orchestration</p>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="grid grid-cols-3 gap-1 p-1 bg-slate-100 dark:bg-white/5 rounded-xl mb-8">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setViewTab(tab.key)}
              className={`flex items-center justify-center gap-1 py-2 text-xs font-medium rounded-lg transition-all ${
                viewTab === tab.key
                  ? "bg-white dark:bg-slate-800 text-orange-600 dark:text-orange-400 shadow-sm scale-[1.02]"
                  : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-white/50 dark:hover:bg-white/5"
              }`}
            >
              <tab.icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Create Button */}
        {viewTab === "templates" && (
          <button
            onClick={() => setShowCreateDialog(true)}
            className="group mb-8 flex w-full items-center justify-center gap-2 rounded-xl bg-orange-600 px-4 py-3 text-sm font-semibold text-white hover:bg-orange-500 transition-all shadow-lg shadow-orange-500/20 active:scale-95"
          >
            <Plus className="w-4 h-4 transition-transform group-hover:rotate-90" />
            创建工作流
          </button>
        )}

        {/* Quick Stats */}
        <div className="space-y-4 mb-6">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2">
            <div className="w-1 h-3 bg-orange-500 rounded-full" />
            Quick Stats
          </h3>
          <div className="space-y-2">
            <div className="flex justify-between items-center p-2.5 rounded-lg bg-slate-50 dark:bg-white/5 border border-slate-100 dark:border-white/5">
              <div className="flex items-center gap-2">
                <LayoutList className="w-3 h-3 text-orange-500" />
                <span className="text-xs text-slate-600 dark:text-slate-300">模板</span>
              </div>
              <span className="font-mono font-bold text-orange-500 text-sm">{stats.templates}</span>
            </div>
            <div className="flex justify-between items-center p-2.5 rounded-lg bg-slate-50 dark:bg-white/5 border border-slate-100 dark:border-white/5">
              <div className="flex items-center gap-2">
                <Loader2 className="w-3 h-3 text-blue-500 animate-spin" />
                <span className="text-xs text-slate-600 dark:text-slate-300">运行中</span>
              </div>
              <span className="font-mono font-bold text-blue-500 text-sm">{stats.running}</span>
            </div>
            <div className="flex justify-between items-center p-2.5 rounded-lg bg-slate-50 dark:bg-white/5 border border-slate-100 dark:border-white/5">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                <span className="text-xs text-slate-600 dark:text-slate-300">已完成</span>
              </div>
              <span className="font-mono font-bold text-emerald-500 text-sm">{stats.completed}</span>
            </div>
            <div className="flex justify-between items-center p-2.5 rounded-lg bg-slate-50 dark:bg-white/5 border border-slate-100 dark:border-white/5">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-3 h-3 text-red-500" />
                <span className="text-xs text-slate-600 dark:text-slate-300">失败</span>
              </div>
              <span className="font-mono font-bold text-red-500 text-sm">{stats.failed}</span>
            </div>
          </div>
        </div>

        <div className="mt-auto shrink-0">
          <div className="p-4 rounded-xl bg-gradient-to-br from-orange-50 to-amber-50 dark:from-orange-900/20 dark:to-amber-900/20 border border-orange-100 dark:border-orange-500/10">
            <p className="text-xs text-orange-600 dark:text-orange-300 leading-relaxed italic">
              "Define the stages, let agents handle the details."
            </p>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        <header className="h-20 border-b border-slate-200 dark:border-white/5 flex items-center justify-between px-10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md z-10 sticky top-0">
          <div>
            <h1 className="text-xl font-bold text-slate-800 dark:text-white tracking-tight">
              {viewTab === "templates" ? "工作流模板" : viewTab === "instances" ? "执行记录" : "触发器管理"}
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              {viewTab === "templates"
                ? "定义任务阶段和依赖关系，每个阶段由 Agent 自主执行"
                : viewTab === "instances"
                ? "查看工作流执行状态、步骤进度和失败详情"
                : "配置定时、手动或级联触发规则"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadData}
              className={`p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 transition-colors ${loading ? "animate-spin" : ""}`}
            >
              <RefreshCw className="w-4 h-4 text-slate-500" />
            </button>
          </div>
        </header>

        {error && (
          <div className="mx-10 mt-6 mb-4 p-4 rounded-xl bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-500/30 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">{error}</p>
            </div>
            <button onClick={() => setError(null)} className="p-1 rounded-lg hover:bg-yellow-100 dark:hover:bg-yellow-800/30 transition-colors">
              <XCircle className="w-4 h-4 text-yellow-600 dark:text-yellow-400" />
            </button>
          </div>
        )}

        <div className="flex-1 overflow-hidden bg-slate-50/50 dark:bg-black/20">
          {viewTab === "templates" && (
            <TemplateList templates={templates} onRefresh={loadData} />
          )}
          {viewTab === "instances" && (
            <InstanceList instances={instances} onRefresh={loadData} />
          )}
          {viewTab === "triggers" && (
            <TriggerList triggers={triggers} templates={templates} onRefresh={loadData} />
          )}
        </div>
      </div>

      <CreateTemplateDialog
        open={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        onSuccess={loadData}
      />
    </div>
  );
}
