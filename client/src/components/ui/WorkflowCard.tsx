"use client";

/**
 * Workflow Card Component
 * 
 * 在 Workbench 的 Active Tasks 中显示工作流执行状态
 */

import React from 'react';

interface StepRun {
  step_id: string;
  step_name: string;
  status: string;
  duration?: number;
  error?: string;
}

interface WorkflowRun {
  id: string;
  template_id: string;
  workflow_name: string;
  status: string;
  start_time?: number;
  end_time?: number;
  duration?: number;
  error?: string;
  step_runs?: StepRun[];
}

interface WorkflowCardProps {
  workflow: WorkflowRun;
  onCancel?: (id: string) => void;
  onViewDetail?: (id: string) => void;
}

export function WorkflowCard({ workflow, onCancel, onViewDetail }: WorkflowCardProps) {
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'bg-blue-500';
      case 'completed': case 'success': return 'bg-green-500';
      case 'failed': return 'bg-red-500';
      case 'created': case 'pending': return 'bg-gray-400';
      case 'cancelled': case 'paused': return 'bg-gray-500';
      default: return 'bg-gray-300';
    }
  };

  const getStatusText = (status: string) => {
    const statusMap: Record<string, string> = {
      created: '已创建',
      pending: '等待中',
      running: '执行中',
      completed: '成功',
      success: '成功',
      failed: '失败',
      cancelled: '已取消',
      paused: '已暂停',
      skipped: '已跳过',
    };
    return statusMap[status] || status;
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds.toFixed(1)}秒`;
    if (seconds < 3600) return `${(seconds / 60).toFixed(1)}分钟`;
    return `${(seconds / 3600).toFixed(1)}小时`;
  };

  const steps = workflow.step_runs || [];
  const completedSteps = steps.filter(s => s.status === 'completed' || s.status === 'success').length;
  const totalSteps = steps.length;
  const progress = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4 hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-medium text-gray-900 dark:text-gray-100">
              {workflow.workflow_name}
            </h3>
            <span className={`px-2 py-0.5 text-xs font-medium text-white rounded ${getStatusColor(workflow.status)}`}>
              {getStatusText(workflow.status)}
            </span>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            ID: {workflow.id.slice(0, 8)}...
          </p>
        </div>

        <div className="flex gap-2">
          {(workflow.status === 'running' || workflow.status === 'created') && onCancel && (
            <button
              onClick={() => onCancel(workflow.id)}
              className="text-sm text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
              title="取消执行"
            >
              取消
            </button>
          )}
          {onViewDetail && (
            <button
              onClick={() => onViewDetail(workflow.id)}
              className="text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
              title="查看详情"
            >
              详情
            </button>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      {workflow.status === 'running' && totalSteps > 0 && (
        <div className="mb-3">
          <div className="flex justify-between text-xs text-gray-600 dark:text-gray-400 mb-1">
            <span>进度: {completedSteps}/{totalSteps} 步骤</span>
            <span>{progress.toFixed(0)}%</span>
          </div>
          <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Steps List */}
      {steps.length > 0 && (
        <div className="space-y-2 mb-3">
          {steps.slice(0, 3).map((step) => (
            <div key={step.step_id} className="flex items-center gap-2 text-sm">
              <div className={`w-2 h-2 rounded-full ${getStatusColor(step.status)}`} />
              <span className="flex-1 text-gray-700 dark:text-gray-300">
                {step.step_name}
              </span>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {step.duration ? formatDuration(step.duration) : '-'}
              </span>
            </div>
          ))}
          {steps.length > 3 && (
            <div className="text-xs text-gray-500 dark:text-gray-400 pl-4">
              还有 {steps.length - 3} 个步骤...
            </div>
          )}
        </div>
      )}

      {/* Error Message */}
      {workflow.error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-2 mb-3">
          <p className="text-xs text-red-700 dark:text-red-400">
            错误: {workflow.error}
          </p>
        </div>
      )}

      {/* Footer */}
      <div className="flex justify-between items-center text-xs text-gray-500 dark:text-gray-400 pt-3 border-t border-gray-200 dark:border-gray-700">
        <span>
          {workflow.start_time
            ? `开始于 ${new Date(workflow.start_time * 1000).toLocaleTimeString()}`
            : '未开始'}
        </span>
        {workflow.duration && (
          <span>耗时 {formatDuration(workflow.duration)}</span>
        )}
      </div>
    </div>
  );
}

export default WorkflowCard;
