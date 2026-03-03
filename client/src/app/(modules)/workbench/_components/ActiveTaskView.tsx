import React, { useEffect, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  CheckCircle2, 
  Loader2, 
  AlertCircle, 
  FileText,
  Terminal,
  ArrowRight,
  Cpu,
  Clock,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { TaskState, TaskStep } from '@/stores/taskStore';
import { useWorkbenchStore } from '@/stores/workbenchStore';

interface ActiveTaskViewProps {
  task: TaskState;
}

export function ActiveTaskView({ task }: ActiveTaskViewProps) {
  const isCompleted = task.status === 'completed';

  const completedCount = useMemo(
    () => task.steps.filter(s => s.status === 'completed').length,
    [task.steps]
  );
  const failedCount = useMemo(
    () => task.steps.filter(s => s.status === 'failed').length,
    [task.steps]
  );
  const totalSteps = task.steps.length || 1; // 防止除 0
  const progressPercent = Math.round((completedCount / totalSteps) * 100);

  // 找当前 active step
  const activeStepIndex = useMemo(() => {
    if (task.status === 'completed' && task.steps.length > 0) {
      return task.steps.length - 1;
    }
    const runningIdx = task.steps.findIndex(s => s.status === 'running');
    if (runningIdx !== -1) return runningIdx;
    return task.steps.findIndex(s => s.status === 'pending');
  }, [task.steps, task.status]);

  // 自动滚动到当前步骤
  const activeRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (activeRef.current && activeStepIndex !== -1) {
      activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [activeStepIndex]);

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-slate-950 overflow-hidden relative">
      {/* 背景装饰 */}
      <div className="absolute top-0 right-0 w-96 h-96 bg-indigo-500/5 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-64 h-64 bg-purple-500/5 rounded-full blur-3xl pointer-events-none" />

      {/* 1. 任务头部 */}
      <div className="shrink-0 p-6 z-10 bg-white/50 dark:bg-slate-950/50 backdrop-blur-sm border-b border-slate-200/50 dark:border-slate-800/50">
        <div className="flex items-center gap-2 mb-3">
          <span className="flex items-center justify-center w-6 h-6 rounded-md bg-indigo-100 dark:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400">
            <Terminal className="w-3.5 h-3.5" />
          </span>
          <span className="text-xs font-bold text-indigo-500 uppercase tracking-wider">
            Current Mission
          </span>
        </div>

        <h2 className="text-lg md:text-xl font-medium text-slate-800 dark:text-slate-100 leading-relaxed font-sans">
          {/* 支持 "A -> B -> C" 的高亮展示 */}
          {task.goal && (task.goal.includes('->') || task.goal.includes('→')) ? (
            <div className="flex flex-wrap items-center gap-2">
              {task.goal.split(/->|→/).map((part, i, arr) => (
                <React.Fragment key={i}>
                  <span
                    className={cn(
                      'px-2 py-0.5 rounded-md',
                      i === arr.length - 1
                        ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 font-semibold'
                        : 'text-slate-600 dark:text-slate-400'
                    )}
                  >
                    {part.trim()}
                  </span>
                  {i < arr.length - 1 && (
                    <ArrowRight className="w-4 h-4 text-slate-300" />
                  )}
                </React.Fragment>
              ))}
            </div>
          ) : (
            task.goal || 'Untitled Task'
          )}
        </h2>

        {/* 全局摘要条：状态 + 总体进度 */}
        <div className="mt-4 flex flex-col gap-2">
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <div className="inline-flex items-center gap-2">
              <span className="inline-flex h-1.5 w-1.5 rounded-full bg-indigo-500" />
              <span className="font-medium">
                Status: <span className="uppercase tracking-wider">{task.status}</span>
              </span>
            </div>
            <div className="flex items-center gap-3 font-mono">
              <span>{completedCount}/{totalSteps} steps done</span>
              {failedCount > 0 && (
                <span className="text-red-500">
                  {failedCount} failed
                </span>
              )}
            </div>
          </div>
          <div className="w-full h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
            <div
              className="h-full bg-indigo-500 dark:bg-indigo-400 transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      </div>

      {/* 2. 主体区域 */}
      <div className="flex-1 overflow-auto custom-scrollbar p-6 z-10">
        <AnimatePresence mode="wait">
          {isCompleted ? (
            <TaskCompletionView key="completion" />
          ) : (
            <div key="list" className="max-w-3xl mx-auto space-y-8 pb-12">
              {/* 时间线 */}
              <div className="relative">
                <div className="absolute left-6 top-4 bottom-4 w-0.5 bg-slate-200 dark:bg-slate-800" />

                {task.steps.map((step, index) => {
                  const isActive = step.status === 'running';
                  const isPast = step.status === 'completed';
                  const isFailed = step.status === 'failed';

                  return (
                    <div
                      key={step.id}
                      ref={isActive ? activeRef : null}
                      className="relative mb-8 last:mb-0"
                    >
                      <StepCard
                        step={step}
                        index={index}
                        isActive={isActive}
                        isPast={isPast}
                        isFailed={isFailed}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </AnimatePresence>
      </div>

      {/* 3. 底部状态条 */}
      {!isCompleted && (
        <div className="shrink-0 bg-white dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 p-3 px-6 flex items-center justify-between text-xs z-20 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)]">
          <div className="flex items-center gap-3">
            {task.status === 'running' || task.status === 'executing' ? (
              <div className="flex items-center gap-2">
                <div className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-indigo-500" />
                </div>
                <span className="font-medium text-slate-600 dark:text-slate-300">
                  AI Agent is active...
                </span>
              </div>
            ) : (
              <span className="text-slate-500">Status: {task.status}</span>
            )}
          </div>

          <div className="flex items-center gap-4 text-slate-400 font-mono">
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>
                {completedCount}/{totalSteps} steps
              </span>
            </div>
            {failedCount > 0 && (
              <div className="flex items-center gap-1.5 text-red-500">
                <AlertCircle className="w-3.5 h-3.5" />
                <span>{failedCount} failed</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------
// 子组件
// ----------------------------------------------------------------------

function StepCard({
  step,
  index,
  isActive,
  isPast,
  isFailed,
}: {
  step: TaskStep;
  index: number;
  isActive: boolean;
  isPast: boolean;
  isFailed: boolean;
}) {
  return (
    <div
      className={cn(
        'relative pl-16 transition-all duration-500',
        isActive
          ? 'opacity-100 scale-100'
          : isPast
          ? 'opacity-80'
          : 'opacity-60'
      )}
    >
      {/* 时间线节点 */}
      <div
        className={cn(
          'absolute left-3 top-0 -translate-x-1/2 w-6 h-6 rounded-full border-2 flex items-center justify-center bg-white dark:bg-slate-950 z-10 transition-colors duration-300',
          isPast
            ? 'border-green-500 text-green-500'
            : isFailed
            ? 'border-red-500 text-red-500'
            : isActive
            ? 'border-indigo-500 text-indigo-500 shadow-[0_0_0_4px_rgba(99,102,241,0.2)]'
            : 'border-slate-300 dark:border-slate-700 text-slate-300'
        )}
      >
        {isPast ? (
          <CheckCircle2 className="w-3.5 h-3.5" />
        ) : isFailed ? (
          <AlertCircle className="w-3.5 h-3.5" />
        ) : isActive ? (
          <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
        ) : (
          <span className="text-[10px] font-mono">{index + 1}</span>
        )}
      </div>

      {/* Step 卡片 */}
      <div
        className={cn(
          'rounded-xl border transition-all duration-300 overflow-hidden',
          isActive
            ? 'bg-white dark:bg-slate-900 border-indigo-200 dark:border-indigo-500/30 shadow-xl shadow-indigo-500/10'
            : isFailed
            ? 'bg-red-50/40 dark:bg-red-900/10 border-red-100 dark:border-red-500/30'
            : 'bg-transparent border-transparent'
        )}
      >
        {/* 头部行 */}
        <div
          className={cn(
            'flex items-center gap-3 p-3',
            isActive && 'border-b border-slate-100 dark:border-slate-800'
          )}
        >
          <h3
            className={cn(
              'font-medium text-sm',
              isActive
                ? 'text-slate-900 dark:text-slate-100 text-base'
                : 'text-slate-600 dark:text-slate-400'
            )}
          >
            {step.step_name}
          </h3>

          {/* 状态 Badge */}
          <div className="ml-auto">
            {isActive && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-50 dark:bg-indigo-500/20 text-indigo-600 dark:text-indigo-300 text-[10px] font-bold uppercase tracking-wider">
                <Loader2 className="w-3 h-3 animate-spin" />
                In Progress
              </span>
            )}
            {isPast && !isFailed && (
              <span className="text-green-500 text-[10px] font-bold uppercase tracking-wider flex items-center gap-1">
                Done <CheckCircle2 className="w-3 h-3" />
              </span>
            )}
            {isFailed && (
              <span className="text-red-500 text-[10px] font-bold uppercase tracking-wider flex items-center gap-1">
                Failed <AlertCircle className="w-3 h-3" />
              </span>
            )}
            {!isActive && !isPast && !isFailed && (
              <span className="text-slate-400 text-[10px] font-bold uppercase tracking-wider flex items-center gap-1">
                Pending <Clock className="w-3 h-3" />
              </span>
            )}
          </div>
        </div>

        {/* 详情：只在 Active 或 Failed 时展开 */}
        <AnimatePresence>
          {(isActive || isFailed) && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="bg-slate-50/50 dark:bg-slate-950/30"
            >
              <div className="p-4 space-y-4">
                {/* Skill 信息 */}
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 w-6 h-6 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 flex items-center justify-center shrink-0 shadow-sm">
                    <Cpu className="w-3.5 h-3.5 text-slate-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-slate-500 mb-0.5 uppercase tracking-wider font-semibold">
                      Running Skill
                    </div>
                    <div className="text-sm font-mono text-slate-700 dark:text-slate-200 break-all">
                      {step.skill_name}
                    </div>
                  </div>
                </div>

                {/* 参数展示 */}
                {step.params && Object.keys(step.params).length > 0 && (
                  <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 p-3 font-mono text-xs">
                    {Object.entries(step.params).map(([key, value]) => (
                      <div key={key} className="flex gap-2 mb-1 last:mb-0">
                        <span className="text-indigo-500 shrink-0 select-none">
                          {key}:
                        </span>
                        <span className="text-slate-600 dark:text-slate-400 break-all">
                          {typeof value === 'object'
                            ? JSON.stringify(value)
                            : String(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* 错误信息 */}
                {isFailed && (
                  <div className="flex gap-3 bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-500/20 rounded-lg p-3 text-red-600 dark:text-red-400 text-xs">
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    <div className="flex-1">
                      <div className="font-semibold mb-1">
                        Execution Failed
                      </div>
                      <div>
                        {typeof step.output_result === 'string'
                          ? step.output_result
                          : 'Unknown error occurred. Check logs for details.'}
                      </div>

                      {/* 这里先做静态 Retry 提示，未来可以和真实重试逻辑挂钩 */}
                      <div className="mt-2 flex items-center gap-2 opacity-70">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        <span>Retrying (1/3)...</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function TaskCompletionView() {
  const { setActiveTab } = useWorkbenchStore();

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex flex-col items-center justify-center h-full min-h-[400px] text-center p-6"
    >
      <div className="relative mb-8">
        <div className="absolute inset-0 bg-green-500 blur-2xl opacity-20 rounded-full animate-pulse" />
        <div className="relative w-24 h-24 rounded-full bg-gradient-to-tr from-green-400 to-emerald-600 flex items-center justify-center shadow-2xl">
          <CheckCircle2 className="w-12 h-12 text-white" />
        </div>
        <div
          className="absolute -top-2 -right-2 w-4 h-4 bg-yellow-400 rounded-full animate-bounce"
          style={{ animationDelay: '0.1s' }}
        />
        <div
          className="absolute top-0 -left-4 w-3 h-3 bg-blue-400 rounded-full animate-bounce"
          style={{ animationDelay: '0.2s' }}
        />
        <div
          className="absolute -bottom-2 right-0 w-3 h-3 bg-purple-400 rounded-full animate-bounce"
          style={{ animationDelay: '0.3s' }}
        />
      </div>

      <h3 className="text-3xl font-bold text-slate-800 dark:text-slate-100 mb-3 tracking-tight">
        Task Completed!
      </h3>
      <p className="text-slate-500 dark:text-slate-400 max-w-sm mx-auto mb-8 text-lg">
        This mission has finished. You can inspect all generated files and outputs in the Preview panel.
      </p>

      <div className="flex items-center gap-4">
        <button
          onClick={() => setActiveTab('preview')}
          className="flex items-center gap-2 px-6 py-3 bg-slate-900 dark:bg-white text-white dark:text-slate-900 rounded-xl font-semibold shadow-lg hover:transform hover:scale-105 transition-all"
        >
          <FileText className="w-4 h-4" />
          Preview Result
        </button>
      </div>
    </motion.div>
  );
}
