"use client";

import { useState, useCallback } from "react";
import { Trash2, RefreshCw, HardDrive, Database, AlertTriangle } from "lucide-react";
import { maintenanceApi } from "@/lib/api/maintenance";

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

function ActionRow({
  label, description, buttonLabel, buttonVariant = "default", loading, onClick,
}: {
  label: string; description?: string; buttonLabel: string;
  buttonVariant?: "default" | "danger"; loading?: boolean; onClick: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div>
        <div className="text-sm text-slate-700 dark:text-slate-200">{label}</div>
        {description && <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">{description}</div>}
      </div>
      <button
        onClick={onClick}
        disabled={loading}
        className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 ${
          buttonVariant === "danger"
            ? "border border-red-200 dark:border-red-500/30 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
            : "border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
        }`}
      >
        {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
        {buttonLabel}
      </button>
    </div>
  );
}


export function MaintenanceView() {
  const [gcLoading, setGcLoading] = useState(false);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [clearLoading, setClearLoading] = useState(false);
  const [result, setResult] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const showResult = (type: "success" | "error", message: string) => {
    setResult({ type, message });
    setTimeout(() => setResult(null), 4000);
  };

  const runGC = useCallback(async () => {
    setGcLoading(true);
    try {
      const res = await maintenanceApi.runGC();
      showResult("success", `GC 完成，清理 ${res.deleted_dirs} 个目录`);
    } catch (e: any) {
      showResult("error", e.message ?? "GC 失败");
    } finally { setGcLoading(false); }
  }, []);

  const runArchive = useCallback(async () => {
    setArchiveLoading(true);
    try {
      const res = await maintenanceApi.runArchive();
      showResult("success", `归档完成，共归档 ${res.archived_count} 条记录`);
    } catch (e: any) {
      showResult("error", e.message ?? "归档失败");
    } finally { setArchiveLoading(false); }
  }, []);

  const clearCache = useCallback(async () => {
    if (!confirm("确认清除所有缓存？此操作不可撤销。")) return;
    setClearLoading(true);
    try {
      await fetch("/api/v1/maintenance/clear-cache", { method: "POST" });
      showResult("success", "缓存已清除");
    } catch {
      showResult("error", "清除失败");
    } finally { setClearLoading(false); }
  }, []);

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-4 py-3">
        <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">系统维护</p>
          <p className="text-[11px] text-amber-600 dark:text-amber-400/80 mt-0.5">以下操作会影响系统数据，请在了解后果后执行</p>
        </div>
      </div>

      <SectionCard icon={Database} title="数据管理">
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          <ActionRow
            label="垃圾回收"
            description="清理孤立节点、过期缓存和临时文件"
            buttonLabel="运行 GC"
            loading={gcLoading}
            onClick={runGC}
          />
          <ActionRow
            label="归档旧任务"
            description="将 30 天前已完成的任务移入归档存储"
            buttonLabel="开始归档"
            loading={archiveLoading}
            onClick={runArchive}
          />
        </div>
      </SectionCard>

      <SectionCard icon={HardDrive} title="缓存管理">
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          <ActionRow
            label="清除计划缓存"
            description="删除所有已缓存的执行计划，下次执行将重新规划"
            buttonLabel="清除缓存"
            buttonVariant="danger"
            loading={clearLoading}
            onClick={clearCache}
          />
        </div>
      </SectionCard>

      <SectionCard icon={Trash2} title="危险操作">
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          <ActionRow
            label="重置所有设置"
            description="将所有配置恢复为默认值，不影响任务数据"
            buttonLabel="重置设置"
            buttonVariant="danger"
            onClick={async () => {
              if (!confirm("确认重置所有设置？")) return;
              try {
                await fetch("/api/v1/settings/reset", { method: "POST" });
                showResult("success", "设置已重置，请刷新页面");
              } catch { showResult("error", "重置失败"); }
            }}
          />
        </div>
      </SectionCard>

      {result && (
        <div className={`rounded-xl border px-4 py-3 text-xs font-medium ${
          result.type === "success"
            ? "border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
            : "border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400"
        }`}>
          {result.message}
        </div>
      )}
    </div>
  );
}
