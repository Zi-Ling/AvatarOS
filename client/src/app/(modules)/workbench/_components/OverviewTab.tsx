"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  CheckCircle2, Clock, Zap, FileText, FolderOpen,
  Package, ExternalLink, XCircle, Loader2, Pause, Play, X,
  ChevronDown, ChevronRight, Paperclip, Shield, AlertTriangle,
  ArrowRight, RotateCcw,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { historyApi, type SessionItem, type ArtifactRecord } from "@/lib/api/history";
import { approvalApi } from "@/lib/api/history";
import { scheduleApi } from "@/lib/api/schedule";
import { artifactApi } from "@/lib/api/history";
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

type HeroMode = "attention" | "live" | "calm";

// ═══════════════════════════════════════════════════════════════════════════════
// HERO A: Attention — 有 pending approval 时显示
// ═══════════════════════════════════════════════════════════════════════════════

function AttentionHero({ approval, onApprove, onReject, submitting }: {
  approval: ApprovalRequest;
  onApprove: () => void;
  onReject: () => void;
  submitting: boolean;
}) {
  // 从 details 提取风险等级
  const risk = approval.details?.risk_level as string | undefined;
  const affectedCount = approval.details?.affected_files as number | undefined;
  const riskLabel = risk === "high" ? "高风险：不可恢复操作"
    : risk === "medium" ? "中风险：请确认操作"
    : affectedCount ? `影响 ${affectedCount} 个文件` : null;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex flex-col items-center justify-center flex-1 px-6"
    >
      {/* Pulsing ring */}
      <div className="relative mb-5">
        <span className="absolute inset-0 rounded-full bg-amber-400/20 animate-ping" style={{ animationDuration: "2s" }} />
        <div className="relative w-12 h-12 rounded-full bg-amber-100 dark:bg-amber-900/40 flex items-center justify-center">
          <Shield className="w-6 h-6 text-amber-600 dark:text-amber-400" />
        </div>
      </div>

      {/* What */}
      <p className="text-base font-medium text-slate-800 dark:text-slate-100 text-center leading-snug mb-1.5 max-w-xs">
        {approval.message}
      </p>

      {/* Why — operation detail */}
      <p className="text-xs text-slate-500 dark:text-slate-400 text-center mb-2 max-w-xs">
        操作: {approval.operation}
      </p>

      {/* Risk badge */}
      {riskLabel && (
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50 mb-4">
          <AlertTriangle className="w-3 h-3 text-amber-500" />
          <span className="text-[11px] font-medium text-amber-700 dark:text-amber-400">{riskLabel}</span>
        </div>
      )}

      {/* Consequence — what happens if you don't act */}
      {approval.expires_at && (
        <p className="text-[11px] text-slate-400 dark:text-slate-500 mb-5">
          不操作将在 {timeAgo(approval.expires_at)} 过期
        </p>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={onReject}
          disabled={submitting}
          className="px-5 py-2 rounded-lg text-sm font-medium border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
        >
          拒绝
        </button>
        <button
          onClick={onApprove}
          disabled={submitting}
          className="px-5 py-2 rounded-lg text-sm font-medium bg-amber-500 hover:bg-amber-600 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
        >
          {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          批准
        </button>
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// HERO B: Live — 有 running task 时显示（沉浸式执行视图）
// ═══════════════════════════════════════════════════════════════════════════════

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

  // 找到当前正在执行的步骤
  const currentStep = stepViews.find(s => s.status === "running");
  const headline = currentStep?.title || narrativePhase?.description || session.goal || "执行中…";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex flex-col flex-1 px-5 pt-4 pb-2"
    >
      {/* ── Current Focus: 当前焦点，大字 ── */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-2">
          {isPaused
            ? <div className="w-2.5 h-2.5 rounded-full bg-amber-400 shrink-0" />
            : <div className="relative w-2.5 h-2.5 shrink-0">
                <span className="absolute inset-0 rounded-full bg-indigo-400 animate-ping opacity-75" />
                <span className="relative block w-2.5 h-2.5 rounded-full bg-indigo-500" />
              </div>
          }
          <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider">
            {isPaused ? "已暂停" : `步骤 ${session.completed_nodes + 1}/${session.total_nodes}`}
          </span>
          <span className="text-[11px] text-slate-400 ml-auto">{timeAgo(session.started_at)}</span>
        </div>

        <p className="text-lg font-semibold text-slate-800 dark:text-slate-100 leading-snug line-clamp-2">
          {headline}
        </p>

        {/* Narrative description (如果和 headline 不同) */}
        {narrativePhase?.description && narrativePhase.description !== headline && (
          <p className="text-sm text-indigo-600 dark:text-indigo-400 mt-1 truncate">
            {narrativePhase.description}
          </p>
        )}
      </div>

      {/* ── Progress bar ── */}
      <div className="mb-4">
        <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1.5">
          <motion.div
            className={cn("h-1.5 rounded-full", isPaused ? "bg-amber-400" : "bg-indigo-500")}
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
        </div>
        <div className="flex justify-between mt-1">
          <span className="text-[11px] text-slate-400">{progress}%</span>
          {session.completed_nodes > 0 && (
            <span className="text-[11px] text-slate-400">
              {session.completed_nodes} 步完成
            </span>
          )}
        </div>
      </div>

      {/* ── Step Timeline: 过程证据 ── */}
      {stepViews.length > 0 && (
        <div className="flex-1 min-h-0 overflow-y-auto mb-3">
          <div className="space-y-0.5">
            {stepViews.map((step, i) => {
              const isCurrent = step.status === "running";
              const isDone = step.status === "completed";
              const isFailed = step.status === "failed";

              return (
                <motion.div
                  key={step.step_id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className={cn(
                    "flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors",
                    isCurrent && "bg-indigo-50 dark:bg-indigo-950/30",
                  )}
                >
                  {/* Status indicator */}
                  {isCurrent ? (
                    <Loader2 className="w-3.5 h-3.5 text-indigo-500 animate-spin shrink-0" />
                  ) : isDone ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                  ) : isFailed ? (
                    <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                  ) : (
                    <div className="w-3.5 h-3.5 rounded-full border-2 border-slate-200 dark:border-slate-700 shrink-0" />
                  )}

                  {/* Title */}
                  <span className={cn(
                    "flex-1 truncate",
                    isCurrent ? "text-slate-800 dark:text-slate-100 font-medium" : "text-slate-500 dark:text-slate-400",
                  )}>
                    {step.title}
                  </span>

                  {/* Duration */}
                  {step.duration_ms && (
                    <span className="text-[10px] text-slate-400 shrink-0">{formatDuration(step.duration_ms)}</span>
                  )}

                  {/* Artifact badge */}
                  {step.has_artifact && (
                    <Paperclip className="w-3 h-3 text-indigo-400 shrink-0" />
                  )}
                </motion.div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Controls ── */}
      {isActive && onPauseResume && onCancel && (
        <div className="flex gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
          <button
            onClick={onPauseResume}
            disabled={isActioning}
            className={cn(
              "flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-medium transition-colors disabled:opacity-50",
              isPaused
                ? "bg-indigo-50 text-indigo-600 hover:bg-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-400"
                : "bg-amber-50 text-amber-600 hover:bg-amber-100 dark:bg-amber-500/10 dark:text-amber-400"
            )}
          >
            {isPaused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
            {isPaused ? "恢复执行" : "暂停"}
          </button>
          <button
            onClick={onCancel}
            disabled={isActioning}
            className="px-4 py-2 rounded-lg text-xs font-medium bg-red-50 text-red-500 hover:bg-red-100 dark:bg-red-500/10 dark:text-red-400 transition-colors disabled:opacity-50"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// HERO C: Calm — 空闲时显示
// ═══════════════════════════════════════════════════════════════════════════════

function CalmHero({ todayCompleted, todayFailed, nextSchedule, lastFailedGoal }: {
  todayCompleted: number;
  todayFailed: number;
  nextSchedule: string;
  lastFailedGoal: string | null;
}) {
  const successRate = todayCompleted + todayFailed > 0
    ? Math.round((todayCompleted / (todayCompleted + todayFailed)) * 100) : 100;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex flex-col items-center justify-center flex-1 px-6"
    >
      {/* Calm icon */}
      <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-950/40 dark:to-purple-950/40 flex items-center justify-center mb-4">
        <Zap className="w-5 h-5 text-indigo-400" />
      </div>

      {/* Stats */}
      {todayCompleted > 0 ? (
        <div className="text-center mb-3">
          <p className="text-2xl font-bold text-slate-800 dark:text-slate-100">{todayCompleted}</p>
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">今日完成任务</p>
        </div>
      ) : (
        <div className="text-center mb-3">
          <p className="text-sm text-slate-500 dark:text-slate-400">系统待机中</p>
        </div>
      )}

      {/* Secondary stats row */}
      <div className="flex items-center gap-4 text-[11px] text-slate-400 dark:text-slate-500 mb-4">
        {todayCompleted > 0 && (
          <span className="flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
            成功率 {successRate}%
          </span>
        )}
        {nextSchedule !== "--:--" && (
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3 text-purple-400" />
            下次 {nextSchedule}
          </span>
        )}
      </div>

      {/* Last failure hint */}
      {lastFailedGoal && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50/50 dark:bg-red-950/20 border border-red-100 dark:border-red-900/30 max-w-xs">
          <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <div className="min-w-0">
            <p className="text-[11px] text-red-500 dark:text-red-400 truncate">{lastFailedGoal}</p>
            <p className="text-[10px] text-red-400/70">最近失败的任务</p>
          </div>
          <RotateCcw className="w-3 h-3 text-red-400 shrink-0 cursor-pointer hover:text-red-500" />
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Secondary Active Tasks — Running 区下方的次要活跃任务条目
// ═══════════════════════════════════════════════════════════════════════════════

function SecondaryTaskRow({ session, label, statusColor, action, onClick }: {
  session: SessionItem;
  label: string;
  statusColor: string;
  action?: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors",
        "hover:bg-slate-100/50 dark:hover:bg-slate-800/30",
        onClick && "cursor-pointer"
      )}
    >
      <div className={cn("w-2 h-2 rounded-full shrink-0", statusColor)} />
      <p className="text-xs text-slate-600 dark:text-slate-300 truncate flex-1">
        {session.goal || "任务"}
      </p>
      <span className="text-[10px] text-slate-400 shrink-0">{label}</span>
      {action}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Activity Feed Item — 底部历史条目（极度克制）
// ═══════════════════════════════════════════════════════════════════════════════

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
      <span className="text-[10px] text-slate-300 dark:text-slate-600 shrink-0">
        {timeAgo(session.completed_at || session.started_at)}
      </span>
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
        const recentCompleted = sessionList.value.filter(s => s.status === "completed").slice(0, 5);
        const artifactResults = await Promise.allSettled(recentCompleted.map(s => historyApi.getArtifacts(s.id)));
        const allArtifacts: ArtifactRecord[] = [];
        artifactResults.forEach((r, idx) => {
          if (r.status === "fulfilled") {
            r.value.artifacts.forEach(a => allArtifacts.push({
              artifact_id: a.artifact_id, step_id: a.step_id, filename: a.filename,
              size: a.size, mime_type: a.mime_type, artifact_type: a.artifact_type,
              created_at: a.created_at, session_id: recentCompleted[idx].id,
            }));
          }
        });
        setArtifacts(allArtifacts);
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

  // ── Hero mode: strict priority ──
  const heroMode: HeroMode = pendingApprovals.length > 0 ? "attention"
    : runningCount > 0 ? "live"
    : "calm";

  // For live hero: pick the primary running session (activeTask match or first)
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
      {/* ── Status Bar: 极简一行 ── */}
      <div className="shrink-0 px-4 py-2 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-2.5 text-[11px] text-slate-400 dark:text-slate-500">
          <span className="relative flex h-2 w-2">
            {runningCount > 0 && isConnected && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            )}
            <span className={cn("relative inline-flex rounded-full h-2 w-2", isConnected ? "bg-emerald-500" : "bg-slate-400")} />
          </span>
          {runningCount > 0 && <span>{runningCount} active</span>}
          {pendingApprovals.length > 0 && (
            <span className="text-amber-500 font-medium">{pendingApprovals.length} waiting</span>
          )}
          {runningCount === 0 && pendingApprovals.length === 0 && (
            <span>{loading ? "…" : "Ready"}</span>
          )}
        </div>
      </div>

      {/* ── Hero Zone: 视觉主体 ── */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={heroMode}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25 }}
            className="flex flex-col flex-1 min-h-0"
          >
            {/* Hero content based on mode */}
            {heroMode === "attention" && pendingApprovals[0] && (
              <AttentionHero
                approval={pendingApprovals[0]}
                onApprove={handleApprove}
                onReject={handleReject}
                submitting={approvalSubmitting}
              />
            )}

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
                lastFailedGoal={lastFailed?.goal ?? null}
              />
            )}
          </motion.div>
        </AnimatePresence>

        {/* ── Secondary active tasks (below hero, above feed) ── */}
        {(secondaryRunning.length > 0 || (heroMode === "attention" && running.length > 0)) && (
          <div className="shrink-0 px-3 py-1.5 border-t border-slate-100 dark:border-slate-800">
            {heroMode === "attention" && running.map(s => (
              <SecondaryTaskRow
                key={s.id}
                session={s}
                label={`${Math.round((s.completed_nodes / Math.max(s.total_nodes, 1)) * 100)}%`}
                statusColor="bg-indigo-500"
                onClick={() => setActiveTab("logs")}
              />
            ))}
            {heroMode === "live" && secondaryRunning.map(s => (
              <SecondaryTaskRow
                key={s.id}
                session={s}
                label={`${Math.round((s.completed_nodes / Math.max(s.total_nodes, 1)) * 100)}%`}
                statusColor="bg-indigo-400"
                onClick={() => setActiveTab("logs")}
              />
            ))}
          </div>
        )}

        {/* ── Feed: 最近完成（极度克制）── */}
        {completed.length > 0 && (
          <div className="shrink-0 max-h-[35%] overflow-y-auto border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center gap-2 px-4 pt-2.5 pb-1">
              <span className="text-[10px] text-slate-300 dark:text-slate-600 uppercase tracking-wider font-medium">最近</span>
            </div>
            <div className="px-1 pb-2">
              {completed.slice(0, 8).map(s => (
                <FeedItem
                  key={s.id}
                  session={s}
                  artifacts={artifacts}
                  onClick={() => setActiveTab("history")}
                />
              ))}
              {completed.length > 8 && (
                <button
                  onClick={() => setActiveTab("history")}
                  className="flex items-center gap-1 px-3 py-1.5 text-[11px] text-indigo-500 hover:text-indigo-600 transition-colors"
                >
                  查看全部 <ArrowRight className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
