"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

export function AdvancedSettings() {
  const [maxReplanAttempts, setMaxReplanAttempts] = useState(2);
  const [workspacePath, setWorkspacePath] = useState("./workspace");

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
              value={maxReplanAttempts}
              onChange={(e) => setMaxReplanAttempts(parseInt(e.target.value))}
              className="w-full max-w-xs rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 px-4 py-2.5 text-sm text-slate-800 dark:text-white focus:border-indigo-400 focus:outline-none"
            />
            <p className="text-xs text-slate-500 dark:text-white/50 mt-1">
              当任务执行失败时，Agent 会尝试重新规划的次数（0-5）
            </p>
          </div>

          <div className="space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500" defaultChecked />
              <span className="text-sm text-slate-700 dark:text-white/80">启用自纠错机制</span>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500" defaultChecked />
              <span className="text-sm text-slate-700 dark:text-white/80">启用上下文记忆</span>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500" />
              <span className="text-sm text-slate-700 dark:text-white/80">启用详细日志</span>
            </label>
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
            <input
              type="text"
              value={workspacePath}
              onChange={(e) => setWorkspacePath(e.target.value)}
              placeholder="./workspace"
              className="w-full rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-white/5 px-4 py-2.5 text-sm text-slate-800 dark:text-white placeholder:text-slate-400 dark:placeholder:text-white/40 focus:border-indigo-400 focus:outline-none"
            />
            <p className="text-xs text-slate-500 dark:text-white/50 mt-1">
              Agent 执行任务时的工作目录，所有文件操作都在此目录下进行
            </p>
          </div>
        </div>
      </section>

      {/* 性能优化 */}
      <section className="rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-6">
        <h3 className="text-lg font-semibold text-slate-800 dark:text-white mb-4">性能优化</h3>
        <div className="space-y-3">
          <label className="flex items-center gap-3 cursor-pointer">
            <input type="checkbox" className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500" defaultChecked />
            <span className="text-sm text-slate-700 dark:text-white/80">启用计划缓存</span>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input type="checkbox" className="h-4 w-4 rounded border-slate-300 dark:border-white/10 bg-white dark:bg-white/5 text-indigo-500 focus:ring-indigo-500" />
            <span className="text-sm text-slate-700 dark:text-white/80">启用并行执行（实验性）</span>
          </label>
        </div>
      </section>

      {/* 危险操作 */}
      <section className="rounded-xl border border-red-300 dark:border-red-500/50 bg-red-50 dark:bg-red-500/10 p-6">
        <h3 className="text-lg font-semibold text-red-600 dark:text-red-300 mb-4">危险操作</h3>
        <div className="space-y-3">
          <button className="w-full rounded-lg border border-red-300 dark:border-red-500/50 bg-red-100 dark:bg-red-500/20 px-4 py-2.5 text-sm text-red-600 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-500/30 transition-colors">
            清除所有缓存
          </button>
          <button className="w-full rounded-lg border border-red-300 dark:border-red-500/50 bg-red-100 dark:bg-red-500/20 px-4 py-2.5 text-sm text-red-600 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-500/30 transition-colors">
            重置所有设置
          </button>
        </div>
      </section>
    </div>
  );
}
