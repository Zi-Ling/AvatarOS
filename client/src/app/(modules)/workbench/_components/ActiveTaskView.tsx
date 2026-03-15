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
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { TaskState, TaskStep } from '@/stores/taskStore';
import { useTaskStore } from '@/stores/taskStore';
import { useWorkbenchStore } from '@/stores/workbenchStore';
import { StepPreview, getSkillMeta } from './StepPreview';
import { deriveTaskControls } from '@/types/task';

interface ActiveTaskViewProps {
  task: TaskState;
}

export function ActiveTaskView({ task }: ActiveTaskViewProps) {
  const { selectedStepId, setSelectedStepId } = useWorkbenchStore();
  const { controlStatus } = useTaskStore();
  const { canPause, canResume, canCancel } = deriveTaskControls(task.status, controlStatus);
  const isCompleted = task.status === 'completed';
  const isExecuting = task.status === 'executing';

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
                    <div className="text-[10px] text-slate-400 truncate" title={step.description || step.skill_name}>
                      {step.description || step.skill_name || `step ${index + 1}`}
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

    </div>
  );
}
