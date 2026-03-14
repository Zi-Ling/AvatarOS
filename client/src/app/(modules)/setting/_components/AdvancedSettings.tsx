"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { AlertTriangle, FolderOpen, Bot, HardDrive, Zap } from "lucide-react";
import { LoadingSpinner } from "@/components/ui/StateViews";

interface AgentConfig {
  max_replan_attempts: number;
  enable_self_correction: boolean;
  enable_context_memory: boolean;
  enable_verbose_logging: boolean;
  enable_plan_cache: boolean;
  enable_parallel_execution: boolean;
}

const inputCls = "rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:border-indigo-400 focus:outline-none transition-colors";

function SectionCard({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100 dark:border-slate-800">
        <Icon className="w-3.5 h-3.5 text-indigo-500" />
        <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">{title}</span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function Toggle({ checked, onChange, label, description }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; description?: string;
}) {
  return (
    <label className="flex items-center justify-between gap-4 cursor-pointer py-1">
      <div>
        <div className="text-sm text-slate-700 dark:text-slate-200">{label}</div>
        {description && <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{description}</div>}
      </div>
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors focus:outline-none ${
          checked ? "bg-indigo-500" : "bg-slate-200 dark:bg-slate-700"
        }`}
      >
        <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform ${
          checked ? "translate-x-4" : "translate-x-0"
        }`} />
      </button>
    </label>
  );
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
  const [loading, setLoading] = useState(true);
  const agentDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isFirstLoad = useRef(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [agentRes, wsRes] = await Promise.all([
        fetch("/api/v1/settings/agent"),
        fetch("/workspace/current"),
      ]);
      if (agentRes.ok) setAgent(await agentRes.json());
      if (wsRes.ok) { const ws = await wsRes.json(); setWorkspacePath(ws.path ?? "./workspace"); }
    } catch {} finally {
      setLoading(false);
      isFirstLoad.current = false;
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const autoSaveAgent = useCallback((cfg: AgentConfig) => {
    if (isFirstLoad.current) return;
    if (agentDebounce.current) clearTimeout(agentDebounce.current);
    agentDebounce.current = setTimeout(async () => {
      try {
        await fetch("/api/v1/settings/agent", {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cfg),
        });
      } catch {}
    }, 600);
  }, []);

  const autoSaveWorkspace = useCallback((path: string) => {
    if (isFirstLoad.current) return;
    if (wsDebounce.current) clearTimeout(wsDebounce.current);
    wsDebounce.current = setTimeout(async () => {
      try {
        await fetch("/workspace/set", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }),
        });
      } catch {}
    }, 800);
  }, []);

  const updateAgent = (patch: Partial<AgentConfig>) => {
    setAgent(a => {
      const next = { ...a, ...patch };
      autoSaveAgent(next);
      return next;
    });
  };

  const toggle = (key: keyof AgentConfig) => updateAgent({ [key]: !agent[key] });

  const selectFolder = async () => {
    try {
      const res = await fetch("/workspace/select-folder", { method: "POST" });
      if (res.ok) { const d = await res.json(); setWorkspacePath(d.path); autoSaveWorkspace(d.path); }
    } catch {}
  };

  if (loading) {
    return <LoadingSpinner text="加载配置中..." />;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-4 py-3">
        <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">高级选项</p>
          <p className="text-[11px] text-amber-600 dark:text-amber-400/80 mt-0.5">这些设置会影响系统的核心行为，请谨慎修改</p>
        </div>
      </div>

      <SectionCard icon={Bot} title="Agent 行为">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">最大重规划次数</label>
            <div className="flex items-center gap-3">
              <input type="number" min="0" max="5" value={agent.max_replan_attempts}
                onChange={e => updateAgent({ max_replan_attempts: parseInt(e.target.value) || 0 })}
                className={`${inputCls} w-24`} />
              <span className="text-[11px] text-slate-400">任务失败时 Agent 重新规划的最大次数（0–5）</span>
            </div>
          </div>
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            <div className="pb-2">
              <Toggle checked={agent.enable_self_correction} onChange={() => toggle("enable_self_correction")} label="启用自纠错机制" />
            </div>
            <div className="py-2">
              <Toggle checked={agent.enable_context_memory} onChange={() => toggle("enable_context_memory")} label="启用上下文记忆" />
            </div>
            <div className="pt-2">
              <Toggle checked={agent.enable_verbose_logging} onChange={() => toggle("enable_verbose_logging")} label="启用详细日志" description="开启后日志量会显著增加" />
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard icon={HardDrive} title="工作空间">
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">工作目录路径</label>
          <div className="flex gap-2">
            <input type="text" value={workspacePath}
              onChange={e => { setWorkspacePath(e.target.value); autoSaveWorkspace(e.target.value); }}
              placeholder="./workspace"
              className={`${inputCls} flex-1`} />
            <button onClick={selectFolder} title="浏览文件夹"
              className="px-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-500 hover:text-slate-700 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
            >
              <FolderOpen className="w-4 h-4" />
            </button>
          </div>
          <p className="text-[11px] text-slate-400 dark:text-slate-500">Agent 执行任务时的工作目录，所有文件操作都在此目录下进行</p>
        </div>
      </SectionCard>

      <SectionCard icon={Zap} title="性能优化">
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          <div className="pb-2">
            <Toggle checked={agent.enable_plan_cache} onChange={() => toggle("enable_plan_cache")} label="启用计划缓存" description="相似任务复用已有执行计划" />
          </div>
          <div className="pt-2">
            <Toggle checked={agent.enable_parallel_execution} onChange={() => toggle("enable_parallel_execution")} label="启用并行执行" description="实验性功能，可能导致不稳定" />
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
