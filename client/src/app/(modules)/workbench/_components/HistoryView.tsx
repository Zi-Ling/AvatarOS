"use client";

import React, { useEffect, useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  History,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronRight,
  Clock,
  Cpu,
  AlertCircle,
  Paperclip,
  Download,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { historyApi, artifactApi, SessionItem, SessionDetail, SessionStep, ArtifactRecord } from "@/lib/api/history";
import { getSkillMeta } from "./StepPreview";

// SessionStep → StepLike（供 StepPreview 复用）
function stepToStepLike(s: SessionStep) {
  return {
    id: String(s.id),
    skill_name: s.step_type ?? undefined,
    params: undefined,
    output_result: s.summary ? { text: s.summary } : undefined,
    status: s.status,
  };
}

export function HistoryView() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    historyApi.listSessions(50)
      .then(setSessions)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    setDetailLoading(true);
    setSelectedStepId(null);
    historyApi.getSession(selectedId)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setDetailLoading(false));
  }, [selectedId]);

  const previewStep = useMemo(() => {
    if (!detail) return null;
    if (selectedStepId) return detail.steps.find(s => String(s.id) === selectedStepId) ?? null;
    return detail.steps.length > 0 ? detail.steps[detail.steps.length - 1] : null;
  }, [selectedStepId, detail]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-indigo-500 animate-spin" />
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-400 gap-3">
        <div className="w-16 h-16 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
          <History className="w-8 h-8 opacity-20 text-slate-500" />
        </div>
        <span className="font-medium text-slate-500 dark:text-slate-400 text-sm">No History</span>
        <span className="text-xs text-slate-400">Task execution history will appear here</span>
      </div>
    );
  }

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
              <button
                key={s.id}
                onClick={() => setSelectedId(s.id)}
                className={cn(
                  "w-full flex items-start gap-2 px-2 py-2.5 rounded-lg text-left transition-all duration-150",
                  isSelected ? "bg-indigo-50 dark:bg-indigo-500/10" : "hover:bg-slate-50 dark:hover:bg-slate-800/50",
                )}
              >
                <div className="shrink-0 mt-0.5">
                  {isSuccess ? (
                    <CheckCircle2 className="w-4 h-4 text-green-500" />
                  ) : isFailed ? (
                    <XCircle className="w-4 h-4 text-red-500" />
                  ) : (
                    <Clock className="w-4 h-4 text-slate-400" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className={cn(
                    "text-xs font-medium truncate leading-snug",
                    isSelected ? "text-indigo-600 dark:text-indigo-400" : "text-slate-700 dark:text-slate-300",
                  )}>
                    {s.goal || "Untitled"}
                  </div>
                  {date && (
                    <div className="text-[10px] text-slate-400 mt-0.5 font-mono">
                      {date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}
                      {" "}
                      {date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false })}
                    </div>
                  )}
                </div>
                {isSelected && <ChevronRight className="w-3 h-3 text-indigo-400 shrink-0 mt-1" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* 右侧：执行回放 */}
      <div className="flex-1 flex overflow-hidden">
        {!selectedId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
            <History className="w-8 h-8 opacity-20" />
            <span className="text-xs">选择左侧任务查看执行详情</span>
          </div>
        ) : detailLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-5 h-5 text-indigo-500 animate-spin" />
          </div>
        ) : detail ? (
          <SessionReplay
            detail={detail}
            selectedStepId={selectedStepId}
            previewStep={previewStep}
            onSelectStep={(id) => setSelectedStepId(id)}
          />
        ) : null}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// 执行回放面板
// -----------------------------------------------------------------------

function SessionReplay({
  detail,
  selectedStepId,
  previewStep,
  onSelectStep,
}: {
  detail: SessionDetail;
  selectedStepId: string | null;
  previewStep: SessionStep | null;
  onSelectStep: (id: string) => void;
}) {
  const isSuccess = detail.result_status === "success" || detail.status === "completed";
  const isFailed = detail.result_status === "failed" || detail.status === "failed";

  const durationS = detail.started_at && detail.completed_at
    ? ((new Date(detail.completed_at).getTime() - new Date(detail.started_at).getTime()) / 1000).toFixed(1)
    : null;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 任务头部 */}
      <div className="shrink-0 px-5 py-4 bg-white dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">History</span>
          {isSuccess && <span className="text-[10px] font-bold text-green-500 bg-green-50 dark:bg-green-500/10 px-1.5 py-0.5 rounded-full">成功</span>}
          {isFailed && <span className="text-[10px] font-bold text-red-500 bg-red-50 dark:bg-red-500/10 px-1.5 py-0.5 rounded-full">失败</span>}
        </div>
        <p className="text-sm font-medium text-slate-800 dark:text-slate-100 leading-snug line-clamp-2">
          {detail.goal || "Untitled Task"}
        </p>
        <div className="mt-2 flex items-center gap-3 text-[10px] font-mono text-slate-400">
          {detail.started_at && (
            <span>{new Date(detail.started_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
          )}
          {durationS && <><span>·</span><span>耗时 {durationS}s</span></>}
          <span>·</span>
          <span>{detail.steps.length} 步骤</span>
        </div>
      </div>

      {/* 左右分栏 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 步骤时间线 */}
        <div className="w-[200px] shrink-0 border-r border-slate-200 dark:border-slate-800 overflow-y-auto custom-scrollbar bg-white dark:bg-slate-950 py-3">
          <div className="px-3 space-y-1">
            {detail.steps.map((step) => {
              const { label } = getSkillMeta(step.step_type ?? undefined);
              const isDone = step.status === "success" || step.status === "completed";
              const isFailed = step.status === "failed";
              const isSelected = previewStep?.id === step.id;

              return (
                <button
                  key={step.id}
                  onClick={() => onSelectStep(String(step.id))}
                  className={cn(
                    "w-full flex items-center gap-2 px-2 py-2 rounded-lg text-left transition-all duration-150",
                    isSelected ? "bg-indigo-50 dark:bg-indigo-500/10" : "hover:bg-slate-50 dark:hover:bg-slate-800/50",
                  )}
                >
                  <div className={cn(
                    "shrink-0 w-5 h-5 flex items-center justify-center",
                    isDone ? "text-green-500" : isFailed ? "text-red-500" : "text-slate-400",
                  )}>
                    {isDone ? <CheckCircle2 className="w-4 h-4" /> :
                     isFailed ? <AlertCircle className="w-4 h-4" /> :
                     <Clock className="w-4 h-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className={cn(
                      "text-xs font-medium truncate",
                      isSelected ? "text-indigo-600 dark:text-indigo-400" : "text-slate-600 dark:text-slate-400",
                    )}>
                      {label}
                    </div>
                    <div className="text-[10px] text-slate-400 truncate font-mono">
                      {step.step_type ?? `step ${step.id}`}
                    </div>
                  </div>
                  {step.artifact_ids.length > 0 && (
                    <Paperclip className="w-3 h-3 text-indigo-400 shrink-0" />
                  )}
                  {isSelected && <ChevronRight className="w-3 h-3 text-indigo-400 shrink-0" />}
                </button>
              );
            })}
            {detail.steps.length === 0 && (
              <div className="text-xs text-slate-400 text-center py-8">无步骤记录</div>
            )}
          </div>
        </div>

        {/* 步骤详情 */}
        <div className="flex-1 overflow-y-auto custom-scrollbar bg-slate-50 dark:bg-slate-950">
          <AnimatePresence mode="wait">
            {previewStep ? (
              <motion.div
                key={previewStep.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="p-4 space-y-4"
              >
                <StepDetail step={previewStep} />
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="h-full flex flex-col items-center justify-center text-slate-400 gap-2 p-8"
              >
                <Cpu className="w-8 h-8 opacity-20" />
                <span className="text-xs">点击左侧步骤查看详情</span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// 步骤详情（含 summary + artifacts）
// -----------------------------------------------------------------------

function StepDetail({ step }: { step: SessionStep }) {
  const { label } = getSkillMeta(step.step_type ?? undefined);
  const isDone = step.status === "success" || step.status === "completed";
  const isFailed = step.status === "failed";

  return (
    <div className="space-y-3">
      {/* 头部 */}
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 flex items-center justify-center">
          {(() => {
            const { icon: Icon } = getSkillMeta(step.step_type ?? undefined);
            return <Icon className="w-4 h-4 text-indigo-500" />;
          })()}
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{label}</div>
          <div className="text-[10px] font-mono text-slate-400">{step.step_type}</div>
        </div>
        <div className="ml-auto">
          {isDone && <span className="text-[10px] font-bold text-green-500 bg-green-50 dark:bg-green-500/10 px-2 py-0.5 rounded-full">完成</span>}
          {isFailed && <span className="text-[10px] font-bold text-red-500 bg-red-50 dark:bg-red-500/10 px-2 py-0.5 rounded-full">失败</span>}
        </div>
      </div>

      {/* 时间 */}
      {step.timing.duration_s != null && (
        <div className="text-[10px] font-mono text-slate-400">
          耗时 {step.timing.duration_s.toFixed(2)}s
          {step.retry_count > 0 && ` · 重试 ${step.retry_count} 次`}
        </div>
      )}

      {/* 错误 */}
      {step.error_message && (
        <div className="rounded-lg border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-900/10 p-3 text-xs text-red-600 dark:text-red-400 font-mono whitespace-pre-wrap break-all">
          {step.error_message}
        </div>
      )}

      {/* 输出摘要 */}
      {step.summary && (
        <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
          <div className="px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            输出摘要
          </div>
          <pre className="p-3 text-xs text-slate-700 dark:text-slate-300 font-mono whitespace-pre-wrap break-all overflow-x-auto max-h-60">
            {step.summary}
          </pre>
        </div>
      )}

      {/* Artifacts */}
      {step.artifact_ids.length > 0 && (
        <ArtifactList artifactIds={step.artifact_ids} />
      )}
    </div>
  );
}

// -----------------------------------------------------------------------
// Artifact 列表（懒加载元数据）
// -----------------------------------------------------------------------

function ArtifactList({ artifactIds }: { artifactIds: string[] }) {
  const [records, setRecords] = useState<ArtifactRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all(artifactIds.map((id) => artifactApi.get(id).catch(() => null)))
      .then((results) => setRecords(results.filter(Boolean) as ArtifactRecord[]))
      .finally(() => setLoading(false));
  }, [artifactIds.join(",")]);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
      <div className="px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
        <Paperclip className="w-3 h-3" /> 产物 ({artifactIds.length})
      </div>
      {loading ? (
        <div className="p-3 flex items-center gap-2 text-xs text-slate-400">
          <Loader2 className="w-3 h-3 animate-spin" /> 加载中...
        </div>
      ) : (
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          {records.map((r) => (
            <div key={r.artifact_id} className="flex items-center gap-3 px-3 py-2">
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">{r.filename}</div>
                <div className="text-[10px] text-slate-400 font-mono">
                  {r.artifact_type}
                  {r.size > 0 && ` · ${r.size < 1024 ? `${r.size}B` : r.size < 1048576 ? `${(r.size / 1024).toFixed(1)}KB` : `${(r.size / 1048576).toFixed(1)}MB`}`}
                </div>
              </div>
              <a
                href={artifactApi.downloadUrl(r.artifact_id)}
                download={r.filename}
                className="shrink-0 p-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-indigo-500 transition-colors"
                title="下载"
              >
                <Download className="w-3.5 h-3.5" />
              </a>
            </div>
          ))}
          {records.length === 0 && (
            <div className="p-3 text-xs text-slate-400">产物文件已过期或不可用</div>
          )}
        </div>
      )}
    </div>
  );
}
