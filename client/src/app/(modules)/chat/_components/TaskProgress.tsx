import React, { useState } from 'react';
import { CheckCircle2, Circle, XCircle, Loader2, MinusCircle, List, Network } from 'lucide-react';
import { cn } from '@/lib/utils';
import { CodeTerminal } from '@/components/ui/CodeTerminal';
import { ResultRenderer } from '@/components/ui/ResultRenderer';
import { TaskStep } from '@/stores/chatStore';
import { TaskDAG } from './TaskDAG';

interface TaskProgressProps {
  steps: TaskStep[];
  taskStatus?: 'planning' | 'executing' | 'completed' | 'failed';
}

export function TaskProgress({ steps, taskStatus }: TaskProgressProps) {
  const [viewMode, setViewMode] = useState<'list' | 'dag'>('list');
  const completedCount = steps.filter(s => s.status === 'completed').length;
  const failedCount = steps.filter(s => s.status === 'failed').length;
  const progressPercent = steps.length > 0 ? Math.round((completedCount / steps.length) * 100) : 0;

  // 获取状态图标
  const getStatusIcon = (status: TaskStep['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="w-4 h-4 text-green-500" />;
      case 'running':
        return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-500" />;
      case 'skipped':
        return <MinusCircle className="w-4 h-4 text-gray-400" />;
      default:
        return <Circle className="w-4 h-4 text-gray-300" />;
    }
  };

  // 获取状态文本颜色
  const getStatusColor = (status: TaskStep['status']) => {
    switch (status) {
      case 'completed':
        return 'text-green-600 dark:text-green-400';
      case 'running':
        return 'text-blue-600 dark:text-blue-400';
      case 'failed':
        return 'text-red-600 dark:text-red-400';
      case 'skipped':
        return 'text-gray-500 dark:text-gray-400';
      default:
        return 'text-gray-400 dark:text-gray-500';
    }
  };

  // 如果是 DAG 视图，直接返回 DAG 组件
  if (viewMode === 'dag') {
    return (
      <div>
        {/* 视图切换按钮 */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
            任务执行流程
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setViewMode('list')}
              className={cn(
                "p-1.5 rounded text-xs transition-colors",
                "hover:bg-slate-200 dark:hover:bg-slate-700",
                "text-slate-500 dark:text-slate-400"
              )}
              title="列表视图"
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('dag')}
              className={cn(
                "p-1.5 rounded text-xs transition-colors",
                "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
              )}
              title="DAG 图"
            >
              <Network className="w-4 h-4" />
            </button>
          </div>
        </div>
        <TaskDAG steps={steps} taskStatus={taskStatus} />
      </div>
    );
  }

  return (
    <div className="my-3 p-3 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200 dark:border-slate-800">
      {/* 进度条 + 视图切换 */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-xs mb-1.5">
          <span className="font-medium text-slate-700 dark:text-slate-300">
            执行进度
          </span>
          <div className="flex items-center gap-3">
            <span className="text-slate-500 dark:text-slate-400">
              {completedCount}/{steps.length} 步骤
              {failedCount > 0 && <span className="text-red-500 ml-1">({failedCount} 失败)</span>}
            </span>
            {/* 视图切换按钮 */}
            <div className="flex gap-1">
              <button
                onClick={() => setViewMode('list')}
                className={cn(
                  "p-1 rounded text-xs transition-colors",
                  "bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
                )}
                title="列表视图"
              >
                <List className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setViewMode('dag')}
                className={cn(
                  "p-1 rounded text-xs transition-colors",
                  "hover:bg-slate-200 dark:hover:bg-slate-700",
                  "text-slate-500 dark:text-slate-400"
                )}
                title="DAG 图"
              >
                <Network className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
        <div className="h-1.5 bg-slate-200 dark:bg-slate-800 rounded-full overflow-hidden">
          <div
            className={cn(
              "h-full transition-all duration-300 rounded-full",
              failedCount > 0 ? "bg-red-500" : "bg-blue-500"
            )}
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {/* 步骤列表 */}
      <div className="space-y-1.5">
        {steps.map((step, index) => (
          <div key={step.id} className="flex flex-col">
            <div
              className={cn(
                "flex items-center gap-2 px-2 py-1.5 rounded text-sm transition-colors",
                step.status === 'running' && "bg-blue-50 dark:bg-blue-900/20",
                step.status === 'completed' && "bg-green-50 dark:bg-green-900/20",
                step.status === 'failed' && "bg-red-50 dark:bg-red-900/20"
              )}
            >
              {/* 状态图标 */}
              {getStatusIcon(step.status)}

              {/* 步骤信息 */}
              <div className="flex-1 min-w-0">
                <span className={cn("font-medium", getStatusColor(step.status))}>
                  {index + 1}. {step.step_name}
                </span>
                <span className="text-xs text-slate-400 dark:text-slate-500 ml-1.5">
                  ({step.skill_name})
                </span>
              </div>

              {/* 状态标签 */}
              {step.status === 'running' && (
                <span className="text-xs px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded">
                  执行中
                </span>
              )}
            </div>

            {/* Code Terminal Insertion */}
            {(step.skill_name === 'python.run' || step.skill_name === 'system.schedule.create') && step.params?.code && (
                 <div className="mt-2 pl-6 pr-2">
                     {(() => {
                         // Pre-calculate result for CodeTerminal output prop
                         let outputText = undefined;
                         try {
                             if (step.output_result) {
                                 const result = typeof step.output_result === 'string' 
                                    ? JSON.parse(step.output_result) 
                                    : step.output_result;
                                 
                                 // Prefer stdout, fall back to result if string
                                 if (result) {
                                     if (result.stdout) outputText = result.stdout;
                                     else if (result.stderr) outputText = result.stderr; // Show error in terminal
                                     else if (typeof result.result === 'string') outputText = result.result;
                                 }
                             }
                         } catch (e) { /* ignore */ }

                         return (
                             <CodeTerminal 
                                code={step.params.code} 
                                output={outputText}
                                status={step.status} 
                                title={step.skill_name === 'python.run' ? 'Python Runtime' : 'Schedule Config'}
                             />
                         );
                     })()}
                     
                     {/* Result Renderer for Python Outputs (Image/Table) */}
                     {step.status === 'completed' && step.output_result && (() => {
                         try {
                             // Handle both JSON string (from DB) and already parsed object (if cached in store)
                             const result = typeof step.output_result === 'string' 
                                ? JSON.parse(step.output_result) 
                                : step.output_result;
                                
                             if (!result) return null;
                             
                             return (
                                 <div className="space-y-2 mt-2">
                                     {result.base64_image && (
                                         <ResultRenderer content={result.base64_image} type="image" />
                                     )}
                                     {result.dataframe_csv && (
                                         <ResultRenderer content={result.dataframe_csv} type="table" />
                                     )}
                                 </div>
                             );
                         } catch (e) {
                             // If parsing fails or not valid JSON, ignore
                             return null;
                         }
                     })()}
                 </div>
            )}
          </div>
        ))}
      </div>

      {/* 任务状态提示 */}
      {taskStatus === 'completed' && (
        <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400">
            <CheckCircle2 className="w-4 h-4" />
            <span className="font-medium">任务执行完成</span>
          </div>
        </div>
      )}

      {taskStatus === 'failed' && (
        <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
            <XCircle className="w-4 h-4" />
            <span className="font-medium">任务执行失败</span>
          </div>
        </div>
      )}
    </div>
  );
}
