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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { historyApi, TaskHistoryItem, TaskStep } from "@/lib/api/history";
import { StepPreview, getSkillMeta } from "./StepPreview";
import type { StepLike } from "./StepPreview";

// 将 history API 的 TaskStep 映射为 StepLike
function mapStep(s: TaskStep): StepLike {
  return {
    id: s.id,
    skill_name: s.skill_name,
    params: s.input_params,
    output_result: s.output_result,
    status: s.status,
  };
}

export function HistoryView() {
  const [tasks, setTasks] = useState<TaskHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [taskDetail, setTaskDetail] = useState<TaskHistoryItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    historyApi.listTasks(50)
      .then(setTasks)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // 选中任务时加载详情
  useEffect(() => {
    if (!selectedTaskId) { setTaskDetail(null); return; }
    setDetailLoading(true);
    setSelectedStepId(null);
    historyApi.getTask(selectedTaskId)
      .then(setTaskDetail)
      .catch(console.error)
      .finally(() => setDetailLoading(false));
  }, [selectedTaskId]);

  // 当前展示的步骤列表（取最近一次 run 的 steps）
  const steps: StepLike[] = useMemo(() => {
    const run = taskDetail?.runs?.[0];
    return (run?.steps ?? []).map(mapStep);
  }, [taskDetail]);

  const previewStep = useMemo(() => {
    if (selectedStepId) return steps.find(s => s.id === selectedStepId) ?? null;
    return steps.length > 0 ? steps[steps.length - 1] : null;
  }, [selectedStepId, steps]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-indigo-500 animate-spin" />
      </div>
    );
  }

  if (tasks.length === 0) {
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
      {/* 左侧：任务列表 */}
      <div className="w-[220px] shrink-0 border-r border-slate-200 dark:border-slate-800 overflow-y-auto custom-scrollbar bg-white dark:bg-slate-950">
        <div className="px-3 py-3 space-y-1">
          {tasks.map((task) => {
            const run = task.runs?.[0];
            const isSelected = selectedTaskId === task.id;
            const status = run?.status ?? 'unknown';
            const date = new Date(task.created_at);

            return (
              <button
                key={task.id}
                onClick={() => setSelectedTaskId(task.id)}
                className={cn(
                  'w-full flex items-start gap-2 px-2 py-2.5 rounded-lg text-left transition-all duration-150',
                  isSelected ? 'bg-indigo-50 dark:bg-indigo-500/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800/50',
                )}
              >
                <div className="shrink-0 mt-0.5">
                  {status === 'completed' || status === 'success' ? (
                    <CheckCircle2 className="w-4 h-4 text-green-500" />
                  ) : status === 'failed' ? (
                    <XCircle className="w-4 h-4 text-red-500" />
                  ) : (
                    <Clock className="w-4 h-4 text-slate-400" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className={cn(
                    'text-xs font-medium truncate leading-snug',
                    isSelected ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-700 dark:text-slate-300'
                  )}>
                    {task.title || task.intent_spec?.goal || 'Untitled'}
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5 font-mono">
                    {date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })}
                    {' '}
                    {date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false })}
                  </div>
                </div>
                {isSelected && <ChevronRight className="w-3 h-3 text-indigo-400 shrink-0 mt-1" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* 右侧：执行回放 */}
      <div className="flex-1 flex overflow-hidden">
        {!selectedTaskId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
            <History className="w-8 h-8 opacity-20" />
            <span className="text-xs">选择左侧任务查看执行详情</span>
          </div>
        ) : detailLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-5 h-5 text-indigo-500 animate-spin" />
          </div>
        ) : taskDetail ? (
          <TaskReplay
            task={taskDetail}
            steps={steps}
            selectedStepId={selectedStepId}
            previewStep={previewStep}
            onSelectStep={setSelectedStepId}
          />
        ) : null}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// 执行回放面板（复用 ActiveTaskView 的左右分栏结构）
// -----------------------------------------------------------------------

function TaskReplay({
  task,
  steps,
  selectedStepId,
  previewStep,
  onSelectStep,
}: {
  task: TaskHistoryItem;
  steps: StepLike[];
  selectedStepId: string | null;
  previewStep: StepLike | null;
  onSelectStep: (id: string) => void;
}) {
  const run = task.runs?.[0];
  const isSuccess = run?.status === 'completed' || run?.status === 'success';
  const isFailed = run?.status === 'failed';

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
          {task.title || task.intent_spec?.goal || 'Untitled Task'}
        </p>
        {run?.summary && (
          <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400 line-clamp-2">{run.summary}</p>
        )}
        {run?.started_at && run?.finished_at && (
          <div className="mt-2 flex items-center gap-3 text-[10px] font-mono text-slate-400">
            <span>{new Date(run.started_at).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
            <span>·</span>
            <span>耗时 {((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000).toFixed(1)}s</span>
            <span>·</span>
            <span>{steps.length} 步骤</span>
          </div>
        )}
      </div>

      {/* 左右分栏 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 步骤时间线 */}
        <div className="w-[200px] shrink-0 border-r border-slate-200 dark:border-slate-800 overflow-y-auto custom-scrollbar bg-white dark:bg-slate-950 py-3">
          <div className="px-3 space-y-1">
            {steps.map((step, index) => {
              const { label } = getSkillMeta(step.skill_name);
              const isDone = step.status === 'completed' || step.status === 'success';
              const isFailed = step.status === 'failed';
              const isSelected = previewStep?.id === step.id;

              return (
                <button
                  key={step.id}
                  onClick={() => onSelectStep(step.id)}
                  className={cn(
                    'w-full flex items-center gap-2 px-2 py-2 rounded-lg text-left transition-all duration-150',
                    isSelected ? 'bg-indigo-50 dark:bg-indigo-500/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800/50',
                  )}
                >
                  <div className={cn(
                    'shrink-0 w-5 h-5 flex items-center justify-center',
                    isDone ? 'text-green-500' : isFailed ? 'text-red-500' : 'text-slate-400'
                  )}>
                    {isDone ? <CheckCircle2 className="w-4 h-4" /> :
                     isFailed ? <AlertCircle className="w-4 h-4" /> :
                     <Clock className="w-4 h-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className={cn(
                      'text-xs font-medium truncate',
                      isSelected ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-600 dark:text-slate-400'
                    )}>
                      {label}
                    </div>
                    <div className="text-[10px] text-slate-400 truncate font-mono">
                      {step.skill_name ?? `step ${index + 1}`}
                    </div>
                  </div>
                  {isSelected && <ChevronRight className="w-3 h-3 text-indigo-400 shrink-0" />}
                </button>
              );
            })}
            {steps.length === 0 && (
              <div className="text-xs text-slate-400 text-center py-8">无步骤记录</div>
            )}
          </div>
        </div>

        {/* 产物预览 */}
        <div className="flex-1 overflow-y-auto custom-scrollbar bg-slate-50 dark:bg-slate-950">
          <AnimatePresence mode="wait">
            {previewStep ? (
              <motion.div
                key={previewStep.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="p-4"
              >
                <StepPreview step={previewStep} />
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="h-full flex flex-col items-center justify-center text-slate-400 gap-2 p-8"
              >
                <Cpu className="w-8 h-8 opacity-20" />
                <span className="text-xs">点击左侧步骤查看产物</span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
