"use client";

import { useState } from "react";
import { useLanguage } from "@/theme/i18n/LanguageContext";

export function GeneralSettings() {
  const { language, setLanguage } = useLanguage();
  const [theme, setTheme] = useState<"dark" | "light" | "auto">("dark");

  return (
    <div className="space-y-6 min-h-full">
      {/* 语言设置 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">语言与地区</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-white/80 mb-2">
              界面语言
            </label>
            <select 
              value={language}
              onChange={(e) => setLanguage(e.target.value as 'zh' | 'en')}
              className="w-full max-w-md rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 px-4 py-2.5 text-sm text-slate-800 dark:text-white focus:border-indigo-400 focus:outline-none"
            >
              <option value="zh">简体中文</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>
      </section>

      {/* 主题设置 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">外观主题</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-600 dark:text-white/80 mb-2">
              主题模式
            </label>
            <div className="flex gap-3">
              <button 
                onClick={() => setTheme("dark")}
                className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-all ${
                  theme === "dark"
                    ? "border-indigo-400 dark:border-indigo-500/50 bg-indigo-50 dark:bg-indigo-500/20 text-indigo-700 dark:text-white"
                    : "border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 text-slate-600 dark:text-white/70 hover:bg-slate-50 dark:hover:bg-white/10"
                }`}
              >
                <span>🌙</span>
                <span>深色模式</span>
              </button>
              <button 
                onClick={() => setTheme("light")}
                className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-all ${
                  theme === "light"
                    ? "border-indigo-400 dark:border-indigo-500/50 bg-indigo-50 dark:bg-indigo-500/20 text-indigo-700 dark:text-white"
                    : "border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 text-slate-600 dark:text-white/70 hover:bg-slate-50 dark:hover:bg-white/10"
                }`}
              >
                <span>☀️</span>
                <span>浅色模式</span>
              </button>
              <button 
                onClick={() => setTheme("auto")}
                className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-all ${
                  theme === "auto"
                    ? "border-indigo-400 dark:border-indigo-500/50 bg-indigo-50 dark:bg-indigo-500/20 text-indigo-700 dark:text-white"
                    : "border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 text-slate-600 dark:text-white/70 hover:bg-slate-50 dark:hover:bg-white/10"
                }`}
              >
                <span>🌓</span>
                <span>自动切换</span>
              </button>
            </div>
            <p className="text-xs text-slate-500 dark:text-white/50 mt-2">
              {theme === "auto" ? "根据系统设置自动切换" : theme === "dark" ? "当前使用深色模式" : "当前使用浅色模式"}
            </p>
          </div>
        </div>
      </section>

      {/* 聊天设置 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">聊天设置</h3>
        <div className="space-y-3">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500"
              defaultChecked
            />
            <span className="text-sm text-slate-700 dark:text-white/80">启用流式输出</span>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500"
              defaultChecked
            />
            <span className="text-sm text-slate-700 dark:text-white/80">保存聊天历史</span>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500"
            />
            <span className="text-sm text-slate-700 dark:text-white/80">发送消息时播放提示音</span>
          </label>
        </div>
      </section>
    </div>
  );
}
