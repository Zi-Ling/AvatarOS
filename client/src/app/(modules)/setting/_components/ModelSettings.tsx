"use client";

import { useState, useRef, useEffect } from "react";
import {
  Check,
  AlertCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

type LLMProvider =
  | "ollama"
  | "openai"
  | "deepseek"
  | "moonshot"
  | "qwen"
  | "glm";

interface LLMConfig {
  provider: LLMProvider;
  model: string;
  base_url: string;
  api_key: string;
  temperature: number;
  max_tokens: number;
}

const PROVIDERS: {
  id: LLMProvider;
  name: string;
  url: string;
  needsKey: boolean;
}[] = [
  { id: "ollama", name: "Ollama (本地)", url: "http://localhost:11434", needsKey: false },
  { id: "openai", name: "OpenAI", url: "https://api.openai.com/v1", needsKey: true },
  { id: "deepseek", name: "DeepSeek", url: "https://api.deepseek.com", needsKey: true },
  { id: "moonshot", name: "Moonshot", url: "https://api.moonshot.cn/v1", needsKey: true },
  { id: "qwen", name: "通义千问", url: "https://dashscope.aliyuncs.com/compatible-mode/v1", needsKey: true },
  { id: "glm", name: "智谱 GLM", url: "https://open.bigmodel.cn/api/paas/v4", needsKey: true },
];

export function ModelSettings() {
  const [config, setConfig] = useState<LLMConfig>({
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "https://api.deepseek.com",
    api_key: "",
    temperature: 0.7,
    max_tokens: 4096,
  });
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [saveStatus, setSaveStatus] = useState<"saved" | "saving" | "error">("saved");
  const [isOpen, setIsOpen] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);
  const cur = PROVIDERS.find((p) => p.id === config.provider) || PROVIDERS[2];

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const pick = (id: LLMProvider) => {
    const p = PROVIDERS.find((x) => x.id === id);
    if (p) {
      setConfig((c) => ({
        ...c,
        provider: id,
        base_url: p.url,
        api_key: p.needsKey ? c.api_key : "",
      }));
    }
    setTestResult(null);
    setIsOpen(false);
  };

  const testConn = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const res = await fetch("/api/v1/settings/test-llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      const d = await res.json();
      setTestResult({
        success: d.success ?? res.ok,
        message: d.message ?? (res.ok ? "连接成功" : "连接失败"),
      });
    } catch {
      setTestResult({ success: false, message: "无法连接到后端服务" });
    } finally {
      setIsTesting(false);
    }
  };

  const saveConfig = async () => {
    setSaveStatus("saving");
    try {
      const res = await fetch("/api/v1/settings/llm", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      setSaveStatus(res.ok ? "saved" : "error");
    } catch {
      setSaveStatus("error");
    }
  };

  const inputCls = [
    "w-full max-w-md rounded-lg border",
    "border-slate-200 dark:border-white/10",
    "bg-white dark:bg-white/5",
    "px-4 py-2.5 text-sm",
    "text-slate-800 dark:text-white",
    "placeholder:text-slate-400 dark:placeholder:text-white/40",
    "focus:border-indigo-400 focus:outline-none",
  ].join(" ");

  return (
    <div className="space-y-6 min-h-full">
      {/* 服务商 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6 relative z-20">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">AI 服务商</h3>
        <div className="relative" ref={dropRef}>
          <button
            type="button"
            onClick={() => setIsOpen(!isOpen)}
            className={[
              "w-full max-w-md flex items-center justify-between rounded-lg border",
              "border-slate-200 dark:border-white/10 bg-white dark:bg-white/5",
              "px-4 py-2.5 text-sm text-slate-800 dark:text-white",
              "hover:border-indigo-400 transition-colors",
            ].join(" ")}
          >
            <span className="font-medium">{cur.name}</span>
            {isOpen
              ? <ChevronUp className="w-4 h-4 text-slate-400" />
              : <ChevronDown className="w-4 h-4 text-slate-400" />}
          </button>
          {isOpen && (
            <div className={[
              "absolute z-50 mt-1 w-full max-w-md rounded-lg border",
              "border-slate-200 dark:border-white/10",
              "bg-white dark:bg-slate-800 shadow-xl py-1",
            ].join(" ")}>
              {PROVIDERS.map((p) => {
                const active = config.provider === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => pick(p.id)}
                    className={[
                      "w-full flex items-center justify-between px-4 py-2.5 text-sm transition-colors",
                      active
                        ? "bg-indigo-50 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300"
                        : "text-slate-700 dark:text-white/80 hover:bg-slate-50 dark:hover:bg-white/5",
                    ].join(" ")}
                  >
                    <span>{p.name}</span>
                    {active && <Check className="w-4 h-4" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <p className="text-xs text-slate-400 dark:text-white/40 mt-3">
          {cur.needsKey ? "需要 API Key" : "本地运行，无需 Key"}
        </p>
      </section>

      {/* 模型配置 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">模型配置</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-white/80 mb-2">
              模型名称
            </label>
            <input
              type="text"
              value={config.model}
              onChange={(e) => setConfig((c) => ({ ...c, model: e.target.value }))}
              placeholder="e.g. deepseek-chat"
              className={inputCls}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-white/80 mb-2">
              API 地址
            </label>
            <input
              type="text"
              value={config.base_url}
              onChange={(e) => setConfig((c) => ({ ...c, base_url: e.target.value }))}
              className={inputCls}
            />
          </div>
          {cur.needsKey && (
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-white/80 mb-2">
                API Key
              </label>
              <input
                type="password"
                value={config.api_key}
                onChange={(e) => setConfig((c) => ({ ...c, api_key: e.target.value }))}
                placeholder="sk-..."
                className={inputCls}
              />
            </div>
          )}
        </div>
      </section>

      {/* 参数 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">参数调节</h3>
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-medium text-slate-600 dark:text-white/80">
                Temperature
              </label>
              <span className="text-sm font-mono text-indigo-500">
                {config.temperature}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="2"
              step="0.1"
              value={config.temperature}
              onChange={(e) => setConfig((c) => ({ ...c, temperature: parseFloat(e.target.value) }))}
              className="w-full max-w-md accent-indigo-500"
            />
            <p className="text-xs text-slate-500 dark:text-white/50 mt-1">
              值越低回答越确定，值越高越有创造性
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-white/80 mb-2">
              Max Tokens
            </label>
            <input
              type="number"
              min="256"
              max="32768"
              step="256"
              value={config.max_tokens}
              onChange={(e) => setConfig((c) => ({ ...c, max_tokens: parseInt(e.target.value) || 4096 }))}
              className={[
                "w-full max-w-xs rounded-lg border",
                "border-slate-200 dark:border-white/10",
                "bg-white dark:bg-white/5 px-4 py-2.5 text-sm",
                "text-slate-800 dark:text-white",
                "focus:border-indigo-400 focus:outline-none",
              ].join(" ")}
            />
          </div>
        </div>
      </section>

      {/* 操作 */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={testConn}
          disabled={isTesting}
          className={[
            "flex items-center gap-2 rounded-lg border",
            "border-slate-200 dark:border-white/10",
            "bg-white dark:bg-white/5 px-4 py-2.5 text-sm",
            "text-slate-700 dark:text-white/80",
            "hover:bg-slate-50 dark:hover:bg-white/10",
            "transition-colors disabled:opacity-50",
          ].join(" ")}
        >
          {isTesting
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <AlertCircle className="w-4 h-4" />}
          <span>测试连接</span>
        </button>
        <button
          onClick={saveConfig}
          disabled={saveStatus === "saving"}
          className={[
            "flex items-center gap-2 rounded-lg",
            "bg-indigo-600 hover:bg-indigo-500",
            "px-4 py-2.5 text-sm text-white",
            "transition-colors disabled:opacity-50",
          ].join(" ")}
        >
          {saveStatus === "saving"
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <Check className="w-4 h-4" />}
          <span>{saveStatus === "saving" ? "保存中..." : "保存配置"}</span>
        </button>
        {saveStatus === "error" && (
          <span className="text-xs text-red-500">保存失败，请重试</span>
        )}
      </div>

      {/* 测试结果 */}
      {testResult && (
        <div
          className={[
            "rounded-lg border p-4",
            testResult.success
              ? "border-emerald-300 dark:border-emerald-500/50 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
              : "border-red-300 dark:border-red-500/50 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400",
          ].join(" ")}
        >
          <div className="flex items-center gap-2">
            {testResult.success
              ? <Check className="w-4 h-4" />
              : <AlertCircle className="w-4 h-4" />}
            <span className="text-sm">{testResult.message}</span>
          </div>
        </div>
      )}
    </div>
  );
}
