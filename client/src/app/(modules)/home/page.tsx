"use client";

import { useRouter, usePathname } from "next/navigation";
import { useState, useEffect, useCallback, useMemo } from "react";
import {
  CheckCircle2, Clock, AlertTriangle, Zap, FileText, FolderOpen,
  Package, ExternalLink, Pin, PinOff, XCircle, Loader2,
} from "lucide-react";
import { motion } from "framer-motion";
import { APP_REGISTRY } from "@/lib/apps";
import { useDockApps } from "@/lib/hooks/useDockApps";
import { historyApi, approvalApi, type SessionItem, type ApprovalHistoryRecord, type ArtifactRecord } from "@/lib/api/history";
import { scheduleApi } from "@/lib/api/schedule";
import { artifactApi } from "@/lib/api/history";
import { useSocket } from "@/components/providers/SocketProvider";
import { cn } from "@/lib/utils";

// ── Helpers ──────────────────────────────────────────────────────────────────

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

// ── Activity Ring ────────────────────────────────────────────────────────────

function ActivityRing({ value, max, color, size = 90, strokeWidth = 7, label, sublabel }: {
  value: number; max: number; color: string; size?: number;
  strokeWidth?: number; label: string; sublabel?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = max > 0 ? Math.min(value / max, 1) : 0;
  const offset = circumference * (1 - progress);

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none" strokeWidth={strokeWidth}
            className="stroke-slate-100 dark:stroke-slate-800"
          />
          <motion.circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none" strokeWidth={strokeWidth}
            stroke={color} strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: offset }}
            transition={{ duration: 1.2, ease: "easeOut" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl font-bold text-slate-700 dark:text-slate-200 tabular-nums">{value}</span>
        </div>
      </div>
      <div className="text-center">
        <p className="text-xs font-medium text-slate-600 dark:text-slate-300">{label}</p>
        {sublabel && <p className="text-[10px] text-slate-400">{sublabel}</p>}
      </div>
    </div>
  );
}

// ── Running Task Card ────────────────────────────────────────────────────────

function RunningCard({ session, index }: { session: SessionItem; index: number }) {
  const progress = session.total_nodes > 0
    ? Math.round((session.completed_nodes / session.total_nodes) * 100) : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      className="p-3 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 hover:border-indigo-200 dark:hover:border-indigo-800 transition-colors"
    >
      <div className="flex items-center gap-2 mb-2">
        <div className="relative w-2 h-2 shrink-0">
          <span className="absolute inset-0 rounded-full bg-indigo-400 animate-ping opacity-75" />
          <span className="relative block w-2 h-2 rounded-full bg-indigo-500" />
        </div>
        <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug truncate flex-1">
          {session.goal || "执行中…"}
        </p>
        <span className="text-[11px] text-slate-400 tabular-nums shrink-0">{progress}%</span>
      </div>
      <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1">
        <motion.div
          className="bg-indigo-500 h-1 rounded-full"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
      <div className="flex items-center justify-between mt-1.5 text-[10px] text-slate-400">
        <span>步骤 {session.completed_nodes + 1}/{session.total_nodes}</span>
        <span>{timeAgo(session.started_at)}</span>
      </div>
    </motion.div>
  );
}

// ── Result Card ──────────────────────────────────────────────────────────────

function ResultCard({ session, index }: { session: SessionItem; index: number }) {
  const failed = session.status === "failed" || session.result_status === "failed";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 transition-colors"
    >
      {failed
        ? <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
        : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
      }
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug truncate">
          {session.goal || "任务"}
        </p>
      </div>
      <div className="flex flex-col items-end shrink-0">
        <span className={cn("text-[10px] font-medium", failed ? "text-red-400" : "text-emerald-500")}>
          {failed ? "失败" : "成功"}
        </span>
        <span className="text-[10px] text-slate-400">{timeAgo(session.completed_at)}</span>
      </div>
    </motion.div>
  );
}

// ── Approval Card ────────────────────────────────────────────────────────────

function ApprovalCard({ record, index }: { record: ApprovalHistoryRecord; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-amber-50/80 dark:bg-amber-950/20 border border-amber-200/60 dark:border-amber-800/40 transition-colors"
    >
      <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-slate-700 dark:text-slate-200 leading-snug truncate">
          {record.message || record.operation}
        </p>
      </div>
      <span className="text-[10px] text-amber-500 shrink-0">待处理</span>
    </motion.div>
  );
}

// ── Artifact Card ────────────────────────────────────────────────────────────

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
          <p className="text-[11px] font-medium text-slate-700 dark:text-slate-200 truncate">{artifact.filename}</p>
          <p className="text-[10px] text-slate-400">{formatBytes(artifact.size)}</p>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-400">{timeAgo(artifact.created_at)}</span>
        <a href={downloadUrl} target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-0.5 text-[10px] text-indigo-500 hover:text-indigo-600 font-medium">
          打开 <ExternalLink className="w-2.5 h-2.5" />
        </a>
      </div>
    </div>
  );
}

// ── App Shortcut ─────────────────────────────────────────────────────────────

function AppShortcut({ app, isPinned, onPinToggle, onClick, isAvatarEnabled, onAvatarToggle }: any) {
  const Icon = app.icon;
  const isAvatar = app.id === "avatar";

  return (
    <div className="relative group">
      <button
        onClick={isAvatar ? onAvatarToggle : onClick}
        disabled={app.comingSoon}
        className={cn(
          "flex flex-col items-center gap-1.5 px-3 py-2 rounded-xl transition-all",
          isAvatar && isAvatarEnabled
            ? "bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400"
            : "hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400",
          app.comingSoon && "opacity-40 cursor-not-allowed"
        )}
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

// ── Section Header ───────────────────────────────────────────────────────────

function SectionHeader({ icon: Icon, title, count }: { icon: any; title: string; count?: number }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-3.5 h-3.5 text-slate-400" />
      <span className="text-[11px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{title}</span>
      {count !== undefined && count > 0 && (
        <span className="ml-auto text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 px-1.5 py-0.5 rounded-full tabular-nums">
          {count}
        </span>
      )}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center h-20 text-[11px] text-slate-400 dark:text-slate-600 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl">
      {text}
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function HomePage() {
  const router = useRouter();
  const pathname = usePathname();
  const { isPinned, togglePin } = useDockApps();
  const { isConnected } = useSocket();
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
        const recentCompleted = sessionList.value.filter(s => s.status === "completed").slice(0, 5);
        const artifactResults = await Promise.allSettled(recentCompleted.map(s => historyApi.getArtifacts(s.id)));
        const allArtifacts: ArtifactRecord[] = [];
        artifactResults.forEach(r => {
          if (r.status === "fulfilled") {
            r.value.artifacts.forEach(a => {
              allArtifacts.push({
                artifact_id: a.artifact_id, step_id: a.step_id, filename: a.filename,
                size: a.size, mime_type: a.mime_type, artifact_type: a.artifact_type, created_at: a.created_at,
              });
            });
          }
        });
        allArtifacts.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        setArtifacts(allArtifacts.slice(0, 10));
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

      if (approvalRes.status === "fulfilled") {
        setApprovals(approvalRes.value.records);
      }
    } catch (e) {
      console.error("Dashboard fetch error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const runningCount = useMemo(() => sessions.filter(s => s.status === "running").length, [sessions]);
  useEffect(() => {
    const interval = setInterval(fetchData, runningCount > 0 ? 10000 : 30000);
    return () => clearInterval(interval);
  }, [fetchData, runningCount]);

  useEffect(() => {
    const check = async () => {
      const api = (window as any).electronAPI;
      if (api?.isFloatingWindowVisible) setIsAvatarEnabled(await api.isFloatingWindowVisible());
    };
    check();
  }, []);

  const handleAvatarToggle = async () => {
    const api = (window as any).electronAPI;
    if (api?.toggleFloatingWindow) setIsAvatarEnabled(await api.toggleFloatingWindow());
  };

  // Derived data
  const running = useMemo(() => sessions.filter(s => s.status === "running"), [sessions]);
  const recent = useMemo(() => sessions.filter(s => s.status === "completed" || s.status === "failed").slice(0, 6), [sessions]);

  const todayCompleted = useMemo(() => sessions.filter(s => {
    if (s.status !== "completed" || !s.completed_at) return false;
    const d = new Date(s.completed_at), now = new Date();
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  }).length, [sessions]);

  const todayFailed = useMemo(() => sessions.filter(s => {
    if (s.status !== "failed" || !s.completed_at) return false;
    const d = new Date(s.completed_at), now = new Date();
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  }).length, [sessions]);

  const todayTotal = todayCompleted + todayFailed;
  const successRate = todayTotal > 0 ? Math.round((todayCompleted / todayTotal) * 100) : 100;

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-950 overflow-hidden">

      {/* ── Status Bar ── */}
      <div className="shrink-0 px-6 py-3 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-3">
          {/* Connection indicator */}
          <span className="relative flex h-2 w-2">
            {running.length > 0 && isConnected && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            )}
            <span className={cn("relative inline-flex rounded-full h-2 w-2", isConnected ? "bg-emerald-500" : "bg-slate-400")} />
          </span>
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 uppercase tracking-wider">
            Avatar OS
          </span>

          {/* Stats chips */}
          <div className="flex items-center gap-3 ml-4 text-[11px] text-slate-500 dark:text-slate-400">
            {running.length > 0 && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium">
                <Zap className="w-3 h-3" /> {running.length} 运行中
              </span>
            )}
            {approvals.length > 0 && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400 font-medium">
                <AlertTriangle className="w-3 h-3" /> {approvals.length} 待确认
              </span>
            )}
            {nextSchedule !== "--:--" && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3 text-purple-400" /> 下次 {nextSchedule}
              </span>
            )}
          </div>

          <span className="ml-auto text-[10px] text-slate-300 dark:text-slate-700 tabular-nums">
            {new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" })}
          </span>
        </div>
      </div>

      {/* ── Main Content ── */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-6 max-w-5xl mx-auto">

          {/* ── Activity Rings ── */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="flex items-center justify-center gap-8 py-4"
          >
            <ActivityRing
              value={todayCompleted} max={Math.max(todayTotal, 10)}
              color="#10b981" label="今日完成"
              sublabel={todayTotal > 0 ? `成功率 ${successRate}%` : undefined}
            />
            <ActivityRing
              value={running.length} max={Math.max(running.length, 5)}
              color="#6366f1" label="正在运行"
            />
            <ActivityRing
              value={approvals.length} max={Math.max(approvals.length, 5)}
              color="#f59e0b" label="待确认"
            />
          </motion.div>

          {/* ── Two Column: Running + Approvals ── */}
          <div className="grid grid-cols-2 gap-5">
            {/* Running tasks */}
            <div>
              <SectionHeader icon={Zap} title="正在执行" count={running.length} />
              <div className="space-y-2">
                {running.length === 0
                  ? <EmptyState text="暂无运行中的任务" />
                  : running.slice(0, 5).map((s, i) => <RunningCard key={s.id} session={s} index={i} />)
                }
              </div>
            </div>

            {/* Approvals + Schedule */}
            <div>
              <SectionHeader icon={AlertTriangle} title="待确认" count={approvals.length} />
              <div className="space-y-2">
                {approvals.length === 0
                  ? <EmptyState text="暂无待确认项" />
                  : approvals.slice(0, 5).map((a, i) => <ApprovalCard key={a.request_id} record={a} index={i} />)
                }
              </div>
            </div>
          </div>

          {/* ── Recent Results ── */}
          <div>
            <SectionHeader icon={CheckCircle2} title="最近结果" count={recent.length} />
            <div className="grid grid-cols-2 gap-2">
              {recent.length === 0
                ? <EmptyState text="暂无历史记录" />
                : recent.map((s, i) => <ResultCard key={s.id} session={s} index={i} />)
              }
            </div>
          </div>

          {/* ── Artifacts ── */}
          {artifacts.length > 0 && (
            <div>
              <SectionHeader icon={Package} title="最近交付" count={artifacts.length} />
              <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-slate-200 dark:scrollbar-thumb-slate-700">
                {artifacts.map(a => <ArtifactCard key={a.artifact_id} artifact={a} />)}
              </div>
            </div>
          )}

        </div>
      </div>

      {/* ── Bottom Shortcuts ── */}
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
