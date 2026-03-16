"use client";

import React, { useEffect, useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  History, CheckCircle2, XCircle, Loader2, ChevronRight, Clock,
  Cpu, AlertCircle, Paperclip, Download, GitBranch, Layers,
  ShieldAlert, DollarSign,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  historyApi, artifactApi,
  SessionItem, SessionDetail, SessionStep,
  SessionArtifact, TimelineEvent, ArtifactLineage,
} from "@/lib/api/history";
import { getSkillMeta } from "./StepPreview";
import { LoadingSpinner, EmptyState } from "@/components/ui/StateViews";
import { ApprovalView } from "./ApprovalView";
import { CostView } from "./CostView";
import { TraceViewer } from "./TraceViewer";
import { useChatStore } from "@/stores/chatStore";
import { useTaskStore } from "@/stores/taskStore";

type HistorySubTab = "sessions" | "approval" | "cost" | "trace";

// -----------------------------------------------------------------------
// HistoryView root
// -----------------------------------------------------------------------
export function HistoryView() {
  const [subTab, setSubTab] = useState<HistorySubTab>("sessions");
  const { pendingApprovals } = useTaskStore();
  const { sessionId } = useChatStore();

  const subTabs: { id: HistorySubTab; label: string; icon: React.ElementType; badge?: number }[] = [
    { id: "sessions", label: "Sessions", icon: History },
    { id: "approval", label: "Approval", icon: ShieldAlert, badge: pendingApprovals.length > 0 ? pendingApprovals.length : undefined },
    { id: "cost", label: "Cost", icon: DollarSign },
    { id: "trace", label: "Trace", icon: GitBranch },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-50 dark:bg-slate-950">
      {/* 子 tab bar */}
      <div className="shrink-0 flex items-center gap-1 px-3 py-1.5 bg-white dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800">
        {subTabs.map(t => {
          const Icon = t.icon;
          const active = subTab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setSubTab(t.id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
                active
                  ? "bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-100"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50"
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {t.label}
              {t.badge !== undefined && (
                <span className="ml-0.5 px-1.5 py-0.5 text-[9px] font-bold rounded-full bg-amber-500 text-white">
                  {t.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* 子视图内容 */}
      <div className="flex-1 overflow-hidden">
        {subTab === "sessions" && <SessionsView />}
        {subTab === "approval" && <ApprovalView />}
        {subTab === "cost" && <CostView />}
        {subTab === "trace" && <TraceViewer sessionId={sessionId ?? ""} />}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// SessionsView（原 HistoryView 主体内容，抽出为独立组件）
// -----------------------------------------------------------------------
function SessionsView() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    historyApi.listSessions(50).then(setSessions).catch(console.error).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    setDetailLoading(true);
    setSelectedStepId(null);
    historyApi.getSession(selectedId).then(setDetail).catch(console.error).finally(() => setDetailLoading(false));
  }, [selectedId]);

  const previewStep = useMemo(() => {
    if (!detail) return null;
    if (selectedStepId) return detail.steps.find(s => String(s.id) === selectedStepId) ?? null;
    return detail.steps.length > 0 ? detail.steps[detail.steps.length - 1] : null;
  }, [selectedStepId, detail]);

  if (loading) return <LoadingSpinner size="lg" />;

  if (sessions.length === 0) return (
    <EmptyState
      icon={History}
      title="No History"
      description="Task execution history will appear here"
      size="lg"
    />
  );

  return (
    <div className="h-full flex overflow-hidden bg-slate-50 dark:bg-slate-950">
      {/* 左侧：会话列表 */}
      <div className="w-[220px] shrink-0 border-r border-slate-200 dark:border-slate-800 overflow-y-auto custom-scrollbar bg-white dark:bg-slate-950">
        <div className="px-3 py-3 space-y-1">
          {sessions.map((s) => {
            const isSelected = selectedId === s.id;
            const isSuccess = s.result_status === "success" || s.status === "completed";
            const isFailed = s.result_status === "failed" || s.status === "failed";
            const date = s.created_at ? new Date(s.created_at) : null;
            return (
              <button key={s.id} onClick={() => setSelectedId(s.id)}
                className={cn("w-full flex items-start gap-2 px-2 py-2.5 rounded-lg text-left transition-all duration-150",
                  isSelected ? "bg-indigo-50 dark:bg-indigo-500/10" : "hover:bg-slate-50 dark:hover:bg-slate-800/50")}>
                <div className="shrink-0 mt-0.5">
                  {isSuccess ? <CheckCircle2 className="w-4 h-4 text-green-500" /> :
                   isFailed  ? <XCircle className="w-4 h-4 text-red-500" /> :
                               <Clock className="w-4 h-4 text-slate-400" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className={cn("text-xs font-medium truncate leading-snug",
                    isSelected ? "text-indigo-600 dark:text-indigo-400" : "text-slate-700 dark:text-slate-300")}>
                    {s.goal || "Untitled"}
                  </div>
                  {date && (
                    <div className="text-[10px] text-slate-400 mt-0.5 font-mono">
                      {date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}
                      {" "}{date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false })}
                    </div>
                  )}
                </div>
                {isSelected && <ChevronRight className="w-3 h-3 text-indigo-400 shrink-0 mt-1" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* 右侧 */}
      <div className="flex-1 flex overflow-hidden">
        {!selectedId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
            <History className="w-8 h-8 opacity-20" />
            <span className="text-xs">选择左侧任务查看执行详情</span>
          </div>
        ) : detailLoading ? (
          <div className="flex-1 flex items-center justify-center"><Loader2 className="w-5 h-5 text-indigo-500 animate-spin" /></div>
        ) : detail ? (
          <SessionReplay detail={detail} selectedStepId={selectedStepId} previewStep={previewStep} onSelectStep={(id) => setSelectedStepId(id)} />
        ) : null}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// SessionReplay — Steps / Timeline 双视图
// -----------------------------------------------------------------------
type ReplayView = "steps" | "timeline";

function SessionReplay({ detail, selectedStepId, previewStep, onSelectStep }: {
  detail: SessionDetail;
  selectedStepId: string | null;
  previewStep: SessionStep | null;
  onSelectStep: (id: string) => void;
}) {
  const [view, setView] = useState<ReplayView>("steps");
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [artifacts, setArtifacts] = useState<SessionArtifact[]>([]);

  const isSuccess = detail.result_status === "success" || detail.status === "completed";
  const isFailed  = detail.result_status === "failed"  || detail.status === "failed";
  const durationS = detail.started_at && detail.completed_at
    ? ((new Date(detail.completed_at).getTime() - new Date(detail.started_at).getTime()) / 1000).toFixed(1)
    : null;

  useEffect(() => {
    historyApi.getArtifacts(detail.id).then(r => setArtifacts(r.artifacts)).catch(console.error);
  }, [detail.id]);

  const loadTimeline = () => {
    if (timeline.length > 0) return;
    setTimelineLoading(true);
    historyApi.getTimeline(detail.id).then(r => setTimeline(r.timeline)).catch(console.error).finally(() => setTimelineLoading(false));
  };

  const handleViewChange = (v: ReplayView) => {
    setView(v);
    if (v === "timeline") loadTimeline();
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 头部 */}
      <div className="shrink-0 px-5 py-4 bg-white dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">History</span>
          {isSuccess && <span className="text-[10px] font-bold text-green-500 bg-green-50 dark:bg-green-500/10 px-1.5 py-0.5 rounded-full">成功</span>}
          {isFailed  && <span className="text-[10px] font-bold text-red-500 bg-red-50 dark:bg-red-500/10 px-1.5 py-0.5 rounded-full">失败</span>}
        </div>
        <p className="text-sm font-medium text-slate-800 dark:text-slate-100 leading-snug line-clamp-2">{detail.goal || "Untitled Task"}</p>
        <div className="mt-2 flex items-center gap-3 text-[10px] font-mono text-slate-400">
          {detail.started_at && <span>{new Date(detail.started_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>}
          {durationS && <><span>·</span><span>耗时 {durationS}s</span></>}
          <span>·</span><span>{detail.steps.length} 步骤</span>
          {artifacts.length > 0 && <><span>·</span><span>{artifacts.length} 产物</span></>}
        </div>
        {/* 视图切换 */}
        <div className="mt-3 flex gap-1">
          {(["steps", "timeline"] as ReplayView[]).map(v => (
            <button key={v} onClick={() => handleViewChange(v)}
              className={cn("px-2.5 py-1 rounded text-[10px] font-medium capitalize transition-colors",
                view === v ? "bg-indigo-500 text-white" : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800")}>
              {v === "steps" ? <span className="flex items-center gap-1"><Layers className="w-3 h-3" />Steps</span>
                             : <span className="flex items-center gap-1"><GitBranch className="w-3 h-3" />Timeline</span>}
            </button>
          ))}
        </div>
      </div>

      {/* 内容区 */}
      <div className="flex-1 flex overflow-hidden">
        {view === "steps" ? (
          <StepsView detail={detail} previewStep={previewStep} artifacts={artifacts} onSelectStep={onSelectStep} />
        ) : (
          <TimelineView events={timeline} loading={timelineLoading} />
        )}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// Steps 视图（原有逻辑）
// -----------------------------------------------------------------------
function StepsView({ detail, previewStep, artifacts, onSelectStep }: {
  detail: SessionDetail;
  previewStep: SessionStep | null;
  artifacts: SessionArtifact[];
  onSelectStep: (id: string) => void;
}) {
  return (
    <div className="flex-1 flex overflow-hidden">
      {/* 步骤列表 */}
      <div className="w-[200px] shrink-0 border-r border-slate-200 dark:border-slate-800 overflow-y-auto custom-scrollbar bg-white dark:bg-slate-950 py-3">
        <div className="px-3 space-y-1">
          {detail.steps.map((step) => {
            const { label } = getSkillMeta(step.step_type ?? undefined);
            const isDone    = step.status === "success" || step.status === "completed";
            const isFailed  = step.status === "failed";
            const isSelected = previewStep?.id === step.id;
            return (
              <button key={step.id} onClick={() => onSelectStep(String(step.id))}
                className={cn("w-full flex items-center gap-2 px-2 py-2 rounded-lg text-left transition-all duration-150",
                  isSelected ? "bg-indigo-50 dark:bg-indigo-500/10" : "hover:bg-slate-50 dark:hover:bg-slate-800/50")}>
                <div className={cn("shrink-0 w-5 h-5 flex items-center justify-center",
                  isDone ? "text-green-500" : isFailed ? "text-red-500" : "text-slate-400")}>
                  {isDone ? <CheckCircle2 className="w-4 h-4" /> : isFailed ? <AlertCircle className="w-4 h-4" /> : <Clock className="w-4 h-4" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className={cn("text-xs font-medium truncate", isSelected ? "text-indigo-600 dark:text-indigo-400" : "text-slate-600 dark:text-slate-400")}>{label}</div>
                  <div className="text-[10px] text-slate-400 truncate font-mono">{step.step_type ?? `step ${step.id}`}</div>
                </div>
                {step.artifact_ids.length > 0 && <Paperclip className="w-3 h-3 text-indigo-400 shrink-0" />}
                {isSelected && <ChevronRight className="w-3 h-3 text-indigo-400 shrink-0" />}
              </button>
            );
          })}
          {detail.steps.length === 0 && <div className="text-xs text-slate-400 text-center py-8">无步骤记录</div>}
        </div>
      </div>

      {/* 步骤详情 */}
      <div className="flex-1 overflow-y-auto custom-scrollbar bg-slate-50 dark:bg-slate-950">
        <AnimatePresence mode="wait">
          {previewStep ? (
            <motion.div key={previewStep.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} className="p-4 space-y-4">
              <StepDetail step={previewStep} sessionArtifacts={artifacts} />
            </motion.div>
          ) : (
            <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="h-full flex flex-col items-center justify-center text-slate-400 gap-2 p-8">
              <Cpu className="w-8 h-8 opacity-20" />
              <span className="text-xs">点击左侧步骤查看详情</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// Timeline 视图（三层 trace）
// -----------------------------------------------------------------------
const LAYER_COLOR: Record<string, string> = {
  session: "bg-indigo-500",
  step:    "bg-purple-500",
  event:   "bg-slate-400",
};

function TimelineView({ events, loading }: { events: TimelineEvent[]; loading: boolean }) {
  if (loading) return <div className="flex-1 flex items-center justify-center"><Loader2 className="w-5 h-5 text-indigo-500 animate-spin" /></div>;
  if (events.length === 0) return (
    <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
      <GitBranch className="w-8 h-8 opacity-20" />
      <span className="text-xs">No trace data</span>
    </div>
  );

  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar px-4 py-3">
      <div className="relative">
        {/* 竖线 */}
        <div className="absolute left-[7px] top-0 bottom-0 w-px bg-slate-200 dark:bg-slate-800" />
        <div className="space-y-2">
          {events.map((ev, i) => {
            const dot = LAYER_COLOR[ev.layer] ?? "bg-slate-400";
            const ts = ev.timestamp ? new Date(ev.timestamp) : null;
            return (
              <div key={i} className="flex gap-3 items-start">
                <div className={cn("w-3.5 h-3.5 rounded-full shrink-0 mt-0.5 ring-2 ring-white dark:ring-slate-950", dot)} />
                <div className="flex-1 min-w-0 pb-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-medium text-slate-700 dark:text-slate-300">{ev.event_type}</span>
                    <span className={cn("text-[9px] font-bold uppercase px-1 py-0.5 rounded",
                      ev.layer === "session" ? "bg-indigo-100 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-400" :
                      ev.layer === "step"    ? "bg-purple-100 text-purple-600 dark:bg-purple-500/20 dark:text-purple-400" :
                                              "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400")}>
                      {ev.layer}
                    </span>
                    {ts && <span className="text-[10px] font-mono text-slate-400 ml-auto">{ts.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</span>}
                  </div>
                  {ev.step_id && <div className="text-[10px] font-mono text-slate-400 truncate">step: {ev.step_id}</div>}
                  {ev.error_message && <div className="text-[10px] text-red-500 truncate">{ev.error_message}</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// StepDetail（含 artifact 血缘展开）
// -----------------------------------------------------------------------
function StepDetail({ step, sessionArtifacts }: { step: SessionStep; sessionArtifacts: SessionArtifact[] }) {
  const { label } = getSkillMeta(step.step_type ?? undefined);
  const isDone   = step.status === "success" || step.status === "completed";
  const isFailed = step.status === "failed";

  // 从 session-level artifacts 里过滤出本 step 的产物
  const stepArtifacts = sessionArtifacts.filter(a => a.step_id === step.step_id);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 flex items-center justify-center">
          {(() => { const { icon: Icon } = getSkillMeta(step.step_type ?? undefined); return <Icon className="w-4 h-4 text-indigo-500" />; })()}
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{label}</div>
          <div className="text-[10px] font-mono text-slate-400">{step.step_type}</div>
        </div>
        <div className="ml-auto">
          {isDone   && <span className="text-[10px] font-bold text-green-500 bg-green-50 dark:bg-green-500/10 px-2 py-0.5 rounded-full">完成</span>}
          {isFailed && <span className="text-[10px] font-bold text-red-500 bg-red-50 dark:bg-red-500/10 px-2 py-0.5 rounded-full">失败</span>}
        </div>
      </div>

      {step.timing.duration_s != null && (
        <div className="text-[10px] font-mono text-slate-400">
          耗时 {step.timing.duration_s.toFixed(2)}s{step.retry_count > 0 && ` · 重试 ${step.retry_count} 次`}
        </div>
      )}

      {step.error_message && (
        <div className="rounded-lg border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-900/10 p-3 text-xs text-red-600 dark:text-red-400 font-mono whitespace-pre-wrap break-all">
          {step.error_message}
        </div>
      )}

      {step.summary && (
        <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
          <div className="px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400">输出摘要</div>
          <pre className="p-3 text-xs text-slate-700 dark:text-slate-300 font-mono whitespace-pre-wrap break-all overflow-x-auto max-h-60">{step.summary}</pre>
        </div>
      )}

      {stepArtifacts.length > 0 && <ArtifactList artifacts={stepArtifacts} />}
    </div>
  );
}

// -----------------------------------------------------------------------
// ArtifactList — session-level 批量数据 + lineage 展开
// -----------------------------------------------------------------------
function ArtifactList({ artifacts }: { artifacts: SessionArtifact[] }) {
  const [lineage, setLineage] = useState<Record<string, ArtifactLineage | null>>({});
  const [lineageLoading, setLineageLoading] = useState<Record<string, boolean>>({});

  const toggleLineage = async (artifactId: string) => {
    if (lineage[artifactId] !== undefined) {
      setLineage(l => { const n = { ...l }; delete n[artifactId]; return n; });
      return;
    }
    setLineageLoading(l => ({ ...l, [artifactId]: true }));
    try {
      const data = await artifactApi.getLineage(artifactId);
      setLineage(l => ({ ...l, [artifactId]: data }));
    } catch {
      setLineage(l => ({ ...l, [artifactId]: null }));
    } finally {
      setLineageLoading(l => ({ ...l, [artifactId]: false }));
    }
  };

  const fmtSize = (b: number) => b < 1024 ? `${b}B` : b < 1048576 ? `${(b/1024).toFixed(1)}KB` : `${(b/1048576).toFixed(1)}MB`;

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
        <Paperclip className="w-3 h-3" /> 产物 ({artifacts.length})
      </div>
      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {artifacts.map((r) => (
          <div key={r.artifact_id}>
            <div className="flex items-center gap-3 px-3 py-2">
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">{r.filename}</div>
                <div className="text-[10px] text-slate-400 font-mono">{r.artifact_type}{r.size > 0 && ` · ${fmtSize(r.size)}`}</div>
              </div>
              <button onClick={() => toggleLineage(r.artifact_id)}
                className={cn("shrink-0 p-1.5 rounded-md transition-colors text-slate-400",
                  lineage[r.artifact_id] !== undefined ? "bg-indigo-50 dark:bg-indigo-500/10 text-indigo-500" : "hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-indigo-500")}
                title="血缘">
                {lineageLoading[r.artifact_id] ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <GitBranch className="w-3.5 h-3.5" />}
              </button>
              <a href={artifactApi.downloadUrl(r.artifact_id)} download={r.filename}
                className="shrink-0 p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-indigo-500 transition-colors" title="下载">
                <Download className="w-3.5 h-3.5" />
              </a>
            </div>
            {/* 血缘展开 */}
            {lineage[r.artifact_id] && (
              <div className="px-3 pb-2 bg-slate-50 dark:bg-slate-900/50 border-t border-slate-100 dark:border-slate-800">
                <LineagePanel lineage={lineage[r.artifact_id]!} />
              </div>
            )}
            {lineage[r.artifact_id] === null && (
              <div className="px-3 pb-2 text-[10px] text-red-400">血缘加载失败</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function LineagePanel({ lineage }: { lineage: ArtifactLineage }) {
  return (
    <div className="pt-2 space-y-2 text-[10px]">
      <div className="flex items-center gap-1 text-slate-500 font-medium">
        <GitBranch className="w-3 h-3" /> Lineage
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <div className="text-slate-400 mb-1 uppercase tracking-wider font-bold">Produced by</div>
          <div className="font-mono text-slate-600 dark:text-slate-400 truncate">{lineage.produced_by.step_id ?? "—"}</div>
        </div>
        <div>
          <div className="text-slate-400 mb-1 uppercase tracking-wider font-bold">Siblings ({lineage.siblings.length})</div>
          {lineage.siblings.length === 0 ? <span className="text-slate-400">—</span> :
            lineage.siblings.map(s => <div key={s.artifact_id} className="font-mono text-slate-600 dark:text-slate-400 truncate">{s.filename}</div>)}
        </div>
        <div>
          <div className="text-slate-400 mb-1 uppercase tracking-wider font-bold">Downstream ({lineage.downstream.length})</div>
          {lineage.downstream.length === 0 ? <span className="text-slate-400">—</span> :
            lineage.downstream.map(d => <div key={d.artifact_id} className="font-mono text-slate-600 dark:text-slate-400 truncate">{d.filename}</div>)}
        </div>
      </div>
    </div>
  );
}
