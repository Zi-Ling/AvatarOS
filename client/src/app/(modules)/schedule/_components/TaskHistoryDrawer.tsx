"use client";

import { useState, useEffect } from 'react';
import { Drawer } from '@/components/ui/Drawer';
import { historyApi, TaskHistoryItem } from '@/lib/api/history';
import { CheckCircle2, XCircle, Clock, Calendar, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface TaskHistoryDrawerProps {
  taskId: string | null;
  onClose: () => void;
}

export function TaskHistoryDrawer({ taskId, onClose }: TaskHistoryDrawerProps) {
  const [task, setTask] = useState<TaskHistoryItem | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (taskId) {
      loadTaskHistory(taskId);
    }
  }, [taskId]);

  const loadTaskHistory = async (id: string) => {
    setLoading(true);
    try {
      const data = await historyApi.getTask(id);
      setTask(data);
    } catch (error) {
      console.error('Failed to load task history:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Drawer
      isOpen={taskId !== null}
      onClose={onClose}
      title="任务执行历史"
      size="lg"
    >
      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
        </div>
      ) : task ? (
        <div className="p-6 space-y-6">
          {/* 任务基本信息 */}
          <div className="bg-slate-50 dark:bg-slate-800/50 rounded-xl p-4">
            <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-2">
              {task.title || task.intent_spec.goal}
            </h3>
            <div className="flex items-center gap-4 text-sm text-slate-600 dark:text-slate-400">
              <div className="flex items-center gap-1">
                <Calendar className="w-4 h-4" />
                <span>创建于 {new Date(task.created_at).toLocaleDateString('zh-CN')}</span>
              </div>
              <div className="flex items-center gap-1">
                <Clock className="w-4 h-4" />
                <span>执行 {task.runs?.length || 0} 次</span>
              </div>
            </div>
          </div>

          {/* 执行记录列表 */}
          <div>
            <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">
              执行记录
            </h4>
            {task.runs && task.runs.length > 0 ? (
              <div className="space-y-3">
                {task.runs.map((run, index) => (
                  <div
                    key={run.id}
                    className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 hover:shadow-md transition-shadow"
                  >
                    {/* Run Header */}
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        {run.status === 'completed' ? (
                          <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                        ) : run.status === 'failed' ? (
                          <XCircle className="w-5 h-5 text-red-500" />
                        ) : (
                          <Loader2 className="w-5 h-5 text-indigo-500 animate-spin" />
                        )}
                        <span className={cn(
                          "text-sm font-medium",
                          run.status === 'completed' ? "text-emerald-600 dark:text-emerald-400" :
                          run.status === 'failed' ? "text-red-600 dark:text-red-400" :
                          "text-indigo-600 dark:text-indigo-400"
                        )}>
                          {run.status === 'completed' ? '成功' : run.status === 'failed' ? '失败' : '运行中'}
                        </span>
                      </div>
                      <span className="text-xs text-slate-500">
                        #{task.runs!.length - index}
                      </span>
                    </div>

                    {/* Run Details */}
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-slate-500 dark:text-slate-400">开始时间</span>
                        <span className="text-slate-700 dark:text-slate-300 font-mono">
                          {run.started_at ? new Date(run.started_at).toLocaleString('zh-CN', {
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                          }) : '-'}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500 dark:text-slate-400">结束时间</span>
                        <span className="text-slate-700 dark:text-slate-300 font-mono">
                          {run.finished_at ? new Date(run.finished_at).toLocaleString('zh-CN', {
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                          }) : '-'}
                        </span>
                      </div>
                      {run.started_at && run.finished_at && (
                        <div className="flex justify-between">
                          <span className="text-slate-500 dark:text-slate-400">耗时</span>
                          <span className="text-slate-700 dark:text-slate-300 font-mono">
                            {((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000).toFixed(2)}s
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Run Summary */}
                    {run.summary && (
                      <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">
                        <p className="text-xs text-slate-600 dark:text-slate-400">
                          {run.summary}
                        </p>
                      </div>
                    )}

                    {/* Error Message */}
                    {run.error_message && (
                      <div className="mt-3 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-500/30 rounded text-xs text-red-600 dark:text-red-400">
                        {run.error_message}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-slate-400">
                <Clock className="w-12 h-12 mx-auto mb-2 opacity-20" />
                <p className="text-sm">暂无执行记录</p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-center h-64 text-slate-400">
          <p>任务不存在</p>
        </div>
      )}
    </Drawer>
  );
}

