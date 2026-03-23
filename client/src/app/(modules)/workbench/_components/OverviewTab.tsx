"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  CheckCircle2, Zap,
  XCircle, Loader2, Pause, Play, X,
  Paperclip, Shield, AlertTriangle, ArrowRight, RotateCcw,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { historyApi, type SessionItem, type ArtifactRecord } from "@/lib/api/history";
import { approvalApi } from "@/lib/api/history";
import { scheduleApi } from "@/lib/api/schedule";
import { useSocket } from "@/components/providers/SocketProvider";
import { useTaskStore } from "@/stores/taskStore";
import { useRunStore } from "@/stores/runStore";
import { useWorkbenchStore } from "@/stores/workbenchStore";
import { cancelTask, pauseTask, resumeTask } from "@/lib/api/task";
import { deriveTaskControls } from "@/types/task";
import type { ApprovalRequest } from "@/types/chat";
import type { NarrativeStepView } from "@/types/narrative";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  const diff = Date.now() - new Date(dateStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m}分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}小时前`;
  return `${Math.floor(h / 24)}天前`;
}

function formatDuration(ms: number | null): string {
  if (!ms) return "";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m${s % 60}s`;
}

// ── Activity Ring (SVG) ──────────────────────────────────────────────────────

function ActivityRing({ value, max, color, size = 80, strokeWidth = 6, label, icon: Icon }: {
  value: number; max: number; color: string; size?: number;
  strokeWidth?: number; label: string; icon: any;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = max > 0 ? Math.min(value / max, 1) : 0;
  const offset = circumference * (1 - progress);

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          {/* Track */}
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none" strokeWidth={strokeWidth}
            className="stroke-slate-100 dark:stroke-slate-800"
          />
          {/* Progress */}
          <motion.circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none" strokeWidth={strokeWidth}
            stroke={color} strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: offset }}
            transition={{ duration: 1, ease: "easeOut" }}
          />
        </svg>
        {/* Center content */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <Icon className="w-3.5 h-3.5 mb-0.5" style={{ color }} />
          <span className="text-sm font-bold text-slate-700 dark:text-slate-200">{value}</span>
        </div>
      </div>
      <span className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">{label}</span>
    </div>
  );
}

// ── Pulse Wave (for live mode) ───────────────────────────────────────────────

function PulseWave({ isPaused }: { isPaused: boolean }) {
  return (
    <div className="relative w-full h-8 overflow-hidden rounded-lg">
      {[0, 1, 2].map(i => (
        <motion.div
          key={i}
          className={cn(
            "absolute inset-0 rounded-lg",
            isPaused ? "bg-amber-400/10" : "bg-indigo-500/10"
          )}
          animate={isPaused ? {} : {
            scaleX: [1, 1.5, 1],
            opacity: [0.3, 0, 0.3],
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            delay: i * 0.6,
            ease: "easeInOut",
          }}
        />
      ))}
      <div className={cn(
        "absolute inset-0 rounded-lg",
        isPaused
          ? "bg-gradient-to-r from-amber-500/5 via-amber-500/10 to-amber-500/5"
          : "bg-gradient-to-r from-indigo-500/5 via-indigo-500/15 to-indigo-500/5"
      )} />
    </div>
  );
}

// ── Timeline Node ────────────────────────────────────────────────────────────

function TimelineNode({ step, index }: { step: NarrativeStepView; index: number }) {
  const isCurrent = step.status === "running";
  const isDone = step.status === "completed";
  const isFailed = step.status === "failed";

  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.04 }}
      className="flex items-start gap-3 relative"
    >
      {/* Timeline line + dot */}
      <div className="flex flex-col items-center shrink-0 pt-0.5">
        <div className={cn(
          "w-2.5 h-2.5 rounded-full border-2 transition-colors relative",
          isCurrent && "border-indigo-500 bg-indigo-500",
          isDone && "border-emerald-500 bg-emerald-500",
          isFailed && "border-red-400 bg-red-400",
          !isCurrent && !isDone && !isFailed && "border-slate-300 dark:border-slate-600 bg-transparent",
        )}>
          {isCurrent && (
            <span className="absolute inset-0 rounded-full bg-indigo-400 animate-ping opacity-75" />
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pb-3">
        <div className="flex items-center gap-2">
          <span className={cn(
            "text-xs truncate flex-1",
            isCurrent ? "text-slate-800 dark:text-slate-100 font-medium" : "text-slate-500 dark:text-slate-400",
          )}>
            {step.title}
          </span>
          {step.duration_ms && (
            <span className="text-[10px] text-slate-400 shrink-0 tabular-nums">{formatDuration(step.duration_ms)}</span>
          )}
          {step.has_artifact && (
            <Paperclip className="w-2.5 h-2.5 text-indigo-400 shrink-0" />
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ── Live Hero (Mission Control style) ────────────────────────────────────────

function LiveHero({ session, stepViews, narrativePhase, isActive, controlStatus, onPauseResume, onCancel, isActioning }: {
  session: SessionItem;
  stepViews: NarrativeStepView[];
  narrativePhase: { phase: string; description: string } | null;
  isActive: boolean;
  controlStatus?: string;
  onPauseResume?: () => void;
  onCancel?: () => void;
  isActioning?: boolean;
}) {
  const progress = session.total_nodes > 0
    ? Math.round((session.completed_nodes / session.total_nodes) * 100) : 0;
  const isPaused = controlStatus === "paused";
  const currentStep = stepViews.find(s => s.status === "running");
  const headline = currentStep?.title || narrativePhase?.description || session.goal || "执行中…";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex flex-col flex-1 min-h-0"
    >
      {/* Pulse wave header */}
      <div className="px-4 pt-3">
        <PulseWave isPaused={isPaused} />
      </div>

      {/* Current focus */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center gap-2 mb-1.5">
          <div className={cn(
            "w-2 h-2 rounded-full shrink-0",
            isPaused ? "bg-amber-400" : "bg-indigo-500"
          )}>
            {!isPaused && (
              <span className="block w-2 h-2 rounded-full bg-indigo-400 animate-ping" />
            )}
          </div>
          <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">
            {isPaused ? "已暂停" : `步骤 ${session.completed_nodes + 1}/${session.total_nodes}`}
          </span>
          <span className="text-[10px] text-slate-400 ml-auto tabular-nums">{progress}%</span>
        </div>

        <p className="text-base font-semibold text-slate-800 dark:text-slate-100 leading-snug line-clamp-2 mb-2">
          {headline}
        </p>

        {/* Progress bar */}
        <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1">
          <motion.div
            className={cn("h-1 rounded-full", isPaused ? "bg-amber-400" : "bg-indigo-500")}
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.6, ease: "easeOut" }}
          />
        </div>
      </div>

      {/* Step timeline */}
      {stepViews.length > 0 && (
        <div className="flex-1 min-h-0 overflow-y-auto px-4 pt-2 pb-1">
          <div className="relative">
            {/* Vertical line */}
            <div className="absolute left-[4.5px] top-2 bottom-2 w-px bg-slate-200 dark:bg-slate-800" />
            {stepViews.map((step, i) => (
              <TimelineNode key={step.step_id} step={step} index={i} />
            ))}
          </div>
        </div>
      )}

      {/* Controls */}
      {isActive && onPauseResume && onCancel && (
        <div className="shrink-0 flex gap-2 px-4 py-2 border-t border-slate-100 dark:border-slate-800">
          <button onClick={onPauseResume} disabled={isActioning}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50",
              isPaused
                ? "bg-indigo-50 text-indigo-600 hover:bg-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-400"
                : "bg-amber-50 text-amber-600 hover:bg-amber-100 dark:bg-amber-500/10 dark:text-amber-400"
            )}>
            {isPaused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
            {isPaused ? "恢复" : "暂停"}
          </button>
          <button onClick={onCancel} disabled={isActioning}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-red-50 text-red-500 hover:bg-red-100 dark:bg-red-500/10 dark:text-red-400 transition-colors disabled:opacity-50">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </motion.div>
  );
}

// ── Calm Hero (Mission Control idle) ─────────────────────────────────────────

function CalmHero({ todayCompleted, todayFailed, nextSchedule, pendingCount, runningCount, lastFailedGoal }: {
  todayCompleted: number;
  todayFailed: number;
  nextSchedule: string;
  pendingCount: number;
  runningCount: number;
  lastFailedGoal: string | null;
}) {
  const total = todayCompleted + todayFailed;
  const successRate = total > 0 ? Math.round((todayCompleted / total) * 100) : 100;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex flex-col items-center justify-center flex-1 px-5"
    >
      {/* Activity Rings */}
      <div className="flex items-end gap-5 mb-5">
        <ActivityRing
          value={todayCompleted} max={Math.max(todayCompleted, 10)}
          color="#10b981" label="完成" icon={CheckCircle2} size={72} strokeWidth={5}
        />
        <ActivityRing
          value={runningCount} max={Math.max(runningCount, 3)}
          color="#6366f1" label="活跃" icon={Zap} size={72} strokeWidth={5}
        />
        <ActivityRing
          value={pendingCount} max={Math.max(pendingCount, 3)}
          color="#f59e0b" label="待确认" icon={AlertTriangle} size={72} strokeWidth={5}
        />
      </div>

      {/* Summary line */}
      {total > 0 ? (
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
          今日 {total} 项任务 · 成功率 {successRate}%
          {nextSchedule !== "--:--" && <span className="ml-2">· 下次调度 {nextSchedule}</span>}
        </p>
      ) : (
        <p className="text-xs text-slate-400 dark:text-slate-500 mb-3">
          系统待机中
          {nextSchedule !== "--:--" && <span> · 下次调度 {nextSchedule}</span>}
        </p>
      )}

      {/* Last failure */}
      {lastFailedGoal && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50/60 dark:bg-red-950/20 border border-red-100 dark:border-red-900/30 max-w-[280px]">
          <XCircle className="w-3 h-3 text-red-400 shrink-0" />
          <p className="text-[11px] text-red-500 dark:text-red-400 truncate flex-1">{lastFailedGoal}</p>
          <RotateCcw className="w-3 h-3 text-red-400 shrink-0 cursor-pointer hover:text-red-500" />
        </div>
      )}
    </motion.div>
  );
}

// ── Activity Ticker (scrolling recent activity) ──────────────────────────────

function ActivityTicker({ sessions }: { sessions: SessionItem[] }) {
  const tickerRef = useRef<HTMLDivElement>(null);

  return (
    <div className="relative overflow-hidden">
      <div ref={tickerRef} className="flex gap-4 px-4 py-2 overflow-x-auto scrollbar-hide">
        {sessions.map(s => {
          const failed = s.status === "failed" || s.result_status === "failed";
          return (
            <div key={s.id} className="flex items-center gap-1.5 shrink-0 text-[11px]">
              {failed
                ? <XCircle className="w-3 h-3 text-red-300" />
                : <CheckCircle2 className="w-3 h-3 text-emerald-400/70" />
              }
              <span className="text-slate-500 dark:text-slate-400 max-w-[160px] truncate">
                {s.goal || "任务"}
              </span>
              <span className="text-slate-300 dark:text-slate-600 tabular-nums">
                {timeAgo(s.completed_at || s.started_at)}
              </span>
            </div>
          );
        })}
      </div>
      {/* Fade edges */}
      <div className="absolute inset-y-0 left-0 w-6 bg-gradient-to-r from-slate-50 dark:from-slate-950 to-transparent pointer-events-none" />
      <div className="absolute inset-y-0 right-0 w-6 bg-gradient-to-l from-slate-50 dark:from-slate-950 to-transparent pointer-events-none" />
    </div>
  );
}

// ── Feed Item ────────────────────────────────────────────────────────────────

function FeedItem({ session, artifacts, onClick }: {
  session: SessionItem;
  artifacts: ArtifactRecord[];
  onClick?: () => void;
}) {
  const failed = session.status === "failed" || session.result_status === "failed";
  const sessionArtifacts = artifacts.filter(a => a.session_id === session.id);

  return (
    <div
      onClick={onClick}
      className={cn(
        "flex items-center gap-2.5 px-3 py-2 transition-colors rounded-md",
        "hover:bg-slate-100/40 dark:hover:bg-slate-800/20",
        onClick && "cursor-pointer"
      )}
    >
      {failed
        ? <XCircle className="w-3.5 h-3.5 text-red-300 shrink-0" />
        : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400/70 shrink-0" />
      }
      <span className="text-xs text-slate-500 dark:text-slate-400 truncate flex-1">
        {session.goal || "任务"}
      </span>
      {sessionArtifacts.length > 0 && (
        <span className="flex items-center gap-0.5 text-[10px] text-indigo-400">
          <Paperclip className="w-2.5 h-2.5" />{sessionArtifacts.length}
        </span>
      )}
      <span className="text-[10px] text-slate-300 dark:text-slate-600 shrink-0 tabular-nums">
        {timeAgo(session.completed_at || session.started_at)}
      </span>
    </div>
  );
}

// ── Secondary Task Row ───────────────────────────────────────────────────────

function SecondaryTaskRow({ session, onClick }: {
  session: SessionItem;
  onClick?: () => void;
}) {
  const pct = Math.round((session.completed_nodes / Math.max(session.total_nodes, 1)) * 100);
  return (
    <div
      onClick={onClick}
      className={cn(
        "flex items-center gap-2.5 px-3 py-1.5 rounded-lg transition-colors",
        "hover:bg-slate-100/50 dark:hover:bg-slate-800/30",
        onClick && "cursor-pointer"
      )}
    >
      <div className="relative w-2 h-2 shrink-0">
        <span className="absolute inset-0 rounded-full bg-indigo-400 animate-ping opacity-50" />
        <span className="relative block w-2 h-2 rounded-full bg-indigo-500" />
      </div>
      <p className="text-xs text-slate-600 dark:text-slate-300 truncate flex-1">
        {session.goal || "任务"}
      </p>
      <span className="text-[10px] text-slate-400 shrink-0 tabular-nums">{pct}%</span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════════════════════════

export function OverviewTab() {
  const { isConnected } = useSocket();
  const { activeTask, controlStatus, setIsCancelling, pendingApprovals, removePendingApproval } = useTaskStore();
  const { setActiveTab } = useWorkbenchStore();
  const getNarrativeStepViews = useRunStore(s => s.getNarrativeStepViews);
  const getCurrentNarrativePhase = useRunStore(s => s.getCurrentNarrativePhase);
  const { canPause, canResume, canCancel } = deriveTaskControls(activeTask?.status as any ?? "executing", controlStatus);

  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  // 缓存已拉取过 artifacts 的 session IDs，避免每次轮询重复请求
  const fetchedArtifactSessionsRef = useRef<Set<string>>(new Set());
  const [nextSchedule, setNextSchedule] = useState<string>("--:--");
  const [loading, setLoading] = useState(true);
  const [isActioning, setIsActioning] = useState(false);
  const [approvalSubmitting, setApprovalSubmitting] = useState(false);

  // ── Data fetching ──
  const fetchData = useCallback(async () => {
    try {
      const [sessionList, scheduleList] = await Promise.allSettled([
        historyApi.listSessions(30),
        scheduleApi.listSchedules(),
      ]);

      if (sessionList.status === "fulfilled") {
        setSessions(sessionList.value);
        // 只拉取尚未缓存的已完成 session 的 artifacts
        const recentCompleted = sessionList.value.filter(s => s.status === "completed").slice(0, 5);
        const unfetched = recentCompleted.filter(s => !fetchedArtifactSessionsRef.current.has(s.id));
        if (unfetched.length > 0) {
          const artifactResults = await Promise.allSettled(unfetched.map(s => historyApi.getArtifacts(s.id)));
          const newArtifacts: ArtifactRecord[] = [];
          artifactResults.forEach((r, idx) => {
            if (r.status === "fulfilled") {
              fetchedArtifactSessionsRef.current.add(unfetched[idx].id);
              r.value.artifacts.forEach(a => newArtifacts.push({
                artifact_id: a.artifact_id, step_id: a.step_id, filename: a.filename,
                size: a.size, mime_type: a.mime_type, artifact_type: a.artifact_type,
                created_at: a.created_at, session_id: unfetched[idx].id,
              }));
            }
          });
          if (newArtifacts.length > 0) {
            setArtifacts(prev => [...prev, ...newArtifacts]);
          }
        }
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

  // ── Derived data ──
  const running = useMemo(() => sessions.filter(s => s.status === "running"), [sessions]);
  const completed = useMemo(() => sessions.filter(s => s.status === "completed" || s.status === "failed"), [sessions]);
  const runningCount = running.length;

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

  const lastFailed = useMemo(() =>
    completed.find(s => s.status === "failed" || s.result_status === "failed") ?? null
  , [completed]);

  // ── Polling with visibility ──
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    const start = () => { interval = setInterval(fetchData, runningCount > 0 ? 10000 : 30000); };
    const onVis = () => { clearInterval(interval); if (document.visibilityState === "visible") start(); };
    start();
    document.addEventListener("visibilitychange", onVis);
    return () => { clearInterval(interval); document.removeEventListener("visibilitychange", onVis); };
  }, [fetchData, runningCount]);

  // ── Hero mode — approval no longer hijacks the entire view ──
  type HeroMode = "live" | "calm";
  const heroMode: HeroMode = runningCount > 0 ? "live" : "calm";

  const primaryRunning = running.find(s => s.id === activeTask?.id) ?? running[0] ?? null;
  const secondaryRunning = running.filter(s => s !== primaryRunning);

  // ── Handlers ──
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

  const handleApprove = async () => {
    if (approvalSubmitting || pendingApprovals.length === 0) return;
    setApprovalSubmitting(true);
    try {
      await approvalApi.respond(pendingApprovals[0].request_id, true);
      removePendingApproval(pendingApprovals[0].request_id);
    } catch (e) { console.error("approve failed", e); }
    finally { setApprovalSubmitting(false); }
  };

  const handleReject = async () => {
    if (approvalSubmitting || pendingApprovals.length === 0) return;
    setApprovalSubmitting(true);
    try {
      await approvalApi.respond(pendingApprovals[0].request_id, false);
      removePendingApproval(pendingApprovals[0].request_id);
    } catch (e) { console.error("reject failed", e); }
    finally { setApprovalSubmitting(false); }
  };

  // ── Render ──
  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-950 overflow-hidden">
      {/* ── Status Bar ── */}
      <div className="shrink-0 px-4 py-2 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-2.5 text-[11px] text-slate-400 dark:text-slate-500">
          <span className="relative flex h-2 w-2">
            {runningCount > 0 && isConnected && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            )}
            <span className={cn("relative inline-flex rounded-full h-2 w-2", isConnected ? "bg-emerald-500" : "bg-slate-400")} />
          </span>
          {runningCount > 0 && <span className="tabular-nums">{runningCount} active</span>}
          {pendingApprovals.length > 0 && (
            <span className="text-amber-500 font-medium tabular-nums">{pendingApprovals.length} waiting</span>
          )}
          {runningCount === 0 && pendingApprovals.length === 0 && (
            <span>{loading ? "…" : "Ready"}</span>
          )}
          <span className="ml-auto text-[10px] text-slate-300 dark:text-slate-700 tabular-nums">
            {new Date().toLocaleDateString("zh-CN", { month: "short", day: "numeric", weekday: "short" })}
          </span>
        </div>
      </div>

      {/* ── Hero Zone ── */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {/* Approval banner — compact, doesn't hijack the view */}
        {pendingApprovals.length > 0 && pendingApprovals[0] && (
          <div className="shrink-0 mx-3 mt-2 mb-1 px-3 py-2.5 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/40">
            <div className="flex items-center gap-2 mb-2">
              <div className="relative">
                <motion.div
                  className="absolute -inset-1 rounded-full bg-amber-400/20"
                  animate={{ scale: [1, 1.3, 1], opacity: [0.4, 0, 0.4] }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
                <Shield className="relative w-4 h-4 text-amber-600 dark:text-amber-400" />
              </div>
              <p className="text-xs font-medium text-slate-700 dark:text-slate-200 truncate flex-1">
                {pendingApprovals[0].message}
              </p>
              {pendingApprovals.length > 1 && (
                <span className="text-[10px] text-amber-500 font-medium shrink-0">+{pendingApprovals.length - 1}</span>
              )}
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={handleReject} disabled={approvalSubmitting}
                className="px-3 py-1 rounded-md text-[11px] font-medium border border-slate-200 dark:border-slate-700 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50">
                拒绝
              </button>
              <button onClick={handleApprove} disabled={approvalSubmitting}
                className="px-3 py-1 rounded-md text-[11px] font-medium bg-amber-500 hover:bg-amber-600 text-white transition-colors disabled:opacity-50 flex items-center gap-1">
                {approvalSubmitting && <Loader2 className="w-3 h-3 animate-spin" />}
                批准
              </button>
            </div>
          </div>
        )}

        <AnimatePresence mode="wait">
          <motion.div
            key={heroMode}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2 }}
            className="flex flex-col flex-1 min-h-0"
          >
            {heroMode === "live" && primaryRunning && (
              <LiveHero
                session={primaryRunning}
                stepViews={getNarrativeStepViews(primaryRunning.id)}
                narrativePhase={getCurrentNarrativePhase(primaryRunning.id)}
                isActive={activeTask?.id === primaryRunning.id}
                controlStatus={activeTask?.id === primaryRunning.id ? controlStatus : undefined}
                onPauseResume={activeTask?.id === primaryRunning.id ? handlePauseResume : undefined}
                onCancel={activeTask?.id === primaryRunning.id ? handleCancel : undefined}
                isActioning={isActioning}
              />
            )}
            {heroMode === "calm" && (
              <CalmHero
                todayCompleted={todayCompleted}
                todayFailed={todayFailed}
                nextSchedule={nextSchedule}
                pendingCount={pendingApprovals.length}
                runningCount={runningCount}
                lastFailedGoal={lastFailed?.goal ?? null}
              />
            )}
          </motion.div>
        </AnimatePresence>

        {/* ── Secondary running tasks ── */}
        {secondaryRunning.length > 0 && (
          <div className="shrink-0 px-2 py-1 border-t border-slate-100 dark:border-slate-800">
            {secondaryRunning.map(s => (
              <SecondaryTaskRow key={s.id} session={s} onClick={() => setActiveTab("logs")} />
            ))}
          </div>
        )}

        {/* ── Activity Feed ── */}
        {completed.length > 0 && (
          <div className="shrink-0 max-h-[35%] overflow-hidden border-t border-slate-100 dark:border-slate-800">
            {/* Ticker for quick glance */}
            {completed.length > 3 && (
              <ActivityTicker sessions={completed.slice(0, 10)} />
            )}
            {/* Detailed feed */}
            <div className="overflow-y-auto max-h-[calc(100%-32px)]">
              <div className="px-1 pb-2">
                {completed.slice(0, 6).map(s => (
                  <FeedItem key={s.id} session={s} artifacts={artifacts} onClick={() => setActiveTab("history")} />
                ))}
                {completed.length > 6 && (
                  <button
                    onClick={() => setActiveTab("history")}
                    className="flex items-center gap-1 px-3 py-1.5 text-[11px] text-indigo-500 hover:text-indigo-600 transition-colors"
                  >
                    查看全部 <ArrowRight className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
