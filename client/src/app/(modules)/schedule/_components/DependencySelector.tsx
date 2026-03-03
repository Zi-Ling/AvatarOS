"use client";

import { useState, useEffect } from 'react';
import { X, Link2, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { scheduleApi, ScheduleItem } from '@/lib/api/schedule';
import { useToast } from '@/lib/hooks/useToast';

interface DependencySelectorProps {
  schedule: ScheduleItem | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function DependencySelector({ schedule, onClose, onSuccess }: DependencySelectorProps) {
  const toast = useToast();
  const [allSchedules, setAllSchedules] = useState<ScheduleItem[]>([]);
  const [selectedDeps, setSelectedDeps] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (schedule) {
      loadSchedules();
      setSelectedDeps(schedule.depends_on || []);
    }
  }, [schedule]);

  const loadSchedules = async () => {
    try {
      const schedules = await scheduleApi.listSchedules();
      // 排除自己
      setAllSchedules(schedules.filter(s => s.id !== schedule?.id));
    } catch (error) {
      console.error('Failed to load schedules:', error);
    }
  };

  const toggleDependency = (scheduleId: string) => {
    if (selectedDeps.includes(scheduleId)) {
      setSelectedDeps(selectedDeps.filter(id => id !== scheduleId));
    } else {
      setSelectedDeps([...selectedDeps, scheduleId]);
    }
  };

  const handleSave = async () => {
    if (!schedule) return;
    
    setSaving(true);
    try {
      await scheduleApi.updateDependencies(schedule.id, selectedDeps);
      toast.success('依赖设置成功', '任务依赖关系已更新');
      onSuccess();
      onClose();
    } catch (error) {
      toast.error('设置失败', error instanceof Error ? error.message : '未知错误');
    } finally {
      setSaving(false);
    }
  };

  if (!schedule) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl max-w-2xl w-full p-6 animate-in zoom-in-95 duration-300">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-bold text-slate-900 dark:text-white">
              设置任务依赖
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              选择必须先成功执行的任务
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* 当前任务 */}
        <div className="mb-6 p-4 bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-500/30 rounded-lg">
          <p className="text-sm font-medium text-indigo-700 dark:text-indigo-300">
            当前任务: {schedule.name}
          </p>
        </div>

        {/* 依赖列表 */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">
            依赖任务 ({selectedDeps.length} 个)
          </h3>
          {allSchedules.length === 0 ? (
            <div className="text-center py-8 text-slate-400">
              <p className="text-sm">暂无其他任务可选</p>
            </div>
          ) : (
            <div className="max-h-96 overflow-y-auto space-y-2">
              {allSchedules.map((s) => {
                const isSelected = selectedDeps.includes(s.id);
                return (
                  <button
                    key={s.id}
                    onClick={() => toggleDependency(s.id)}
                    className={cn(
                      "w-full p-3 rounded-lg border transition-all text-left",
                      isSelected
                        ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-300 dark:border-emerald-500/30"
                        : "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-indigo-300 dark:hover:border-indigo-500/30"
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div className={cn(
                        "w-5 h-5 rounded border-2 flex items-center justify-center shrink-0",
                        isSelected
                          ? "bg-emerald-500 border-emerald-500"
                          : "border-slate-300 dark:border-slate-600"
                      )}>
                        {isSelected && <CheckCircle2 className="w-4 h-4 text-white" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
                          {s.name}
                        </p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {s.cron_expression}
                        </p>
                      </div>
                      {isSelected && (
                        <Link2 className="w-4 h-4 text-emerald-500 shrink-0" />
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* 提示 */}
        {selectedDeps.length > 0 && (
          <div className="mb-6 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-500/30 rounded-lg">
            <p className="text-xs text-amber-700 dark:text-amber-400">
              💡 只有当所有依赖任务最近一次执行成功时，此任务才会执行
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg font-medium transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? '保存中...' : '保存依赖'}
          </button>
        </div>
      </div>
    </div>
  );
}

