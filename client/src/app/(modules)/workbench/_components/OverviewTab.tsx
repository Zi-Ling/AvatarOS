"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  CheckCircle2, XCircle, Loader2, Pause, Play, X,
  Paperclip, Shield, AlertTriangle, ArrowRight,
  Send, Eye, RotateCcw, Hand, FileText, Globe,
  ChevronDown, ChevronUp, Edit3, KeyRound, GitBranch,
  Upload, AlertOctagon,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { historyApi, type SessionItem, type ArtifactRecord, artifactApi } from "@/lib/api/history";
import { approvalApi } from "@/lib/api/history";
import { scheduleApi } from "@/lib/api/schedule";
import { useSocket } from "@/components/providers/SocketProvider";
import { useTaskStore } from "@/stores/taskStore";
import { useRunStore } from "@/stores/runStore";
import { useWorkbenchStore } from "@/stores/workbenchStore";
import { cancelTask, pauseTask, resumeTask, getPauseContext, type PauseContext } from "@/lib/api/task";
import { deriveTaskControls } from "@/types/task";
import type { ApprovalRequest, InterruptType } from "@/types/chat";
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

const STALE_THRESHOLD_MS = 2 * 60 * 60 * 1000;

// ── Interrupt Type Config ─────────────────────────────────────────────────────

const INTERRUPT_CONFIG: Record<InterruptType, {
  icon: typeof Shield;
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
}> = {
  approval_required: {
    icon: Shield, label: "需要你的批准", color: "text-amber-600 dark:text-amber-400",
    bgColor: "bg-amber-50/80 dark:bg-amber-950/20", borderColor: "border-amber-200 dark:border-amber-800/40",
  },
  input_required: {
    icon: Edit3, label: "需要你提供信息", color: "text-blue-600 dark:text-blue-400",
    bgColor: "bg-blue-50/80 dark:bg-blue-950/20", borderColor: "border-blue-200 dark:border-blue-800/40",
  },
  auth_required: {
    icon: KeyRound, label: "需要你的授权", color: "text-violet-600 dark:text-violet-400",
    bgColor: "bg-violet-50/80 dark:bg-violet-950/20", borderColor: "border-violet-200 dark:border-violet-800/40",
  },
  recovery_choice_required: {
    icon: GitBranch, label: "需要你选择恢复方案", color: "text-orange-600 dark:text-orange-400",
    bgColor: "bg-orange-50/80 dark:bg-orange-950/20", borderColor: "border-orange-200 dark:border-orange-800/40",
  },
  publish_required: {
    icon: Upload, label: "准备发布，需要你确认", color: "text-emerald-600 dark:text-emerald-400",
    bgColor: "bg-emerald-50/80 dark:bg-emerald-950/20", borderColor: "border-emerald-200 dark:border-emerald-800/40",
  },
  conflict_resolution_required: {
    icon: AlertOctagon, label: "发现冲突，需要你决定", color: "text-red-600 dark:text-red-400",
    bgColor: "bg-red-50/80 dark:bg-red-950/20", borderColor: "border-red-200 dark:border-red-800/40",
  },
};

// ── Agent Orb ─────────────────────────────────────────────────────────────────

type AgentMood = "idle" | "working" | "waiting" | "paused" | "error";

function AgentOrb({ mood, size = 48 }: { mood: AgentMood; size?: number }) {
  const colors: Record<AgentMood, { core: string; glow: string }> = {
    idle:    { core: "from-slate-400 to-slate-500", glow: "bg-slate-400/20" },
    working: { core: "from-indigo-500 to-violet-500", glow: "bg-indigo-500/20" },
    waiting: { core: "from-amber-400 to-orange-400", glow: "bg-amber-400/20" },
    paused:  { core: "from-amber-400 to-amber-500", glow: "bg-amber-400/15" },
    error:   { core: "from-red-400 to-red-500", glow: "bg-red-400/20" },
  };
  const { core, glow } = colors[mood];
  const isActive = mood === "working";
  const isWaiting = mood === "waiting";

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <motion.div
        className={cn("absolute inset-0 rounded-full", glow)}
        animate={
          isActive
            ? { scale: [1, 1.6, 1], opacity: [0.4, 0, 0.4] }
            : isWaiting
              ? { scale: [1, 1.4, 1], opacity: [0.3, 0, 0.3] }
              : { scale: [1, 1.2, 1], opacity: [0.2, 0.1, 0.2] }
        }
        transition={{ duration: isActive ? 1.5 : isWaiting ? 2 : 3, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className={cn("absolute inset-1 rounded-full bg-gradient-to-br shadow-lg", core)}
        animate={isActive ? { scale: [1, 1.05, 1] } : { scale: [1, 1.02, 1] }}
        transition={{ duration: isActive ? 1.5 : 3, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  );
}


// ── Decision Card (Feature 1 + 3: Interrupt Types + Multi-Action) ─────────────

function DecisionCard({ approval, onApprove, onReject, onEditApprove, isSubmitting }: {
  approval: ApprovalRequest;
  onApprove: () => void;
  onReject: () => void;
  onEditApprove: (modifications: Record<string, any>) => void;
  isSubmitting: boolean;
}) {
  const [editMode, setEditMode] = useState(false);
  const [editComment, setEditComment] = useState("");

  const itype = (approval.interrupt_type || "approval_required") as InterruptType;
  const config = INTERRUPT_CONFIG[itype] || INTERRUPT_CONFIG.approval_required;
  const IconComp = config.icon;

  const handleEditApprove = () => {
    onEditApprove({ user_edit_comment: editComment });
    setEditMode(false);
    setEditComment("");
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("rounded-xl border p-4", config.bgColor, config.borderColor)}
    >
      {/* Header with interrupt type */}
      <div className="flex items-start gap-2.5 mb-3">
        <div className="relative mt-0.5">
          <motion.div
            className="absolute -inset-1.5 rounded-full bg-current opacity-20"
            animate={{ scale: [1, 1.3, 1], opacity: [0.2, 0, 0.2] }}
            transition={{ duration: 2, repeat: Infinity }}
          />
          <IconComp className={cn("relative w-4 h-4", config.color)} />
        </div>
        <div className="flex-1 min-w-0">
          <p className={cn("text-xs font-medium mb-0.5", config.color)}>
            {config.label}
          </p>
          <p className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed">
            {approval.message}
          </p>
        </div>
      </div>

      {/* Details / Impact */}
      {approval.details && Object.keys(approval.details).length > 0 && (
        <div className="mb-3 px-2 py-1.5 rounded-lg bg-black/5 dark:bg-white/5 text-[11px] text-slate-600 dark:text-slate-400">
          {approval.details.reason && <p>原因：{approval.details.reason}</p>}
          {approval.details.impact && <p className="mt-0.5">影响：{approval.details.impact}</p>}
          {approval.details.risk && <p className="mt-0.5">风险：{approval.details.risk}</p>}
        </div>
      )}

      {/* Edit mode (Feature 3: edit-then-approve) */}
      {editMode && (
        <div className="mb-3">
          <textarea
            value={editComment}
            onChange={e => setEditComment(e.target.value)}
            placeholder="描述你想修改的内容…"
            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-700 dark:text-slate-200 resize-none outline-none focus:border-indigo-300 dark:focus:border-indigo-600"
            rows={2}
          />
          <div className="flex gap-2 mt-2">
            <button
              onClick={handleEditApprove}
              disabled={isSubmitting || !editComment.trim()}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-500 hover:bg-indigo-600 text-white transition-colors disabled:opacity-50"
            >
              {isSubmitting && <Loader2 className="w-3 h-3 animate-spin" />}
              修改后批准
            </button>
            <button
              onClick={() => { setEditMode(false); setEditComment(""); }}
              className="px-3 py-1.5 rounded-lg text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* Action buttons */}
      {!editMode && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={onApprove}
            disabled={isSubmitting}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500 hover:bg-amber-600 text-white transition-colors disabled:opacity-50"
          >
            {isSubmitting && <Loader2 className="w-3 h-3 animate-spin" />}
            批准执行
          </button>
          <button
            onClick={() => setEditMode(true)}
            disabled={isSubmitting}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <Edit3 className="w-3 h-3" />
            编辑后批准
          </button>
          <button
            onClick={onReject}
            disabled={isSubmitting}
            className="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-slate-700 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            拒绝
          </button>
        </div>
      )}
    </motion.div>
  );
}


// ── Continuity Card (Feature 2: Real Data from pause_context_json) ────────────

function ContinuityCard({ session, stepViews, pauseContext, onResume, onCancel, isActioning }: {
  session: SessionItem;
  stepViews: NarrativeStepView[];
  pauseContext: PauseContext | null;
  onResume: () => void;
  onCancel: () => void;
  isActioning: boolean;
}) {
  // Use real pause context if available, fallback to step views
  const completedSteps = pauseContext?.completed_steps_summary
    ?? stepViews.filter(s => s.status === "completed").slice(-3).map(s => s.title);
  const completedCount = pauseContext?.completed_count
    ?? stepViews.filter(s => s.status === "completed").length;
  const pauseReason = pauseContext?.pause_reason ?? "用户主动暂停";
  const nextAction = pauseContext?.next_planned_action ?? null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-amber-200/60 dark:border-amber-800/30 bg-gradient-to-b from-amber-50/60 to-white dark:from-amber-950/10 dark:to-slate-900/50 p-4"
    >
      <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">
        这个任务已安全暂停
      </p>

      {/* Pause reason */}
      <p className="text-[11px] text-slate-400 mb-2">
        暂停原因：{pauseReason}
      </p>

      {/* What was done */}
      {completedSteps.length > 0 && (
        <div className="mb-2.5">
          <p className="text-[11px] text-slate-400 mb-1">暂停前已完成</p>
          <div className="space-y-0.5">
            {completedSteps.slice(-5).map((title, i) => (
              <p key={i} className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                {title}
              </p>
            ))}
            {completedCount > 5 && (
              <p className="text-[10px] text-slate-400">…还有 {completedCount - 5} 个步骤</p>
            )}
          </div>
        </div>
      )}

      {/* Progress */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
          <span>进度 {session.completed_nodes}/{session.total_nodes}</span>
          <span>{session.total_nodes > 0 ? Math.round((session.completed_nodes / session.total_nodes) * 100) : 0}%</span>
        </div>
        <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1">
          <div
            className="h-1 rounded-full bg-amber-400"
            style={{ width: `${session.total_nodes > 0 ? (session.completed_nodes / session.total_nodes) * 100 : 0}%` }}
          />
        </div>
      </div>

      {/* Resume info */}
      <p className="text-[11px] text-slate-400 mb-3">
        {nextAction
          ? `恢复后我会继续执行：${nextAction}`
          : "恢复后我会从中断点继续，不会重头开始。"}
      </p>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={onResume}
          disabled={isActioning}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-500 hover:bg-indigo-600 text-white transition-colors disabled:opacity-50"
        >
          <Play className="w-3 h-3" /> 继续执行
        </button>
        <button
          onClick={onCancel}
          disabled={isActioning}
          className="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-slate-700 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
        >
          取消任务
        </button>
      </div>
    </motion.div>
  );
}


// ── Narrative Stream ──────────────────────────────────────────────────────────

function NarrativeStream({ stepViews, maxItems = 6 }: {
  stepViews: NarrativeStepView[];
  maxItems?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? stepViews : stepViews.slice(-maxItems);

  if (stepViews.length === 0) return null;

  return (
    <div className="px-4 py-2">
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-[10px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider">
          我刚刚做了这些
        </p>
        {stepViews.length > maxItems && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-[10px] text-indigo-400 hover:text-indigo-500 flex items-center gap-0.5"
          >
            {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {expanded ? "收起" : `全部 ${stepViews.length} 步`}
          </button>
        )}
      </div>
      <div className="space-y-1">
        {visible.map((step) => {
          const icon = step.status === "completed"
            ? <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
            : step.status === "failed"
              ? <XCircle className="w-3 h-3 text-red-400 shrink-0" />
              : step.status === "running"
                ? <Loader2 className="w-3 h-3 text-indigo-400 animate-spin shrink-0" />
                : <div className="w-3 h-3 rounded-full border border-slate-300 dark:border-slate-600 shrink-0" />;

          return (
            <div key={step.step_id} className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              {icon}
              <span className="truncate flex-1">{step.title}</span>
              {step.duration_ms && (
                <span className="text-[10px] text-slate-300 dark:text-slate-600 tabular-nums shrink-0">
                  {formatDuration(step.duration_ms)}
                </span>
              )}
              {step.has_artifact && <Paperclip className="w-2.5 h-2.5 text-indigo-400 shrink-0" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Artifact Dock (Feature 4: Live Preview for HTML) ──────────────────────────

function ArtifactDock({ artifacts, sessions }: {
  artifacts: ArtifactRecord[];
  sessions: SessionItem[];
}) {
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactRecord | null>(null);

  if (artifacts.length === 0) return null;

  const recentArtifacts = artifacts.slice(0, 6);

  const isPreviewable = (a: ArtifactRecord) =>
    a.preview_state === "static" || a.preview_state === "live";

  const isHtmlPreviewable = (a: ArtifactRecord) =>
    (a.preview_state === "static" || a.preview_state === "live") &&
    (a.mime_type?.startsWith("text/html") || a.artifact_type === "website" || a.filename?.endsWith(".html"));

  const getIcon = (type: string, mime: string | null) => {
    if (mime?.startsWith("text/html") || type === "website") return <Globe className="w-3.5 h-3.5 text-indigo-400" />;
    if (mime?.startsWith("image/")) return <Eye className="w-3.5 h-3.5 text-violet-400" />;
    return <FileText className="w-3.5 h-3.5 text-slate-400" />;
  };

  return (
    <div className="px-4 py-2">
      <p className="text-[10px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1.5">
        最近产物
      </p>
      <div className="flex gap-2 overflow-x-auto scrollbar-hide">
        {recentArtifacts.map(a => (
          <div
            key={a.artifact_id}
            onClick={() => isPreviewable(a) ? setPreviewArtifact(a) : undefined}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-100/60 dark:bg-slate-800/40 border border-slate-200/50 dark:border-slate-700/30 shrink-0 transition-colors",
              isPreviewable(a) ? "cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-500/10 hover:border-indigo-200 dark:hover:border-indigo-700/30" : "cursor-default hover:bg-slate-100 dark:hover:bg-slate-800/60",
            )}
          >
            {getIcon(a.artifact_type, a.mime_type)}
            <span className="text-[11px] text-slate-600 dark:text-slate-300 max-w-[100px] truncate">
              {a.filename}
            </span>
            {isPreviewable(a) && <Eye className="w-2.5 h-2.5 text-indigo-400/60" />}
          </div>
        ))}
      </div>

      {/* Live Preview Modal (Feature 4) */}
      <AnimatePresence>
        {previewArtifact && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={() => setPreviewArtifact(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="relative w-[90vw] h-[80vh] max-w-5xl bg-white dark:bg-slate-900 rounded-2xl shadow-2xl overflow-hidden"
              onClick={e => e.stopPropagation()}
            >
              {/* Preview header */}
              <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                <div className="flex items-center gap-2">
                  {getIcon(previewArtifact.artifact_type, previewArtifact.mime_type)}
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {previewArtifact.filename}
                  </span>
                </div>
                <button
                  onClick={() => setPreviewArtifact(null)}
                  className="p-1 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                >
                  <X className="w-4 h-4 text-slate-500" />
                </button>
              </div>
              {/* Preview content */}
              <div className="w-full h-[calc(100%-40px)]">
                {isHtmlPreviewable(previewArtifact) ? (
                  <iframe
                    src={previewArtifact.preview_url || artifactApi.downloadUrl(previewArtifact.artifact_id)}
                    sandbox="allow-scripts allow-same-origin"
                    className="w-full h-full border-0"
                    title={`Preview: ${previewArtifact.filename}`}
                  />
                ) : previewArtifact.mime_type?.startsWith("image/") ? (
                  <div className="w-full h-full flex items-center justify-center bg-slate-100 dark:bg-slate-800">
                    <img
                      src={previewArtifact.preview_url || artifactApi.downloadUrl(previewArtifact.artifact_id)}
                      alt={previewArtifact.filename}
                      className="max-w-full max-h-full object-contain"
                    />
                  </div>
                ) : null}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}


// ── Task Orbit Item ───────────────────────────────────────────────────────────

function TaskOrbitItem({ session, isActive, onClick }: {
  session: SessionItem;
  isActive: boolean;
  onClick?: () => void;
}) {
  const failed = session.status === "failed" || session.result_status === "failed";
  const stale = session.status === "running" &&
    (Date.now() - new Date(session.started_at || "").getTime()) > STALE_THRESHOLD_MS;

  const narrative = stale
    ? "中断，可从上次位置恢复"
    : failed
      ? "执行失败"
      : session.status === "completed"
        ? "已完成"
        : session.total_nodes > 0
          ? `进行中 ${session.completed_nodes}/${session.total_nodes}`
          : "进行中";

  return (
    <div
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 px-3 py-1.5 rounded-lg transition-colors",
        "hover:bg-slate-100/50 dark:hover:bg-slate-800/30",
        isActive && "bg-indigo-50/50 dark:bg-indigo-500/5",
        onClick && "cursor-pointer"
      )}
    >
      {stale ? (
        <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0" />
      ) : failed ? (
        <XCircle className="w-3 h-3 text-red-400 shrink-0" />
      ) : session.status === "completed" ? (
        <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
      ) : (
        <div className="relative w-3 h-3 shrink-0">
          <span className="absolute inset-0 rounded-full bg-indigo-400 animate-ping opacity-40" />
          <span className="relative block w-3 h-3 rounded-full bg-indigo-500" />
        </div>
      )}

      <div className="flex-1 min-w-0">
        <p className="text-xs text-slate-600 dark:text-slate-300 truncate">
          {session.goal || "任务"}
        </p>
        <p className="text-[10px] text-slate-400 dark:text-slate-500 truncate">
          {narrative}
        </p>
      </div>

      <span className="text-[10px] text-slate-300 dark:text-slate-600 tabular-nums shrink-0">
        {timeAgo(session.completed_at || session.started_at)}
      </span>
    </div>
  );
}

// ── Command Bar ───────────────────────────────────────────────────────────────

function CommandBar({ onSend }: { onSend: (text: string) => void }) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim()) return;
    onSend(value.trim());
    setValue("");
  };

  return (
    <div className="px-3 py-2">
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100/80 dark:bg-slate-800/50 border border-slate-200/50 dark:border-slate-700/30 focus-within:border-indigo-300 dark:focus-within:border-indigo-600 transition-colors">
        <input
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleSubmit()}
          placeholder="给我一句话，例如：先别发布，把按钮改成深蓝"
          className="flex-1 bg-transparent text-xs text-slate-600 dark:text-slate-300 placeholder:text-slate-400 dark:placeholder:text-slate-500 outline-none"
        />
        <button
          onClick={handleSubmit}
          disabled={!value.trim()}
          className="p-1 rounded-md text-indigo-500 hover:bg-indigo-50 dark:hover:bg-indigo-500/10 transition-colors disabled:opacity-30"
        >
          <Send className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════════
// Stage — The dynamic center that morphs based on context
// ═══════════════════════════════════════════════════════════════════════════════

type StageMode = "working" | "decision" | "paused" | "completed" | "idle";

function Stage({
  mode, session, stepViews, narrativePhase, controlStatus,
  pendingApprovals, artifacts, pauseContext,
  onPauseResume, onCancel, onApprove, onReject, onEditApprove,
  isActioning, approvalSubmitting,
}: {
  mode: StageMode;
  session: SessionItem | null;
  stepViews: NarrativeStepView[];
  narrativePhase: { phase: string; description: string } | null;
  controlStatus: string;
  pendingApprovals: ApprovalRequest[];
  artifacts: ArtifactRecord[];
  pauseContext: PauseContext | null;
  onPauseResume: () => void;
  onCancel: () => void;
  onApprove: () => void;
  onReject: () => void;
  onEditApprove: (modifications: Record<string, any>) => void;
  isActioning: boolean;
  approvalSubmitting: boolean;
}) {
  const currentStep = stepViews.find(s => s.status === "running");
  const completedSteps = stepViews.filter(s => s.status === "completed");
  const progress = session && session.total_nodes > 0
    ? Math.round((session.completed_nodes / session.total_nodes) * 100) : 0;

  // ── Working Stage ──
  if (mode === "working" && session) {
    const headline = currentStep?.title || narrativePhase?.description || "正在处理中…";
    const completedSummary = completedSteps.length > 0
      ? completedSteps.slice(-3).map(s => s.title).join("、")
      : null;

    return (
      <div className="px-4 py-3">
        <p className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed mb-2">
          正在为你处理：<span className="font-medium">{session.goal || "任务"}</span>
        </p>
        {completedSummary && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
            我已经完成：{completedSummary}
          </p>
        )}
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
          当前：{headline}
        </p>
        <div className="mb-3">
          <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
            <span>步骤 {session.completed_nodes + 1}/{session.total_nodes}</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1">
            <motion.div
              className="h-1 rounded-full bg-indigo-500"
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.6, ease: "easeOut" }}
            />
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={onPauseResume}
            disabled={isActioning}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-50 text-amber-600 hover:bg-amber-100 dark:bg-amber-500/10 dark:text-amber-400 transition-colors disabled:opacity-50"
          >
            <Pause className="w-3 h-3" /> 暂停
          </button>
          <button
            onClick={onCancel}
            disabled={isActioning}
            className="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-slate-700 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      </div>
    );
  }

  // ── Decision Stage ──
  if (mode === "decision" && pendingApprovals.length > 0) {
    return (
      <div className="px-4 py-3">
        <DecisionCard
          approval={pendingApprovals[0]}
          onApprove={onApprove}
          onReject={onReject}
          onEditApprove={onEditApprove}
          isSubmitting={approvalSubmitting}
        />
        {pendingApprovals.length > 1 && (
          <p className="text-[10px] text-amber-500 mt-2 text-center">
            还有 {pendingApprovals.length - 1} 个决策等你处理
          </p>
        )}
      </div>
    );
  }

  // ── Paused Stage ──
  if (mode === "paused" && session) {
    return (
      <div className="px-4 py-3">
        <ContinuityCard
          session={session}
          stepViews={stepViews}
          pauseContext={pauseContext}
          onResume={onPauseResume}
          onCancel={onCancel}
          isActioning={isActioning}
        />
      </div>
    );
  }

  // ── Completed Stage (Feature 4: show live preview for HTML artifacts) ──
  if (mode === "completed" && session) {
    const sessionArtifacts = artifacts.filter(a => a.session_id === session.id);
    const htmlArtifact = sessionArtifacts.find(a =>
      (a.preview_state === "static" || a.preview_state === "live") &&
      (a.mime_type?.startsWith("text/html") || a.artifact_type === "website" || a.filename?.endsWith(".html"))
    );

    return (
      <div className="px-4 py-3">
        <div className="flex items-start gap-2.5 mb-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm text-slate-700 dark:text-slate-200">
              已完成：{session.goal || "任务"}
            </p>
            {sessionArtifacts.length > 0 && (
              <p className="text-xs text-slate-400 mt-1">
                产出了 {sessionArtifacts.length} 个成果物
              </p>
            )}
          </div>
        </div>

        {/* Inline HTML preview for completed website tasks */}
        {htmlArtifact && (
          <div className="mb-3 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
            <div className="flex items-center gap-1.5 px-2 py-1 bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
              <Globe className="w-3 h-3 text-indigo-400" />
              <span className="text-[10px] text-slate-500">{htmlArtifact.filename}</span>
            </div>
            <iframe
              src={htmlArtifact.preview_url || artifactApi.downloadUrl(htmlArtifact.artifact_id)}
              sandbox="allow-scripts allow-same-origin"
              className="w-full h-48 border-0"
              title={`Preview: ${htmlArtifact.filename}`}
            />
          </div>
        )}

        {sessionArtifacts.length > 0 && (
          <div className="flex gap-2 flex-wrap">
            {sessionArtifacts.slice(0, 3).map(a => (
              <div key={a.artifact_id} className="flex items-center gap-1 px-2 py-1 rounded-md bg-emerald-50 dark:bg-emerald-500/10 text-[11px] text-emerald-600 dark:text-emerald-400">
                <Paperclip className="w-2.5 h-2.5" />
                {a.filename}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ── Idle Stage ──
  return (
    <div className="px-4 py-6 flex flex-col items-center justify-center">
      <AgentOrb mood="idle" size={56} />
      <p className="text-xs text-slate-400 dark:text-slate-500 mt-3">
        系统待机中，随时可以给我任务
      </p>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════════
// Main Component — Agent Operating Surface
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
  const fetchedArtifactSessionsRef = useRef<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [isActioning, setIsActioning] = useState(false);
  const [approvalSubmitting, setApprovalSubmitting] = useState(false);
  const [pauseContext, setPauseContext] = useState<PauseContext | null>(null);

  // ── Data fetching ──
  const fetchData = useCallback(async () => {
    try {
      const [sessionList] = await Promise.allSettled([
        historyApi.listSessions(30),
      ]);

      if (sessionList.status === "fulfilled") {
        setSessions(sessionList.value);
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
    } catch (e) {
      console.error("Overview fetch error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Fetch pause context when paused ──
  useEffect(() => {
    if (controlStatus === "paused" && activeTask?.id) {
      getPauseContext(activeTask.id).then(ctx => setPauseContext(ctx)).catch(() => setPauseContext(null));
    } else {
      setPauseContext(null);
    }
  }, [controlStatus, activeTask?.id]);

  // ── Derived data ──
  const running = useMemo(() => sessions.filter(s => {
    if (s.status !== "running") return false;
    const startedAt = s.started_at ? new Date(s.started_at).getTime() : 0;
    const age = Date.now() - startedAt;
    if (age > STALE_THRESHOLD_MS && s.id !== activeTask?.id) return false;
    return true;
  }), [sessions, activeTask?.id]);

  const completed = useMemo(() => sessions.filter(
    s => s.status === "completed" || s.status === "failed"
  ), [sessions]);

  const runningCount = running.length;
  const primaryRunning = running.find(s => s.id === activeTask?.id) ?? running[0] ?? null;

  // ── Polling ──
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    const start = () => { interval = setInterval(fetchData, runningCount > 0 ? 8000 : 30000); };
    const onVis = () => { clearInterval(interval); if (document.visibilityState === "visible") start(); };
    start();
    document.addEventListener("visibilitychange", onVis);
    return () => { clearInterval(interval); document.removeEventListener("visibilitychange", onVis); };
  }, [fetchData, runningCount]);

  // ── Determine Stage Mode ──
  const isPaused = controlStatus === "paused";
  const stageMode: StageMode = useMemo(() => {
    if (pendingApprovals.length > 0) return "decision";
    if (isPaused && primaryRunning) return "paused";
    if (runningCount > 0 && primaryRunning) return "working";
    if (completed.length > 0) return "completed";
    return "idle";
  }, [pendingApprovals.length, isPaused, primaryRunning, runningCount, completed.length]);

  const agentMood: AgentMood = useMemo(() => {
    if (pendingApprovals.length > 0) return "waiting";
    if (isPaused) return "paused";
    if (runningCount > 0) return "working";
    return "idle";
  }, [pendingApprovals.length, isPaused, runningCount]);

  // ── Headline ──
  const headline = useMemo(() => {
    if (stageMode === "decision") return "我需要你做一个决定";
    if (stageMode === "paused") return "任务已暂停，等你继续";
    if (stageMode === "working" && primaryRunning) {
      return running.length > 1
        ? `我在同时处理 ${running.length} 件事`
        : `正在处理：${primaryRunning.goal || "任务"}`;
    }
    if (stageMode === "completed" && completed[0]) return "刚刚完成了一项任务";
    return "随时准备好为你工作";
  }, [stageMode, primaryRunning, running.length, completed]);

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

  const handleEditApprove = async (modifications: Record<string, any>) => {
    if (approvalSubmitting || pendingApprovals.length === 0) return;
    setApprovalSubmitting(true);
    try {
      await approvalApi.respond(pendingApprovals[0].request_id, true, undefined, modifications);
      removePendingApproval(pendingApprovals[0].request_id);
    } catch (e) { console.error("edit-approve failed", e); }
    finally { setApprovalSubmitting(false); }
  };

  const handleCommand = (text: string) => {
    setActiveTab("overview");
    window.dispatchEvent(new CustomEvent("agent-command", { detail: { text } }));
  };

  // Get narrative data for primary session
  const primaryStepViews = primaryRunning ? getNarrativeStepViews(primaryRunning.id) : [];
  const primaryPhase = primaryRunning ? getCurrentNarrativePhase(primaryRunning.id) : null;
  const latestCompleted = completed[0] ?? null;
  const stageSession = stageMode === "completed" ? latestCompleted : primaryRunning;

  // ── Render ──
  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-950 overflow-hidden">
      {/* ── Agent Presence Header ── */}
      <div className="shrink-0 px-4 py-3 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <AgentOrb mood={agentMood} size={36} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">
              {headline}
            </p>
            <div className="flex items-center gap-2 text-[10px] text-slate-400 dark:text-slate-500">
              <span className="relative flex h-1.5 w-1.5">
                {runningCount > 0 && isConnected && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                )}
                <span className={cn("relative inline-flex rounded-full h-1.5 w-1.5", isConnected ? "bg-emerald-500" : "bg-slate-400")} />
              </span>
              <span>{isConnected ? "在线" : "离线"}</span>
              {runningCount > 0 && <span className="tabular-nums">{runningCount} 个任务运行中</span>}
            </div>
          </div>
        </div>
      </div>

      {/* ── Main Content (scrollable) ── */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {/* ── Center Stage ── */}
        <AnimatePresence mode="wait">
          <motion.div
            key={stageMode}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2 }}
          >
            <Stage
              mode={stageMode}
              session={stageSession}
              stepViews={primaryStepViews}
              narrativePhase={primaryPhase}
              controlStatus={controlStatus}
              pendingApprovals={pendingApprovals}
              artifacts={artifacts}
              pauseContext={pauseContext}
              onPauseResume={handlePauseResume}
              onCancel={handleCancel}
              onApprove={handleApprove}
              onReject={handleReject}
              onEditApprove={handleEditApprove}
              isActioning={isActioning}
              approvalSubmitting={approvalSubmitting}
            />
          </motion.div>
        </AnimatePresence>

        {/* ── Narrative Stream ── */}
        {primaryStepViews.length > 0 && (
          <div className="border-t border-slate-100 dark:border-slate-800">
            <NarrativeStream stepViews={primaryStepViews} />
          </div>
        )}

        {/* ── Artifact Dock ── */}
        {artifacts.length > 0 && (
          <div className="border-t border-slate-100 dark:border-slate-800">
            <ArtifactDock artifacts={artifacts} sessions={sessions} />
          </div>
        )}

        {/* ── Task Orbit ── */}
        {(running.length > 1 || completed.length > 0) && (
          <div className="border-t border-slate-100 dark:border-slate-800 px-2 py-2">
            <p className="text-[10px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider px-2 mb-1">
              {running.length > 1 ? "其他任务" : "最近任务"}
            </p>
            {running.filter(s => s !== primaryRunning).map(s => (
              <TaskOrbitItem key={s.id} session={s} isActive={false} onClick={() => setActiveTab("logs")} />
            ))}
            {completed.slice(0, 4).map(s => (
              <TaskOrbitItem key={s.id} session={s} isActive={false} onClick={() => setActiveTab("history")} />
            ))}
            {completed.length > 4 && (
              <button
                onClick={() => setActiveTab("history")}
                className="flex items-center gap-1 px-3 py-1 text-[11px] text-indigo-500 hover:text-indigo-600 transition-colors"
              >
                查看全部 <ArrowRight className="w-3 h-3" />
              </button>
            )}
          </div>
        )}
      </div>

      {/* ── Command Bar (fixed bottom) ── */}
      <div className="shrink-0 border-t border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900">
        <CommandBar onSend={handleCommand} />
      </div>
    </div>
  );
}
