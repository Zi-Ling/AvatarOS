"use client";

import { useRouter, usePathname } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  Zap,
  FileText,
  FolderOpen,
  Package,
  ExternalLink,
  Pin,
  PinOff,
  XCircle,
  Loader2,
  Wifi,
  WifiOff,
} from "lucide-react";
import { APP_REGISTRY } from "@/lib/apps";
import { useDockApps } from "@/lib/hooks/useDockApps";
import { historyApi, approvalApi, type SessionItem, type ApprovalHistoryRecord, type ArtifactRecord } from "@/lib/api/history";
import { scheduleApi } from "@/lib/api/schedule";
import { artifactApi } from "@/lib/api/history";
import { useSocket } from "@/components/providers/SocketProvider";

// ── 工具函数 ──────────────────────────────────────────────────────────────────

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

function fileIcon(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase();
  if (["pdf", "doc", "docx", "md", "txt"].includes(ext || "")) return FileText;
  if (["zip", "tar", "gz"].includes(ext || "")) return Package;
  return FolderOpen;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── 子组件 ────────────────────────────────────────────────────────────────────

function StatusDot({ active, isConnected }: { active: boolean; isConnected: boolean }) {
  const color = !isConnected ? "bg-slate-400" : active ? "bg-emerald-500" : "bg-emerald-500";
  const label = !isConnected ? "离线" : active ? "执行中" : "待机";

  return (
    <span className="relative flex h-2.5 w-2.5" title={label}>
      {(active && isConnected) && (
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
      )}
      <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${color}`} />
    </span>
  );
}

function SectionHeader({ icon: Icon, title, count }: { icon: any; title: string; count?: number }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-4 h-4 text-slate-400" />
      <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">{title}</span>
      {count !== undefined && (
        <span className="ml-auto text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 px-2 py-0.5 rounded-full">
          {count}
        </span>
      )}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center h-24 text-xs text-slate-400 dark:text-slate-600 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl">
      {text}
    </div>
  );
}

function RunningCard({ session }: { session: SessionItem }) {
  const progress = session.total_nodes > 0
    ? Math.round((session.completed_nodes / session.total_nodes) * 100)
    : 0;
  const currentStep = session.completed_nodes + 1;

  return (
    <div className="p-3 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 hover:border-indigo-200 dark:hover:border-indigo-800 transition-colors">
      <div className="flex items-start gap-2 mb-2">
        <Loader2 className="w-3.5 h-3.5 text-indigo-500 animate-spin mt-0.5 shrink-0" />
        <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug line-clamp-2">
          {session.goal || "执行中…"}
        </p>
      </div>
      <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1.5 mb-1.5">
        <div
          className="bg-indigo-500 h-1.5 rounded-full transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-[11px] text-slate-400">
        <span>步骤 {currentStep} / {session.total_nodes}</span>
        <span>{timeAgo(session.started_at)}</span>
      </div>
    </div>
  );
}

function ResultCard({ session }: { session: SessionItem }) {
  const success = session.result_status === "success" || session.status === "completed";
  const failed = session.status === "failed" || session.result_status === "failed";

  return (
    <div className="p-3 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 transition-colors">
      <div className="flex items-start gap-2">
        {failed
          ? <XCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
          : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 mt-0.5 shrink-0" />
        }
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug line-clamp-2">
            {session.goal || "任务"}
          </p>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-[11px] font-medium ${failed ? "text-red-400" : "text-emerald-500"}`}>
              {failed ? "失败" : "成功"}
            </span>
            <span className="text-[11px] text-slate-400">{timeAgo(session.completed_at)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ApprovalCard({ record, onRespond }: { record: ApprovalHistoryRecord; onRespond: (id: string, approved: boolean) => void }) {
  const [loading, setLoading] = useState(false);

  const handle = async (approved: boolean) => {
    setLoading(true);
    await onRespond(record.request_id, approved);
    setLoading(false);
  };

  return (
    <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50 transition-colors">
      <div className="flex items-start gap-2 mb-2">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
        <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug line-clamp-2">
          {record.message || record.operation}
        </p>
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => handle(true)}
          disabled={loading}
          className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white transition-colors disabled:opacity-50"
        >
          批准
        </button>
        <button
          onClick={() => handle(false)}
          disabled={loading}
          className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-slate-200 dark:bg-slate-700 hover:bg-red-100 dark:hover:bg-red-900/30 text-slate-600 dark:text-slate-300 hover:text-red-600 dark:hover:text-red-400 transition-colors disabled:opacity-50"
        >
          拒绝
        </button>
      </div>
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: ArtifactRecord }) {
  const Icon = fileIcon(artifact.filename);
  const downloadUrl = artifactApi.downloadUrl(artifact.artifact_id);

  return (
    <div className="flex-shrink-0 w-52 p-3 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 hover:border-indigo-200 dark:hover:border-indigo-800 transition-colors">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-8 h-8 rounded-lg bg-indigo-50 dark:bg-indigo-950/50 flex items-center justify-center shrink-0">
          <Icon className="w-4 h-4 text-indigo-500" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-700 dark:text-slate-200 truncate">{artifact.filename}</p>
          <p className="text-[11px] text-slate-400">{formatBytes(artifact.size)}</p>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-slate-400">{timeAgo(artifact.created_at)}</span>
        <a
          href={downloadUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-[11px] text-indigo-500 hover:text-indigo-600 font-medium"
        >
          打开 <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </div>
  );
}

function AppShortcut({ app, isPinned, onPinToggle, onClick, isAvatarEnabled, onAvatarToggle }: any) {
  const Icon = app.icon;
  const isAvatar = app.id === "avatar";

  return (
    <div className="relative group">
      <button
        onClick={isAvatar ? onAvatarToggle : onClick}
        disabled={app.comingSoon}
        className={`flex flex-col items-center gap-1.5 px-3 py-2 rounded-xl transition-all
          ${isAvatar && isAvatarEnabled
            ? "bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400"
            : "hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400"
          }
          ${app.comingSoon ? "opacity-40 cursor-not-allowed" : ""}
        `}
      >
        <Icon className="w-5 h-5" />
        <span className="text-[11px] font-medium whitespace-nowrap">{app.label}</span>
      </button>
      {!app.comingSoon && (
        <button
          onClick={(e) => { e.stopPropagation(); onPinToggle(); }}
          className="absolute -top-1 -right-1 p-1 rounded-full bg-white dark:bg-slate-800 shadow opacity-0 group-hover:opacity-100 transition-opacity"
        >
          {isPinned
            ? <PinOff className="w-2.5 h-2.5 text-indigo-500" />
            : <Pin className="w-2.5 h-2.5 text-slate-400" />
          }
        </button>
      )}
    </div>
  );
}

// ── 主页面 ────────────────────────────────────────────────────────────────────

export default function HomePage() {
  const router = useRouter();
  const pathname = usePathname();
  const { isPinned, togglePin } = useDockApps();
  const { isConnected } = useSocket();
  // embedded = 嵌入在 MainShell 中间面板（chat 页空状态），不显示底部快捷栏
  const isEmbedded = pathname === '/chat';

  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [approvals, setApprovals] = useState<ApprovalHistoryRecord[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [nextSchedule, setNextSchedule] = useState<string>("--:--");
  const [loading, setLoading] = useState(true);
  const [isAvatarEnabled, setIsAvatarEnabled] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [sessionList, scheduleList, approvalRes] = await Promise.allSettled([
        historyApi.listSessions(30),
        scheduleApi.listSchedules(),
        approvalApi.getHistory("pending", 10),
      ]);

      if (sessionList.status === "fulfilled") {
        setSessions(sessionList.value);

        // 取最近完成 session 的 artifacts
        const recentCompleted = sessionList.value
          .filter(s => s.status === "completed")
          .slice(0, 5);

        const artifactResults = await Promise.allSettled(
          recentCompleted.map(s => historyApi.getArtifacts(s.id))
        );

        const allArtifacts: ArtifactRecord[] = [];
        artifactResults.forEach(r => {
          if (r.status === "fulfilled") {
            r.value.artifacts.forEach(a => {
              allArtifacts.push({
                artifact_id: a.artifact_id,
                step_id: a.step_id,
                filename: a.filename,
                size: a.size,
                mime_type: a.mime_type,
                artifact_type: a.artifact_type,
                created_at: a.created_at,
              });
            });
          }
        });

        // 按时间排序，取最新 10 个
        allArtifacts.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        setArtifacts(allArtifacts.slice(0, 10));
      }

      if (scheduleList.status === "fulfilled") {
        const upcoming = scheduleList.value
          .filter(s => s.is_active && s.next_run_at)
          .map(s => new Date(s.next_run_at!).getTime())
          .sort((a, b) => a - b);
        if (upcoming.length > 0) {
          const d = new Date(upcoming[0]);
          setNextSchedule(`${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`);
        }
      }

      if (approvalRes.status === "fulfilled") {
        setApprovals(approvalRes.value.records);
      }
    } catch (e) {
      console.error("Dashboard fetch error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // 有 running 任务时 10s 轮询，否则 30s
  const runningCount = sessions.filter(s => s.status === "running").length;
  useEffect(() => {
    const interval = setInterval(fetchData, runningCount > 0 ? 10000 : 30000);
    return () => clearInterval(interval);
  }, [fetchData, runningCount]);

  useEffect(() => {
    const check = async () => {
      const api = (window as any).electronAPI;
      if (api?.isFloatingWindowVisible) {
        setIsAvatarEnabled(await api.isFloatingWindowVisible());
      }
    };
    check();
  }, []);

  const handleAvatarToggle = async () => {
    const api = (window as any).electronAPI;
    if (api?.toggleFloatingWindow) {
      setIsAvatarEnabled(await api.toggleFloatingWindow());
    }
  };

  const handleApprovalRespond = async (id: string, approved: boolean) => {
    await approvalApi.respond(id, approved);
    setApprovals(prev => prev.filter(a => a.request_id !== id));
  };

  // 派生数据
  const running = sessions.filter(s => s.status === "running");
  const recent = sessions.filter(s => s.status === "completed" || s.status === "failed").slice(0, 5);
  const todayCompleted = sessions.filter(s => {
    if (s.status !== "completed") return false;
    if (!s.completed_at) return false;
    const d = new Date(s.completed_at);
    const now = new Date();
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  }).length;

  // 自然语言摘要
  const summary = (() => {
    const parts: string[] = [];
    if (todayCompleted > 0) parts.push(`今天已完成 ${todayCompleted} 项任务`);
    if (running.length > 0) parts.push(`${running.length} 项正在执行`);
    if (approvals.length > 0) parts.push(`${approvals.length} 项等待确认`);
    if (parts.length === 0) return "系统待机中，随时准备执行任务。";
    return parts.join("，") + "。";
  })();

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-950 overflow-hidden">

      {/* 顶部状态栏 */}
      <div className="shrink-0 px-6 py-4 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-6 mb-2">
          <div className="flex items-center gap-2">
            <StatusDot active={running.length > 0} isConnected={isConnected} />
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">
              Avatar OS
            </span>
          </div>
          <div className="flex items-center gap-5 text-xs text-slate-500 dark:text-slate-400">
            <span className="flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-indigo-400" />
              正在运行 <strong className="text-slate-700 dark:text-slate-200">{loading ? "…" : running.length}</strong>
            </span>
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              今日完成 <strong className="text-slate-700 dark:text-slate-200">{loading ? "…" : todayCompleted}</strong>
            </span>
            <span className="flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              待确认 <strong className="text-slate-700 dark:text-slate-200">{loading ? "…" : approvals.length}</strong>
            </span>
            <span className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-purple-400" />
              下次调度 <strong className="text-slate-700 dark:text-slate-200">{loading ? "…" : nextSchedule}</strong>
            </span>
          </div>
        </div>
        <p className="text-xs text-slate-400 dark:text-slate-500">{loading ? "加载中…" : summary}</p>
      </div>

      {/* 主内容区（可滚动） */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-6">

          {/* 三栏 */}
          <div className="grid grid-cols-3 gap-4">

            {/* 正在执行 */}
            <div>
              <SectionHeader icon={Zap} title="正在执行" count={running.length} />
              <div className="space-y-2">
                {running.length === 0
                  ? <EmptyState text="暂无运行中的任务" />
                  : running.slice(0, 5).map(s => <RunningCard key={s.id} session={s} />)
                }
              </div>
            </div>

            {/* 最近结果 */}
            <div>
              <SectionHeader icon={CheckCircle2} title="最近结果" count={recent.length} />
              <div className="space-y-2">
                {recent.length === 0
                  ? <EmptyState text="暂无历史记录" />
                  : recent.map(s => <ResultCard key={s.id} session={s} />)
                }
              </div>
            </div>

            {/* 待确认 */}
            <div>
              <SectionHeader icon={AlertTriangle} title="待确认" count={approvals.length} />
              <div className="space-y-2">
                {approvals.length === 0
                  ? <EmptyState text="暂无待确认项" />
                  : approvals.slice(0, 5).map(a => (
                    <ApprovalCard key={a.request_id} record={a} onRespond={handleApprovalRespond} />
                  ))
                }
              </div>
            </div>

          </div>

          {/* 最近交付 */}
          <div>
            <SectionHeader icon={Package} title="最近交付" count={artifacts.length} />
            {artifacts.length === 0
              ? <EmptyState text="暂无交付文件" />
              : (
                <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-slate-200 dark:scrollbar-thumb-slate-700">
                  {artifacts.map(a => <ArtifactCard key={a.artifact_id} artifact={a} />)}
                </div>
              )
            }
          </div>

        </div>
      </div>

      {/* 底部快捷入口：仅在独立路由 /home 下显示，embedded 模式下 Dock 已提供导航 */}
      {!isEmbedded && (
        <div className="shrink-0 px-6 py-3 bg-white dark:bg-slate-900 border-t border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-1">
            {APP_REGISTRY.map(app => (
              <AppShortcut
                key={app.id}
                app={app}
                isPinned={isPinned(app.id)}
                onPinToggle={() => togglePin(app.id)}
                onClick={() => !app.comingSoon && app.path && router.push(app.path)}
                isAvatarEnabled={isAvatarEnabled}
                onAvatarToggle={handleAvatarToggle}
              />
            ))}
          </div>
        </div>
      )}

    </div>
  );
}
