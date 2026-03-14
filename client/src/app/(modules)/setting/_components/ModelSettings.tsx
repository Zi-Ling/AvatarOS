"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Check, AlertCircle, Loader2, ChevronDown, ChevronUp, Cpu, Link, Sliders } from "lucide-react";

type LLMProvider = "ollama" | "openai" | "deepseek" | "moonshot" | "qwen" | "glm";

interface LLMConfig {
  provider: LLMProvider;
  model: string;
  base_url: string;
  api_key: string;
  temperature: number;
  max_tokens: number;
}

const PROVIDERS: { id: LLMProvider; name: string; url: string; needsKey: boolean }[] = [
  { id: "ollama",   name: "Ollama (本地)",  url: "http://localhost:11434",                             needsKey: false },
  { id: "openai",   name: "OpenAI",         url: "https://api.openai.com/v1",                          needsKey: true  },
  { id: "deepseek", name: "DeepSeek",       url: "https://api.deepseek.com",                           needsKey: true  },
  { id: "moonshot", name: "Moonshot",       url: "https://api.moonshot.cn/v1",                         needsKey: true  },
  { id: "qwen",     name: "通义千问",        url: "https://dashscope.aliyuncs.com/compatible-mode/v1", needsKey: true  },
  { id: "glm",      name: "智谱 GLM",       url: "https://open.bigmodel.cn/api/paas/v4",              needsKey: true  },
];

const inputCls = "w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:border-indigo-400 focus:outline-none transition-colors";

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

function FieldRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">{label}</label>
      {children}
      {hint && <p className="text-[11px] text-slate-400 dark:text-slate-500">{hint}</p>}
    </div>
  );
}

function SaveIndicator({ status }: { status: "idle" | "saving" | "saved" | "error" }) {
  if (status === "idle") return null;
  return (
    <span className={`flex items-center gap-1 text-[11px] ${
      status === "saving" ? "text-slate-400" :
      status === "saved"  ? "text-emerald-500" :
                            "text-red-500"
    }`}>
      {status === "saving" && <Loader2 className="w-3 h-3 animate-spin" />}
      {status === "saved"  && <Check className="w-3 h-3" />}
      {status === "saving" ? "保存中..." : status === "saved" ? "已保存" : "保存失败"}
    </span>
  );
}

export function ModelSettings() {
  const [config, setConfig] = useState<LLMConfig>({
    provider: "deepseek", model: "deepseek-chat",
    base_url: "https://api.deepseek.com", api_key: "",
    temperature: 0.7, max_tokens: 4096,
  });
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [isOpen, setIsOpen] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isFirstLoad = useRef(true);
  const cur = PROVIDERS.find(p => p.id === config.provider) || PROVIDERS[2];

  // 初始加载
  useEffect(() => {
    fetch("/api/v1/settings/llm").then(r => r.ok ? r.json() : null).then(d => {
      if (d) setConfig(c => ({ ...c, ...d }));
    }).catch(() => {}).finally(() => { isFirstLoad.current = false; });
  }, []);

  // 关闭下拉
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setIsOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  // debounce 自动保存
  const autoSave = useCallback((cfg: LLMConfig) => {
    if (isFirstLoad.current) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setSaveStatus("saving");
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch("/api/v1/settings/llm", {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cfg),
        });
        setSaveStatus(res.ok ? "saved" : "error");
        if (res.ok) setTimeout(() => setSaveStatus("idle"), 2000);
      } catch { setSaveStatus("error"); }
    }, 600);
  }, []);

  const updateConfig = (patch: Partial<LLMConfig>) => {
    setConfig(c => {
      const next = { ...c, ...patch };
      autoSave(next);
      return next;
    });
  };

  const pick = (id: LLMProvider) => {
    const p = PROVIDERS.find(x => x.id === id);
    if (p) updateConfig({ provider: id, base_url: p.url, api_key: p.needsKey ? config.api_key : "" });
    setTestResult(null);
    setIsOpen(false);
  };

  const testConn = async () => {
    setIsTesting(true); setTestResult(null);
    try {
      const res = await fetch("/api/v1/settings/test-llm", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config),
      });
      const d = await res.json();
      setTestResult({ success: d.success ?? res.ok, message: d.message ?? (res.ok ? "连接成功" : "连接失败") });
    } catch { setTestResult({ success: false, message: "无法连接到后端服务" }); }
    finally { setIsTesting(false); }
  };

  return (
    <div className="space-y-3">
      {/* 服务商 — 不用 overflow-hidden，让下拉能溢出 */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100 dark:border-slate-800">
          <Cpu className="w-3.5 h-3.5 text-indigo-500" />
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">AI 服务商</span>
        </div>
        <div className="p-4">
          <div className="relative" ref={dropRef}>
            <button
              type="button"
              onClick={() => setIsOpen(!isOpen)}
              className="w-full flex items-center justify-between rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 hover:border-indigo-400 transition-colors"
            >
              <span className="font-medium">{cur.name}</span>
              {isOpen ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
            </button>
            {isOpen && (
              <div className="absolute z-50 mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-xl py-1">
                {PROVIDERS.map(p => (
                  <button key={p.id} onClick={() => pick(p.id)}
                    className={`w-full flex items-center justify-between px-3 py-2 text-sm transition-colors ${
                      config.provider === p.id
                        ? "bg-indigo-50 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300"
                        : "text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
                    }`}
                  >
                    <span>{p.name}</span>
                    {config.provider === p.id && <Check className="w-3.5 h-3.5" />}
                  </button>
                ))}
              </div>
            )}
          </div>
          <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-2">
            {cur.needsKey ? "需要 API Key" : "本地运行，无需 Key"}
          </p>
        </div>
      </div>

      {/* 模型配置 + 测试连接 */}
      <SectionCard icon={Link} title="模型配置">
        <div className="space-y-3">
          <FieldRow label="模型名称">
            <input type="text" value={config.model}
              onChange={e => updateConfig({ model: e.target.value })}
              placeholder="e.g. deepseek-chat" className={inputCls} />
          </FieldRow>
          <FieldRow label="API 地址">
            <input type="text" value={config.base_url}
              onChange={e => updateConfig({ base_url: e.target.value })}
              className={inputCls} />
          </FieldRow>
          {cur.needsKey && (
            <FieldRow label="API Key">
              <input type="password" value={config.api_key}
                onChange={e => updateConfig({ api_key: e.target.value })}
                placeholder="sk-..." className={inputCls} />
            </FieldRow>
          )}

          {/* 测试连接放在模型配置卡片内 */}
          <div className="pt-1 flex items-center gap-3">
            <button onClick={testConn} disabled={isTesting}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
            >
              {isTesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <AlertCircle className="w-3.5 h-3.5" />}
              测试连接
            </button>
            <SaveIndicator status={saveStatus} />
          </div>

          {testResult && (
            <div className={`rounded-lg border p-3 flex items-center gap-2 text-xs ${
              testResult.success
                ? "border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : "border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400"
            }`}>
              {testResult.success ? <Check className="w-3.5 h-3.5 shrink-0" /> : <AlertCircle className="w-3.5 h-3.5 shrink-0" />}
              {testResult.message}
            </div>
          )}
        </div>
      </SectionCard>

      {/* 参数 */}
      <SectionCard icon={Sliders} title="参数调节">
        <div className="space-y-4">
          <FieldRow label="Temperature" hint="值越低回答越确定，值越高越有创造性">
            <div className="flex items-center gap-3">
              <input type="range" min="0" max="2" step="0.1" value={config.temperature}
                onChange={e => updateConfig({ temperature: parseFloat(e.target.value) })}
                className="flex-1 accent-indigo-500" />
              <span className="text-sm font-mono text-indigo-500 w-8 text-right">{config.temperature}</span>
            </div>
          </FieldRow>
          <FieldRow label="Max Tokens">
            <input type="number" min="256" max="32768" step="256" value={config.max_tokens}
              onChange={e => updateConfig({ max_tokens: parseInt(e.target.value) || 4096 })}
              className={`${inputCls} max-w-[140px]`} />
          </FieldRow>
        </div>
      </SectionCard>
    </div>
  );
}
