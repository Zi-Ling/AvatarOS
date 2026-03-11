"use client";

import { useState } from "react";
import { X, Clock, Calendar as CalendarIcon, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { scheduleApi } from "@/lib/api/schedule";
import { useToast } from "@/lib/hooks/useToast";

interface CreateScheduleDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

type Frequency = "daily" | "weekday" | "weekly" | "monthly";

const FREQ_OPTIONS: { value: Frequency; label: string; cron: (h: string, m: string) => string }[] = [
  { value: "daily",   label: "每天",    cron: (h, m) => `${m} ${h} * * *`   },
  { value: "weekday", label: "工作日",  cron: (h, m) => `${m} ${h} * * 1-5` },
  { value: "weekly",  label: "每周一",  cron: (h, m) => `${m} ${h} * * 1`   },
  { value: "monthly", label: "每月1号", cron: (h, m) => `${m} ${h} 1 * *`   },
];

export function CreateScheduleDialog({ open, onClose, onSuccess }: CreateScheduleDialogProps) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [hour, setHour] = useState("9");
  const [minute, setMinute] = useState("0");
  const [frequency, setFrequency] = useState<Frequency>("daily");
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const buildCron = () => {
    const opt = FREQ_OPTIONS.find((f) => f.value === frequency)!;
    return opt.cron(hour.padStart(2, "0"), minute.padStart(2, "0"));
  };

  const previewText = () => {
    const time = `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
    const labels: Record<Frequency, string> = {
      daily: "每天",
      weekday: "每个工作日",
      weekly: "每周一",
      monthly: "每月1号",
    };
    return `${labels[frequency]} ${time}`;
  };

  const handleCreate = async () => {
    if (!name.trim() || !goal.trim()) {
      toast.error("请填写完整", "任务名称和目标不能为空");
      return;
    }
    setSaving(true);
    try {
      await scheduleApi.createSchedule({
        name: name.trim(),
        cron: buildCron(),
        task_goal: goal.trim(),
      });
      toast.success("创建成功", "定时任务已添加");
      onSuccess();
      onClose();
      // 重置表单
      setName("");
      setGoal("");
      setHour("9");
      setMinute("0");
      setFrequency("daily");
    } catch (e) {
      toast.error("创建失败", e instanceof Error ? e.message : "未知错误");
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    "w-full px-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none";

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl w-full max-w-md p-6 animate-in zoom-in-95 duration-300">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center">
              <Clock className="w-4 h-4 text-indigo-500" />
            </div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">创建定时任务</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        <div className="space-y-4">
          {/* 任务名称 */}
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              任务名称
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例：每日邮件提醒"
              className={inputCls}
            />
          </div>

          {/* 任务目标 */}
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              任务目标
            </label>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="例：检查并汇总今日邮件，生成摘要报告"
              rows={3}
              className={cn(inputCls, "resize-none")}
            />
          </div>

          {/* 执行时间 */}
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              <Clock className="w-3.5 h-3.5 inline mr-1" />
              执行时间
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                max={23}
                value={hour}
                onChange={(e) => setHour(e.target.value)}
                className="w-20 px-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm text-center focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none"
              />
              <span className="text-slate-400 font-bold">:</span>
              <input
                type="number"
                min={0}
                max={59}
                value={minute}
                onChange={(e) => setMinute(e.target.value)}
                className="w-20 px-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm text-center focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none"
              />
            </div>
          </div>

          {/* 执行频率 */}
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
              <CalendarIcon className="w-3.5 h-3.5 inline mr-1" />
              执行频率
            </label>
            <div className="grid grid-cols-4 gap-2">
              {FREQ_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setFrequency(opt.value)}
                  className={cn(
                    "py-2 rounded-lg text-xs font-medium transition-all",
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

          {/* 预览 */}
          <div className="p-3 bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-500/30 rounded-lg">
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-0.5">执行计划</p>
            <p className="text-sm font-semibold text-indigo-600 dark:text-indigo-400">{previewText()}</p>
            <p className="text-[10px] text-slate-400 font-mono mt-0.5">cron: {buildCron()}</p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg font-medium transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleCreate}
            disabled={saving || !name.trim() || !goal.trim()}
            className="flex-1 py-2.5 text-sm bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {saving ? "创建中..." : "创建任务"}
          </button>
        </div>
      </div>
    </div>
  );
}
