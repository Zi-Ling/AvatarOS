import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2,
  Loader2,
  AlertCircle,
  Clock,
  Cpu,
  ChevronRight,
  Terminal,
  Pause,
  Play,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { TaskState, TaskStep } from '@/stores/taskStore';
import { useTaskStore } from '@/stores/taskStore';
import { useWorkbenchStore } from '@/stores/workbenchStore';
import { StepPreview, getSkillMeta } from './StepPreview';
import { cancelTask, pauseTask, resumeTask } from '@/lib/api/task';
import { deriveTaskControls } from '@/types/task';
import { approvalApi } from '@/lib/api/history';
import { ShieldCheck, ShieldX, AlertTriangle } from 'lucide-react';

interface ActiveTaskViewProps {
  task: TaskState;
}

export function ActiveTaskView({ task }: ActiveTaskViewProps) {
  const { selectedStepId, setSelectedStepId } = useWorkbenchStore();
  const { controlStatus, setIsCancelling, pendingApprovals, removePendingApproval } = useTaskStore();
  const { canPause, canResume, canCancel } = deriveTaskControls(task.status, controlStatus);
  const [isActioning, setIsActioning] = useState(false);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const isCompleted = task.status === 'completed';
  const isExecuting = task.status === 'executing';

  // 匹配当前 task 的 pending approvals
  const taskApprovals = pendingApprovals.filter(
    (a) => a.task_id === task.id || task.steps.some((s) => s.id === a.step_id)
  );

  const completedCount = useMemo(
    () => task.steps.filter(s => s.status === 'completed').length,
    [task.steps]
  );
  const totalSteps = task.steps.length || 1;
  const progressPercent = Math.round((completedCount / totalSteps) * 100);

  const runningStep = useMemo(
    () => task.steps.find(s => s.status === 'running'),
    [task.steps]
  );

  const previewStep = useMemo(() => {
    if (selectedStepId) return task.steps.find(s => s.id === selectedStepId) ?? null;
    if (runningStep) return runningStep;
    const completed = task.steps.filter(s => s.status === 'completed');
    return completed.length > 0 ? completed[completed.length - 1] : null;
  }, [selectedStepId, runningStep, task.steps]);

  const activeRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!selectedStepId && activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [runningStep?.id, selectedStepId]);

  useEffect(() => {
    if (isCompleted) setSelectedStepId(null);
  }, [isCompleted, setSelectedStepId]);

  const handlePauseResume = async () => {
    if (isActioning) return;
    setIsActioning(true);
    try {
      if (canResume) {
        await resumeTask(task.id);
      } else if (canPause) {
        await pauseTask(task.id);
      }
    } catch (e) {
      console.error('pause/resume failed', e);
    } finally {
      setIsActioning(false);
    }
  };

  const handleCancel = async () => {
    if (isActioning || !canCancel) return;
    setIsActioning(true);
    setIsCancelling(true);
    try {
      await cancelTask(task.id);
    } catch (e) {
      console.error('cancel failed', e);
      setIsCancelling(false);
    } finally {
      setIsActioning(false);
    }
  };

  const handleApprove = async (requestId: string, approved: boolean) => {
    setApprovingId(requestId);
    try {
      await approvalApi.respond(requestId, approved);
      removePendingApproval(requestId);
    } catch (e) {
      console.error('approval respond failed', e);
    } finally {
      setApprovingId(null);
    }
  };

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-slate-950 overflow-hidden">
      {/* 任务头部 */}
      <div className="shrink-0 px-5 py-4 bg-white dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2 mb-1.5">
          <Terminal className="w-3.5 h-3.5 text-indigo-500" />
          <span className="text-[10px] font-bold text-indigo-500 uppercase tracking-wider">Current Mission</span>
        </div>
        <p className="text-sm font-medium text-slate-800 dark:text-slate-100 leading-snug line-clamp-2">
          {task.goal || 'Untitled Task'}
        </p>
        <div className="mt-3 flex items-center gap-3">
          <div className="flex-1 h-1 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
            <div
              className={cn(
                'h-full transition-all duration-500',
                controlStatus === 'paused' ? 'bg-amber-400' : 'bg-indigo-500'
              )}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <span className="text-[10px] font-mono text-slate-400 shrink-0">{completedCount}/{task.steps.length}</span>
        </div>
      </div>

      {/* 主体：左右分栏 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：步骤时间线 */}
        <div className="w-[200px] shrink-0 border-r border-slate-200 dark:border-slate-800 overflow-y-auto custom-scrollbar bg-white dark:bg-slate-950 py-3">
          <div className="relative px-3 space-y-1">
            {task.steps.map((step, index) => {
              const { label } = getSkillMeta(step.skill_name);
              const isRunning = step.status === 'running';
              const isDone = step.status === 'completed';
              const isFailed = step.status === 'failed';
              const isSelected = previewStep?.id === step.id;

              return (
                <button
                  key={step.id}
                  ref={isRunning ? activeRef : null}
                  onClick={() => setSelectedStepId(isSelected && !selectedStepId ? null : step.id)}
                  className={cn(
                    'w-full flex items-center gap-2 px-2 py-2 rounded-lg text-left transition-all duration-150',
                    isSelected ? 'bg-indigo-50 dark:bg-indigo-500/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800/50',
                  )}
                >
                  <div className={cn(
                    'shrink-0 w-5 h-5 rounded-full flex items-center justify-center',
                    isDone ? 'text-green-500' : isFailed ? 'text-red-500' : isRunning ? 'text-indigo-500' : 'text-slate-300 dark:text-slate-600'
                  )}>
                    {isDone ? <CheckCircle2 className="w-4 h-4" /> :
                     isFailed ? <AlertCircle className="w-4 h-4" /> :
                     isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> :
                     <Clock className="w-4 h-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className={cn(
                      'text-xs font-medium truncate',
                      isSelected ? 'text-indigo-600 dark:text-indigo-400' :
                      isDone ? 'text-slate-600 dark:text-slate-400' :
                      isRunning ? 'text-slate-900 dark:text-slate-100' :
                      'text-slate-400 dark:text-slate-600'
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
            {task.steps.length === 0 && (
              <div className="text-xs text-slate-400 text-center py-8">等待计划生成...</div>
            )}
          </div>
        </div>

        {/* 右侧：产物预览 */}
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

      {/* 内联审批 banner */}
      {taskApprovals.length > 0 && (
        <div className="shrink-0 border-t border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10">
          {taskApprovals.map((req) => (
            <div key={req.request_id} className="px-4 py-3">
              <div className="flex items-start gap-2 mb-2">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-slate-800 dark:text-slate-100 leading-snug">
                    {req.message}
                  </div>
                  <div className="text-[10px] font-mono text-slate-400 mt-0.5 truncate">{req.operation}</div>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleApprove(req.request_id, true)}
                  disabled={approvingId === req.request_id}
                  className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-md bg-green-500 hover:bg-green-600 text-white text-xs font-medium transition-colors disabled:opacity-50"
                >
                  {approvingId === req.request_id
                    ? <Loader2 className="w-3 h-3 animate-spin" />
                    : <ShieldCheck className="w-3 h-3" />}
                  批准
                </button>
                <button
                  onClick={() => handleApprove(req.request_id, false)}
                  disabled={approvingId === req.request_id}
                  className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-md bg-red-500 hover:bg-red-600 text-white text-xs font-medium transition-colors disabled:opacity-50"
                >
                  <ShieldX className="w-3 h-3" />
                  拒绝
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 底部状态条 + 控制按钮 */}
      {!isCompleted && isExecuting && (
        <div className="shrink-0 bg-white dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 px-4 py-2 flex items-center gap-2 text-xs">
          {controlStatus === 'paused' ? (
            <div className="relative flex h-2 w-2">
              <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
            </div>
          ) : (
            <div className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500" />
            </div>
          )}
          <span className="text-slate-500 dark:text-slate-400 flex-1">
            {controlStatus === 'paused' ? '已暂停' : 'AI Agent 执行中...'}
          </span>

          {/* 暂停/恢复按钮 */}
          <button
            onClick={handlePauseResume}
            disabled={isActioning || (!canPause && !canResume)}
            className={cn(
              'flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors',
              canResume
                ? 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-400 dark:hover:bg-indigo-500/20'
                : 'bg-amber-50 text-amber-600 hover:bg-amber-100 dark:bg-amber-500/10 dark:text-amber-400 dark:hover:bg-amber-500/20',
              (isActioning || (!canPause && !canResume)) && 'opacity-50 cursor-not-allowed'
            )}
          >
            {canResume ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
            {canResume ? '恢复' : '暂停'}
          </button>

          {/* 取消按钮 */}
          <button
            onClick={handleCancel}
            disabled={isActioning || !canCancel}
            className={cn(
              'flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors',
              'bg-red-50 text-red-500 hover:bg-red-100 dark:bg-red-500/10 dark:text-red-400 dark:hover:bg-red-500/20',
              (isActioning || !canCancel) && 'opacity-50 cursor-not-allowed'
            )}
          >
            <X className="w-3 h-3" />
            取消
          </button>
        </div>
      )}
    </div>
  );
}
