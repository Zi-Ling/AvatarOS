"use client";

import { useState, useEffect } from 'react';
import { X, Clock, Calendar as CalendarIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { scheduleApi, ScheduleItem } from '@/lib/api/schedule';
import { useToast } from '@/lib/hooks/useToast';

interface EditScheduleDialogProps {
  schedule: ScheduleItem | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function EditScheduleDialog({ schedule, onClose, onSuccess }: EditScheduleDialogProps) {
  const toast = useToast();
  const [hour, setHour] = useState('9');
  const [minute, setMinute] = useState('0');
  const [frequency, setFrequency] = useState<'daily' | 'weekday' | 'weekly' | 'monthly'>('daily');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (schedule) {
      // 解析现有的 Cron 表达式
      parseCronExpression(schedule.cron_expression);
    }
  }, [schedule]);

  const parseCronExpression = (cron: string) => {
    const parts = cron.split(' ');
    if (parts.length >= 5) {
      setMinute(parts[0]);
      setHour(parts[1]);
      
      // 简单判断频率
      if (parts[4] === '1-5') {
        setFrequency('weekday');
      } else if (parts[2] === '1') {
        setFrequency('monthly');
      } else if (parts[4] === '1') {
        setFrequency('weekly');
      } else {
        setFrequency('daily');
      }
    }
  };

  const buildCronExpression = (): string => {
    const m = minute.padStart(2, '0');
    const h = hour.padStart(2, '0');
    
    switch (frequency) {
      case 'daily':
        return `${m} ${h} * * *`;
      case 'weekday':
        return `${m} ${h} * * 1-5`;
      case 'weekly':
        return `${m} ${h} * * 1`;
      case 'monthly':
        return `${m} ${h} 1 * *`;
      default:
        return `${m} ${h} * * *`;
    }
  };

  const handleSave = async () => {
    if (!schedule) return;
    
    setSaving(true);
    try {
      const newCron = buildCronExpression();
      await scheduleApi.updateSchedule(schedule.id, {
        name: schedule.name,
        cron: newCron,
        task_goal: schedule.intent_spec.goal,
      });
      
      toast.success('修改成功', '定时任务已更新');
      onSuccess();
      onClose();
    } catch (error) {
      toast.error('修改失败', error instanceof Error ? error.message : '未知错误');
    } finally {
      setSaving(false);
    }
  };

  if (!schedule) return null;

  const previewText = () => {
    const time = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`;
    const freqMap = {
      daily: '每天',
      weekday: '每个工作日',
      weekly: '每周一',
      monthly: '每月1号',
    };
    return `${freqMap[frequency]} ${time}`;
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl max-w-md w-full p-6 animate-in zoom-in-95 duration-300">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-slate-900 dark:text-white">
            编辑任务时间
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* 任务信息 */}
        <div className="mb-6 p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
          <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {schedule.name}
          </p>
        </div>

        {/* 时间选择 */}
        <div className="space-y-4 mb-6">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              <Clock className="w-4 h-4 inline mr-1" />
              执行时间
            </label>
            <div className="flex gap-2">
              <input
                type="number"
                min="0"
                max="23"
                value={hour}
                onChange={(e) => setHour(e.target.value)}
                className="flex-1 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="时"
              />
              <span className="text-2xl text-slate-400 flex items-center">:</span>
              <input
                type="number"
                min="0"
                max="59"
                value={minute}
                onChange={(e) => setMinute(e.target.value)}
                className="flex-1 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="分"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              <CalendarIcon className="w-4 h-4 inline mr-1" />
              执行频率
            </label>
            <div className="grid grid-cols-2 gap-2">
              {[
                { value: 'daily', label: '每天' },
                { value: 'weekday', label: '工作日' },
                { value: 'weekly', label: '每周一' },
                { value: 'monthly', label: '每月1号' },
              ].map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setFrequency(opt.value as any)}
                  className={cn(
                    "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                    frequency === opt.value
                      ? "bg-indigo-500 text-white shadow-md"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700"
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 预览 */}
        <div className="mb-6 p-4 bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-500/30 rounded-lg">
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-1">预览</p>
          <p className="text-base font-semibold text-indigo-600 dark:text-indigo-400">
            {previewText()}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 font-mono">
            Cron: {buildCronExpression()}
          </p>
        </div>

        {/* 提示 */}
        <div className="mb-6 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-500/30 rounded-lg">
          <p className="text-xs text-amber-700 dark:text-amber-400">
            💡 提示：只能修改时间和频率。如需修改任务内容，请删除后重新创建。
          </p>
        </div>

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
            {saving ? '保存中...' : '保存修改'}
          </button>
        </div>
      </div>
    </div>
  );
}

