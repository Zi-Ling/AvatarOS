"use client";

import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { TrendingUp, CheckCircle2, XCircle, Calendar, Activity, BarChart3 } from 'lucide-react';
import { scheduleApi, ScheduleStats } from '@/lib/api/schedule';
import { cn } from '@/lib/utils';

interface StatsPanelProps {
  compact?: boolean; // 紧凑模式用于侧边栏
}

export function StatsPanel({ compact = false }: StatsPanelProps) {
  const [stats, setStats] = useState<ScheduleStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      const data = await scheduleApi.getStats();
      setStats(data);
    } catch (error) {
      console.error('Failed to load stats:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className={cn("flex items-center justify-center", compact ? "h-20" : "h-64")}>
        <div className="w-6 h-6 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!stats) {
    return (
      <div className={cn("flex flex-col items-center justify-center text-slate-400", compact ? "h-20" : "h-64")}>
        <BarChart3 className={cn("mb-2 opacity-20", compact ? "w-6 h-6" : "w-8 h-8")} />
        <p className={cn(compact ? "text-xs" : "text-sm")}>暂无统计数据</p>
      </div>
    );
  }

  // 紧凑模式：只显示关键指标和迷你图表
  if (compact) {
    return (
      <div className="space-y-3">
        {/* 成功率大卡片 */}
        <div className="bg-gradient-to-br from-emerald-50 to-green-50 dark:from-emerald-900/20 dark:to-green-900/20 border border-emerald-200 dark:border-emerald-500/30 rounded-xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">成功率</span>
            <TrendingUp className="w-4 h-4 text-emerald-500" />
          </div>
          <p className="text-3xl font-bold text-emerald-600 dark:text-emerald-400">
            {stats.success_rate}%
          </p>
          <p className="text-xs text-emerald-600/60 dark:text-emerald-400/60 mt-1">
            {stats.success_runs}/{stats.total_runs} 次成功
          </p>
        </div>

        {/* 迷你图表 */}
        <div className="bg-white dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-700 p-3">
          <h4 className="text-xs font-semibold text-slate-600 dark:text-slate-400 mb-2">
            7天趋势
          </h4>
          <ResponsiveContainer width="100%" height={80}>
            <BarChart data={stats.trend}>
              <Bar dataKey="success" fill="#10b981" radius={[2, 2, 0, 0]} />
              <Bar dataKey="failed" fill="#ef4444" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* 紧凑指标 */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-slate-50 dark:bg-white/5 rounded-lg p-2 border border-slate-100 dark:border-white/5">
            <p className="text-[10px] text-slate-500 dark:text-slate-400 mb-1">总执行</p>
            <p className="text-lg font-bold text-slate-700 dark:text-slate-300">{stats.total_runs}</p>
          </div>
          <div className="bg-slate-50 dark:bg-white/5 rounded-lg p-2 border border-slate-100 dark:border-white/5">
            <p className="text-[10px] text-slate-500 dark:text-slate-400 mb-1">失败</p>
            <p className="text-lg font-bold text-red-500">{stats.failed_runs}</p>
          </div>
        </div>
      </div>
    );
  }

  // 完整模式（保留原有的大图表）
  return (
    <div className="space-y-6">
      {/* 核心指标卡片 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={<Calendar className="w-5 h-5" />}
          label="总任务数"
          value={stats.total_schedules}
          color="indigo"
        />
        <StatCard
          icon={<Activity className="w-5 h-5" />}
          label="活跃任务"
          value={stats.active_schedules}
          color="emerald"
        />
        <StatCard
          icon={<CheckCircle2 className="w-5 h-5" />}
          label="成功率"
          value={`${stats.success_rate}%`}
          color="green"
        />
        <StatCard
          icon={<TrendingUp className="w-5 h-5" />}
          label="总执行次数"
          value={stats.total_runs}
          color="blue"
        />
      </div>

      {/* 执行趋势图表 */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6">
        <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-4">
          执行趋势 (最近7天)
        </h3>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={stats.trend}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis 
              dataKey="date" 
              tick={{ fill: '#64748b', fontSize: 12 }}
            />
            <YAxis 
              tick={{ fill: '#64748b', fontSize: 12 }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#fff',
                border: '1px solid #e5e7eb',
                borderRadius: '8px',
                fontSize: '12px'
              }}
            />
            <Legend 
              wrapperStyle={{ fontSize: '12px' }}
            />
            <Bar 
              dataKey="success" 
              name="成功" 
              fill="#10b981" 
              radius={[4, 4, 0, 0]}
            />
            <Bar 
              dataKey="failed" 
              name="失败" 
              fill="#ef4444" 
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* 详细统计 */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-500/30 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span className="text-sm font-medium text-emerald-700 dark:text-emerald-300">成功执行</span>
          </div>
          <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
            {stats.success_runs}
          </p>
        </div>
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-500/30 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <XCircle className="w-4 h-4 text-red-600 dark:text-red-400" />
            <span className="text-sm font-medium text-red-700 dark:text-red-300">失败执行</span>
          </div>
          <p className="text-2xl font-bold text-red-600 dark:text-red-400">
            {stats.failed_runs}
          </p>
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon, label, value, color }: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color: 'indigo' | 'emerald' | 'green' | 'blue';
}) {
  const colorClasses = {
    indigo: 'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-200 dark:border-indigo-500/30 text-indigo-600 dark:text-indigo-400',
    emerald: 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-500/30 text-emerald-600 dark:text-emerald-400',
    green: 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-500/30 text-green-600 dark:text-green-400',
    blue: 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-500/30 text-blue-600 dark:text-blue-400',
  };

  return (
    <div className={cn(
      "rounded-xl border p-4",
      colorClasses[color]
    )}>
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-sm font-medium">{label}</span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
    </div>
  );
}

