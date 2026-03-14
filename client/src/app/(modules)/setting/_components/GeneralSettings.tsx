"use client";

import { Globe, Palette, MessageSquare } from "lucide-react";
import { useLanguage } from "@/theme/i18n/LanguageContext";
import { useTheme } from "next-themes";

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

function Toggle({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  return (
    <label className="flex items-center justify-between gap-4 cursor-pointer py-1">
      <div>
        <div className="text-sm text-slate-700 dark:text-slate-200">{label}</div>
        {description && <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{description}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
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

const THEME_OPTIONS = [
  { value: "dark",   label: "深色",   icon: "🌙" },
  { value: "light",  label: "浅色",   icon: "☀️" },
  { value: "system", label: "跟随系统", icon: "🌓" },
];

const LANG_OPTIONS = [
  { value: "zh", label: "简体中文" },
  { value: "en", label: "English" },
];

export function GeneralSettings() {
  const { language, setLanguage } = useLanguage();
  const { theme, setTheme } = useTheme();

  return (
    <div className="space-y-3">
      {/* 语言 */}
      <SectionCard icon={Globe} title="语言与地区">
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">界面语言</label>
          <div className="flex gap-2">
            {LANG_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setLanguage(opt.value as "zh" | "en")}
                className={`px-4 py-2 rounded-lg text-sm font-medium border transition-all ${
                  language === opt.value
                    ? "border-indigo-400 bg-indigo-50 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300"
                    : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:border-slate-300 dark:hover:border-slate-600"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </SectionCard>

      {/* 主题 */}
      <SectionCard icon={Palette} title="外观主题">
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">主题模式</label>
          <div className="flex gap-2">
            {THEME_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setTheme(opt.value)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-all ${
                  theme === opt.value
                    ? "border-indigo-400 bg-indigo-50 dark:bg-indigo-500/20 text-indigo-700 dark:text-indigo-300"
                    : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:border-slate-300 dark:hover:border-slate-600"
                }`}
              >
                <span>{opt.icon}</span>
                <span>{opt.label}</span>
              </button>
            ))}
          </div>
          <p className="text-[11px] text-slate-400 dark:text-slate-500">
            {theme === "system" ? "根据系统设置自动切换" : theme === "dark" ? "当前使用深色模式" : "当前使用浅色模式"}
          </p>
        </div>
      </SectionCard>

      {/* 聊天 */}
      <SectionCard icon={MessageSquare} title="聊天设置">
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          <div className="pb-3">
            <Toggle checked={true} onChange={() => {}} label="启用流式输出" description="实时显示 AI 回复内容" />
          </div>
          <div className="py-3">
            <Toggle checked={true} onChange={() => {}} label="保存聊天历史" description="关闭后刷新页面将清除记录" />
          </div>
          <div className="pt-3">
            <Toggle checked={false} onChange={() => {}} label="发送消息时播放提示音" />
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
