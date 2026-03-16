"use client";

import { useState, useEffect, useCallback } from "react";
import {
  CheckCircle2, Clock, AlertTriangle, Zap, FileText, FolderOpen,
  Package, ExternalLink, XCircle, Loader2, Pause, Play, X, History,
} from "lucide-react";
import { historyApi, approvalApi, type SessionItem, type ArtifactRecord, type ApprovalHistoryRecord } from "@/lib/api/history";
import { scheduleApi } from "@/lib/api/schedule";
import { artifactApi } from "@/lib/api/history";
import { useSocket } from "@/components/providers/SocketProvider";
import { useTaskStore } from "@/stores/taskStore";
import { useWorkbenchStore } from "@/stores/workbenchStore";
import { cancelTask, pauseTask, resumeTask } from "@/lib/api/task";
import { deriveTaskControls } from "@/types/task";
import { cn } from "@/lib/utils";
import type { ApprovalRequest } from "@/types/chat";

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

function within24h(dateStr: string | null): boolean {
  if (!dateStr) return false;
  return Date.now() - new Date(dateStr).getTime() < 24 * 60 * 60 * 1000;
}

// ── 子组件 ────────────────────────────────────────────────────────────────────

function SectionHeader({ icon: Icon, title, count, subtitle }: {
  icon: any; title: string; count?: number; subtitle?: string;
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-4 h-4 text-slate-400" />
      <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">{title}</span>
      {subtitle && <span className="text-[10px] text-slate-400 dark:text-slate-600">{subtitle}</span>}
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
    <div className="flex items-center justify-center h-20 text-xs text-slate-400 dark:text-slate-600 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl">
      {text}
    </div>
  );
}

function RunningCard({ session, isActive, controlStatus, onPauseResume, onCancel, isActioning, onClick }: {
  session: SessionItem;
  isActive: boolean;
  controlStatus?: string;
  onPauseResume?: () => void;
  onCancel?: () => void;
  isActioning?: boolean;
  onClick?: () => void;
}) {
  const progress = session.total_nodes > 0
    ? Math.round((session.completed_nodes / session.total_nodes) * 100) : 0;
  const isPaused = controlStatus === "paused";

  return (
    <div
      onClick={onClick}
      className={cn(
        "p-3 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 hover:border-indigo-200 dark:hover:border-indigo-800 transition-colors",
        onClick && "cursor-pointer"
      )}
    >
      <div className="flex items-start gap-2 mb-2">
        {isPaused
          ? <div className="w-3.5 h-3.5 mt-0.5 shrink-0 rounded-full bg-amber-400" />
          : <Loader2 className="w-3.5 h-3.5 text-indigo-500 animate-spin mt-0.5 shrink-0" />
        }
        <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug line-clamp-2 flex-1">
          {session.goal || "执行中…"}
        </p>
      </div>
      <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1.5 mb-2">
        <div
          className={cn("h-1.5 rounded-full transition-all duration-500", isPaused ? "bg-amber-400" : "bg-indigo-500")}
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-[11px] text-slate-400 mb-2">
        <span>步骤 {session.completed_nodes + 1} / {session.total_nodes}</span>
        <span>{timeAgo(session.started_at)}</span>
      </div>
      {isActive && onPauseResume && onCancel && (
        <div className="flex gap-1.5 pt-1 border-t border-slate-100 dark:border-slate-800">
          <button
            onClick={(e) => { e.stopPropagation(); onPauseResume(); }}
            disabled={isActioning}
            className={cn(
              "flex-1 flex items-center justify-center gap-1 py-1 rounded text-[10px] font-medium transition-colors disabled:opacity-50",
              isPaused
                ? "bg-indigo-50 text-indigo-600 hover:bg-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-400"
                : "bg-amber-50 text-amber-600 hover:bg-amber-100 dark:bg-amber-500/10 dark:text-amber-400"
            )}
          >
            {isPaused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
            {isPaused ? "恢复" : "暂停"}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onCancel(); }}
            disabled={isActioning}
            className="flex-1 flex items-center justify-center gap-1 py-1 rounded text-[10px] font-medium transition-colors disabled:opacity-50 bg-red-50 text-red-500 hover:bg-red-100 dark:bg-red-500/10 dark:text-red-400"
          >
            <X className="w-3 h-3" />
            取消
          </button>
        </div>
      )}
    </div>
  );
}

// 没有运行中任务时，显示最近执行过的（灰色调）
function RecentRunCard({ session, onClick }: { session: SessionItem; onClick?: () => void }) {
  const failed = session.status === "failed" || session.result_status === "failed";
  return (
    <div
      onClick={onClick}
      className={cn(
        "p-3 rounded-xl bg-slate-50 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-800/60 transition-colors hover:border-slate-300 dark:hover:border-slate-700",
        onClick && "cursor-pointer"
      )}
    >
      <div className="flex items-start gap-2">
        {failed
          ? <XCircle className="w-3.5 h-3.5 text-red-300 mt-0.5 shrink-0" />
          : <CheckCircle2 className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
        }
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-500 dark:text-slate-400 leading-snug line-clamp-2">{session.goal || "任务"}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[11px] text-slate-400">{timeAgo(session.completed_at)}</span>
            {session.total_nodes > 0 && (
              <span className="text-[11px] text-slate-400">{session.completed_nodes} 步</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ResultCard({ session, onClick }: { session: SessionItem; onClick?: () => void }) {
  const failed = session.status === "failed" || session.result_status === "failed";
  const isRecent = within24h(session.completed_at);
  return (
    <div
      onClick={onClick}
      className={cn(
        "p-3 rounded-xl bg-white dark:bg-slate-900 border transition-colors hover:border-indigo-200 dark:hover:border-indigo-800",
        isRecent ? "border-slate-100 dark:border-slate-800" : "border-slate-100/60 dark:border-slate-800/60 opacity-75",
        onClick && "cursor-pointer"
      )}
    >
      <div className="flex items-start gap-2">
        {failed
          ? <XCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
          : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 mt-0.5 shrink-0" />
        }
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug line-clamp-2">{session.goal || "任务"}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-[11px] font-medium ${failed ? "text-red-400" : "text-emerald-500"}`}>
              {failed ? "失败" : "成功"}
            </span>
            <span className="text-[11px] text-slate-400">{timeAgo(session.completed_at)}</span>
            {!isRecent && <span className="text-[10px] text-slate-300 dark:text-slate-600">24h 前</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

function PendingApprovalCard({ req, onRespond }: { req: ApprovalRequest; onRespond: (id: string, approved: boolean) => void }) {
  const [loading, setLoading] = useState(false);
  const handle = async (approved: boolean) => {
    setLoading(true);
    await onRespond(req.request_id, approved);
    setLoading(false);
  };
  return (
    <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50">
      <div className="flex items-start gap-2 mb-1.5">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug line-clamp-2">{req.message}</p>
          <p className="text-[10px] font-mono text-slate-400 mt-0.5 truncate">{req.operation}</p>
        </div>
      </div>
      <div className="flex gap-2">
        <button onClick={() => handle(true)} disabled={loading}
          className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white transition-colors disabled:opacity-50">
          批准
        </button>
        <button onClick={() => handle(false)} disabled={loading}
          className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-slate-200 dark:bg-slate-700 hover:bg-red-100 dark:hover:bg-red-900/30 text-slate-600 dark:text-slate-300 hover:text-red-600 transition-colors disabled:opacity-50">
          拒绝
        </button>
      </div>
    </div>
  );
}

// 历史审批记录卡片（无待确认时的兜底）
function ApprovalHistoryCard({ record }: { record: ApprovalHistoryRecord }) {
  const approved = record.status === "approved";
  return (
    <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-800/60">
      <div className="flex items-start gap-2">
        {approved
          ? <CheckCircle2 className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
          : <XCircle className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
        }
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-500 dark:text-slate-400 leading-snug line-clamp-2">{record.message}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-[11px] font-medium ${approved ? "text-slate-400" : "text-slate-400"}`}>
              {approved ? "已批准" : "已拒绝"}
            </span>
            <span className="text-[11px] text-slate-400">{timeAgo(record.responded_at || record.created_at)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ArtifactCard({ artifact }: { artifact: ArtifactRecord }) {
  const Icon = fileIcon(artifact.filename);
  const downloadUrl = artifactApi.downloadUrl(artifact.artifact_id);
  return (
    <div className="flex-shrink-0 w-48 p-3 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 hover:border-indigo-200 dark:hover:border-indigo-800 transition-colors">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-950/50 flex items-center justify-center shrink-0">
          <Icon className="w-3.5 h-3.5 text-indigo-500" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-700 dark:text-slate-200 truncate">{artifact.filename}</p>
          <p className="text-[11px] text-slate-400">{formatBytes(artifact.size)}</p>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-slate-400">{timeAgo(artifact.created_at)}</span>
        <a href={downloadUrl} target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-1 text-[11px] text-indigo-500 hover:text-indigo-600 font-medium">
          打开 <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────────────────────────

export function OverviewTab() {
  const { isConnected } = useSocket();
  const { activeTask, controlStatus, setIsCancelling, pendingApprovals, removePendingApproval } = useTaskStore();
  const { setActiveTab } = useWorkbenchStore();
  const { canPause, canResume, canCancel } = deriveTaskControls(activeTask?.status as any ?? "executing", controlStatus);

  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [approvalHistory, setApprovalHistory] = useState<ApprovalHistoryRecord[]>([]);
  const [nextSchedule, setNextSchedule] = useState<string>("--:--");
  const [loading, setLoading] = useState(true);
  const [isActioning, setIsActioning] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [sessionList, scheduleList, approvalList] = await Promise.allSettled([
        historyApi.listSessions(50),
        scheduleApi.listSchedules(),
        approvalApi.getHistory(undefined, 10),
      ]);

      if (sessionList.status === "fulfilled") {
        setSessions(sessionList.value);
        const recentCompleted = sessionList.value.filter(s => s.status === "completed").slice(0, 5);
        const artifactResults = await Promise.allSettled(recentCompleted.map(s => historyApi.getArtifacts(s.id)));
        const allArtifacts: ArtifactRecord[] = [];
        artifactResults.forEach(r => {
          if (r.status === "fulfilled") r.value.artifacts.forEach(a => allArtifacts.push({
            artifact_id: a.artifact_id, step_id: a.step_id, filename: a.filename,
            size: a.size, mime_type: a.mime_type, artifact_type: a.artifact_type, created_at: a.created_at,
          }));
        });
        allArtifacts.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        setArtifacts(allArtifacts.slice(0, 10));
      }

      if (approvalList.status === "fulfilled") {
        setApprovalHistory(approvalList.value.records);
      }

      if (scheduleList.status === "fulfilled") {
        const upcoming = scheduleList.value
          .filter(s => s.is_active && s.next_run_at)
          .map(s => new Date(s.next_run_at!).getTime()).sort((a, b) => a - b);
        if (upcoming.length > 0) {
          const d = new Date(upcoming[0]);
          setNextSchedule(`${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`);
        }
      }
    } catch (e) {
      console.error("Overview fetch error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const running = sessions.filter(s => s.status === "running");
  const runningCount = running.length;
  useEffect(() => {
    const interval = setInterval(fetchData, runningCount > 0 ? 10000 : 30000);
    return () => clearInterval(interval);
  }, [fetchData, runningCount]);

  // 最近执行过的（running 为空时的兜底）
  const recentRan = sessions
    .filter(s => s.status === "completed" || s.status === "failed")
    .slice(0, 5);

  // 最近结果：优先 24h 内，不足 3 条往前补到 3 条
  const allDone = sessions.filter(s => s.status === "completed" || s.status === "failed");
  const done24h = allDone.filter(s => within24h(s.completed_at));
  const recent = done24h.length >= 3 ? done24h : allDone.slice(0, Math.max(3, done24h.length));

  const todayCompleted = sessions.filter(s => {
    if (s.status !== "completed" || !s.completed_at) return false;
    const d = new Date(s.completed_at), now = new Date();
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  }).length;

  const handlePauseResume = async () => {
    if (isActioning || !activeTask) return;
    setIsActioning(true);
    try {
      if (canResume) await resumeTask(activeTask.id);
      else if (canPause) await pauseTask(activeTask.id);
    } catch (e) { console.error("pause/resume failed", e); }
    finally { setIsActioning(false); }
  };

  const handleCancel = async () => {
    if (isActioning || !canCancel || !activeTask) return;
    setIsActioning(true);
    setIsCancelling(true);
    try { await cancelTask(activeTask.id); }
    catch (e) { console.error("cancel failed", e); setIsCancelling(false); }
    finally { setIsActioning(false); }
  };

  const handleApprovalRespond = async (id: string, approved: boolean) => {
    await approvalApi.respond(id, approved);
    removePendingApproval(id);
  };

  const summary = (() => {
    const parts: string[] = [];
    if (todayCompleted > 0) parts.push(`今天已完成 ${todayCompleted} 项任务`);
    if (running.length > 0) parts.push(`${running.length} 项正在执行`);
    if (pendingApprovals.length > 0) parts.push(`${pendingApprovals.length} 项等待确认`);
    return parts.length === 0 ? "系统待机中，随时准备执行任务。" : parts.join("，") + "。";
  })();

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-950 overflow-hidden">
      {/* 状态栏 */}
      <div className="shrink-0 px-5 py-3 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-4 mb-1">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              {running.length > 0 && isConnected && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              )}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${!isConnected ? "bg-slate-400" : "bg-emerald-500"}`} />
            </span>
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">Overview</span>
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
            <span className="flex items-center gap-1">
              <Zap className="w-3 h-3 text-indigo-400" />
              运行中 <strong className="text-slate-700 dark:text-slate-200">{loading ? "…" : running.length}</strong>
            </span>
            <span className="flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3 text-emerald-400" />
              今日完成 <strong className="text-slate-700 dark:text-slate-200">{loading ? "…" : todayCompleted}</strong>
            </span>
            <span className="flex items-center gap-1">
              <AlertTriangle className="w-3 h-3 text-amber-400" />
              待确认 <strong className="text-slate-700 dark:text-slate-200">{pendingApprovals.length}</strong>
            </span>
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3 text-purple-400" />
              下次调度 <strong className="text-slate-700 dark:text-slate-200">{loading ? "…" : nextSchedule}</strong>
            </span>
          </div>
        </div>
        <p className="text-xs text-slate-400 dark:text-slate-500">{loading ? "加载中…" : summary}</p>
      </div>

      {/* 内容区：三列独立滚动 + 底部最近交付固定 */}
      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        {/* 三列区域，各自独立滚动 */}
        <div className="flex-1 min-h-0 px-5 pt-5 grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* 正在执行 / 最近执行 */}
          <div className="flex flex-col min-h-0">
            {running.length > 0 ? (
              <SectionHeader icon={Zap} title="正在执行" count={running.length} />
            ) : (
              <SectionHeader icon={History} title="最近执行" subtitle="无运行中任务" />
            )}
            <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-0.5">
              {running.length > 0
                ? running.map(s => (
                    <RunningCard
                      key={s.id}
                      session={s}
                      isActive={activeTask?.id === s.id}
                      controlStatus={activeTask?.id === s.id ? controlStatus : undefined}
                      onPauseResume={activeTask?.id === s.id ? handlePauseResume : undefined}
                      onCancel={activeTask?.id === s.id ? handleCancel : undefined}
                      isActioning={isActioning}
                      onClick={() => setActiveTab("active")}
                    />
                  ))
                : recentRan.length === 0
                  ? <EmptyState text="暂无执行记录" />
                  : recentRan.map(s => (
                      <RecentRunCard key={s.id} session={s} onClick={() => setActiveTab("history")} />
                    ))
              }
            </div>
          </div>

          {/* 待确认 / 历史审批 */}
          <div className="flex flex-col min-h-0">
            {pendingApprovals.length > 0 ? (
              <SectionHeader icon={AlertTriangle} title="待确认" count={pendingApprovals.length} />
            ) : (
              <SectionHeader icon={History} title="历史审批" subtitle="无待确认项" />
            )}
            <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-0.5">
              {pendingApprovals.length > 0
                ? pendingApprovals.map(a => (
                    <PendingApprovalCard key={a.request_id} req={a} onRespond={handleApprovalRespond} />
                  ))
                : approvalHistory.length === 0
                  ? <EmptyState text="暂无审批记录" />
                  : approvalHistory.slice(0, 5).map(r => (
                      <ApprovalHistoryCard key={r.request_id} record={r} />
                    ))
              }
            </div>
          </div>

          {/* 最近结果 */}
          <div className="flex flex-col min-h-0">
            <SectionHeader
              icon={CheckCircle2}
              title="最近结果"
              count={recent.length}
              subtitle={done24h.length < 3 ? "含 24h 前" : undefined}
            />
            <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-0.5">
              {recent.length === 0
                ? <EmptyState text="暂无历史记录" />
                : recent.map(s => (
                    <ResultCard key={s.id} session={s} onClick={() => setActiveTab("history")} />
                  ))
              }
            </div>
          </div>

        </div>

        {/* 最近交付：固定在底部，不被三列内容撑走 */}
        <div className="shrink-0 px-5 py-4 border-t border-slate-100 dark:border-slate-800">
          <SectionHeader icon={Package} title="最近交付" count={artifacts.length} />
          {artifacts.length === 0
            ? <EmptyState text="暂无交付文件" />
            : <div className="flex gap-3 overflow-x-auto scrollbar-hide pb-1">{artifacts.map(a => <ArtifactCard key={a.artifact_id} artifact={a} />)}</div>
          }
        </div>
      </div>
    </div>
  );
}
