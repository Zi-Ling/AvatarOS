"use client";

import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, Loader2, Check, FolderOpen } from "lucide-react";

interface AgentConfig {
  max_replan_attempts: number;
  enable_self_correction: boolean;
  enable_context_memory: boolean;
  enable_verbose_logging: boolean;
  enable_plan_cache: boolean;
  enable_parallel_execution: boolean;
}

export function AdvancedSettings() {
  const [agent, setAgent] = useState<AgentConfig>({
    max_replan_attempts: 2,
    enable_self_correction: true,
    enable_context_memory: true,
    enable_verbose_logging: false,
    enable_plan_cache: true,
    enable_parallel_execution: false,
  });
  const [workspacePath, setWorkspacePath] = useState("./workspace");
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [wsSaveStatus, setWsSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [agentRes, wsRes] = await Promise.all([
        fetch("/api/v1/settings/agent"),
        fetch("/workspace/current"),
      ]);
      if (agentRes.ok) setAgent(await agentRes.json());
      if (wsRes.ok) {
        const ws = await wsRes.json();
        setWorkspacePath(ws.path ?? "./workspace");
      }
    } catch {
      // 静默失败，使用默认值
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveAgent = async () => {
    setSaveStatus("saving");
    try {
      const res = await fetch("/api/v1/settings/agent", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(agent),
      });
      setSaveStatus(res.ok ? "saved" : "error");
      if (res.ok) setTimeout(() => setSaveStatus("idle"), 2000);
    } catch {
      setSaveStatus("error");
    }
  };

  const saveWorkspace = async () => {
    setWsSaveStatus("saving");
    try {
      const res = await fetch("/workspace/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: workspacePath }),
      });
      setWsSaveStatus(res.ok ? "saved" : "error");
      if (res.ok) setTimeout(() => setWsSaveStatus("idle"), 2000);
    } catch {
      setWsSaveStatus("error");
    }
  };

  const selectFolder = async () => {
    try {
      const res = await fetch("/workspace/select-folder", { method: "POST" });
      if (res.ok) {
        const d = await res.json();
        setWorkspacePath(d.path);
      }
    } catch {
      // 非桌面环境静默失败
    }
  };

  const toggle = (key: keyof AgentConfig) =>
    setAgent((a) => ({ ...a, [key]: !a[key as keyof AgentConfig] }));

  const inputCls = "w-full max-w-xs rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 px-4 py-2.5 text-sm text-slate-800 dark:text-white focus:border-indigo-400 focus:outline-none";

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-slate-400 gap-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-sm">加载配置中...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 min-h-full">
      {/* 警告提示 */}
      <div className="rounded-lg border border-yellow-400/50 dark:border-yellow-500/50 bg-yellow-50 dark:bg-yellow-500/10 p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-yellow-500 dark:text-yellow-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-yellow-700 dark:text-yellow-300 font-medium">高级选项</p>
            <p className="text-xs text-yellow-600 dark:text-yellow-300/80 mt-1">
              这些设置会影响系统的核心行为，请谨慎修改
            </p>
          </div>
        </div>
      </div>

      {/* Agent 行为 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">Agent 行为</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-white/80 mb-2">
              最大重规划次数
            </label>
            <input
              type="number"
              min="0"
              max="5"
              value={agent.max_replan_attempts}
              onChange={(e) => setAgent((a) => ({ ...a, max_replan_attempts: parseInt(e.target.value) || 0 }))}
              className={inputCls}
            />
            <p className="text-xs text-slate-500 dark:text-white/50 mt-1">
              当任务执行失败时，Agent 会尝试重新规划的次数（0-5）
            </p>
          </div>

          <div className="space-y-3">
            {([
              ["enable_self_correction", "启用自纠错机制"],
              ["enable_context_memory", "启用上下文记忆"],
              ["enable_verbose_logging", "启用详细日志"],
            ] as const).map(([key, label]) => (
              <label key={key} className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agent[key]}
                  onChange={() => toggle(key)}
                  className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500"
                />
                <span className="text-sm text-slate-700 dark:text-white/80">{label}</span>
              </label>
            ))}
          </div>
        </div>
      </section>

      {/* 工作空间 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">工作空间</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-white/80 mb-2">
              工作目录路径
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={workspacePath}
                onChange={(e) => setWorkspacePath(e.target.value)}
                placeholder="./workspace"
                className="flex-1 rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 px-4 py-2.5 text-sm text-slate-800 dark:text-white placeholder:text-slate-400 dark:placeholder:text-white/40 focus:border-indigo-400 focus:outline-none"
              />
              <button
                onClick={selectFolder}
                title="浏览文件夹"
                className="px-3 rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 text-slate-500 hover:text-slate-700 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-white/10 transition-colors"
              >
                <FolderOpen className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-slate-500 dark:text-white/50 mt-1">
              Agent 执行任务时的工作目录，所有文件操作都在此目录下进行
            </p>
          </div>
          <button
            onClick={saveWorkspace}
            disabled={wsSaveStatus === "saving"}
            className="flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-2.5 text-sm text-white transition-colors disabled:opacity-50"
          >
            {wsSaveStatus === "saving" ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            {wsSaveStatus === "saved" ? "已保存" : wsSaveStatus === "saving" ? "保存中..." : "应用路径"}
          </button>
          {wsSaveStatus === "error" && <p className="text-xs text-red-500">保存失败，请检查路径是否有效</p>}
        </div>
      </section>

      {/* 性能优化 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">性能优化</h3>
        <div className="space-y-3">
          {([
            ["enable_plan_cache", "启用计划缓存"],
            ["enable_parallel_execution", "启用并行执行（实验性）"],
          ] as const).map(([key, label]) => (
            <label key={key} className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={agent[key]}
                onChange={() => toggle(key)}
                className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500"
              />
              <span className="text-sm text-slate-700 dark:text-white/80">{label}</span>
            </label>
          ))}
        </div>
      </section>

      {/* 保存 Agent 配置 */}
      <div className="flex items-center gap-3">
        <button
          onClick={saveAgent}
          disabled={saveStatus === "saving"}
          className="flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-2.5 text-sm text-white transition-colors disabled:opacity-50"
        >
          {saveStatus === "saving" ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
          {saveStatus === "saved" ? "已保存" : saveStatus === "saving" ? "保存中..." : "保存 Agent 配置"}
        </button>
        {saveStatus === "error" && <span className="text-xs text-red-500">保存失败，请重试</span>}
      </div>
    </div>
  );
}
