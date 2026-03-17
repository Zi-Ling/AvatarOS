"use client";

import { useState, useEffect } from "react";
import { 
  Calendar, 
  Plus, 
  Clock,
  LayoutList,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  BarChart3,
  XCircle
} from "lucide-react";
import { TimelineView, TimelineNode } from "./_components/TimelineView";
import { CalendarView } from "./_components/CalendarView";
import { EditScheduleDialog } from "./_components/EditScheduleDialog";
import { CreateScheduleDialog } from "./_components/CreateScheduleDialog";
import { StatsPanel } from "./_components/StatsPanel";
import { DependencySelector } from "./_components/DependencySelector";
import { scheduleApi, ScheduleItem } from "@/lib/api/schedule";

export default function SchedulePage() {
  const [viewMode, setViewMode] = useState<'timeline' | 'calendar'>('timeline');
  const [data, setData] = useState<TimelineNode[]>([]);
  const [schedules, setSchedules] = useState<ScheduleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null); // 新增：错误状态
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<ScheduleItem | null>(null);
  const [dependencySchedule, setDependencySchedule] = useState<ScheduleItem | null>(null);
  
  const loadData = async () => {
    setLoading(true);
    setError(null); // 重置错误状态
    
    try {
      // 1. Fetch Schedules (Future) - 带错误处理
      let schedules: Awaited<ReturnType<typeof scheduleApi.listSchedules>> = [];
      let schedulesError = false;
      try {
        schedules = await scheduleApi.listSchedules();
        setSchedules(schedules); // 保存完整数据用于编辑
      } catch (err) {
        console.error('❌ Failed to fetch schedules:', err);
        schedulesError = true;
        // 不崩溃，继续渲染空状态
      }
      
      // 2. Fetch History — 不再需要，Schedule 只管计划
      
      // 设置友好的错误提示
      if (schedulesError) {
        setError('无法连接到后端服务，请检查服务器是否正常运行');
      }
      
      // 3. Transform to TimelineNode
      const futureNodes: TimelineNode[] = schedules.map(s => {
        const nextRunDate = s.next_run_at ? new Date(s.next_run_at) : new Date();
        
        return {
          id: s.id,
          type: 'future' as const,
          // 显示可读的日期时间 (如 "12月1日 09:00")
          timestamp: s.next_run_at 
            ? nextRunDate.toLocaleString('zh-CN', { 
                month: 'short', 
                day: 'numeric', 
                hour: '2-digit', 
                minute: '2-digit',
                hour12: false 
              })
            : 'N/A',
          rawDate: nextRunDate,
          title: s.name,
          description: s.intent_spec.goal,
          status: s.is_active ? 'pending' as const : 'failed' as const,
          meta: `Cron: ${s.cron_expression}`, // Cron 表达式作为技术细节
          isActive: s.is_active, // 新增：是否激活
        };
      }).sort((a, b) => a.rawDate.getTime() - b.rawDate.getTime()); // 按时间排序
      
      // 只保留未来计划节点
      setData([...futureNodes]);
    } catch (e) {
      console.error("Failed to load schedule data", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    
    // 监听 Socket.IO 推送的 Schedule 更新事件
    const handleScheduleUpdate = (event: CustomEvent) => {
      console.log('📅 Schedule页面收到更新事件:', event.detail);
      // 自动刷新数据
      loadData();
    };
    
    window.addEventListener('schedule-updated', handleScheduleUpdate as EventListener);
    
    return () => {
      window.removeEventListener('schedule-updated', handleScheduleUpdate as EventListener);
    };
  }, []);

  const handleCreateTask = () => {
    setShowCreateDialog(true);
  };
  
  const handleEdit = (scheduleId: string) => {
    const schedule = schedules.find(s => s.id === scheduleId);
    if (schedule) setEditingSchedule(schedule);
  };
  
  const handleSetDependency = (scheduleId: string) => {
    const schedule = schedules.find(s => s.id === scheduleId);
    if (schedule) setDependencySchedule(schedule);
  };

  return (
    <div className="flex h-full bg-slate-50 dark:bg-slate-950 overflow-hidden">
      
      {/* 1. Left Sidebar (Navigation & Stats) */}
      <div className="w-72 border-r border-slate-200 dark:border-white/5 bg-white dark:bg-slate-900/50 p-6 flex flex-col backdrop-blur-xl z-20 overflow-y-auto">
        <div className="flex items-center gap-3 mb-8">
          <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
            <Clock className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-800 dark:text-white tracking-tight">Schedule</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">Task Management</p>
          </div>
        </div>

        {/* View Switcher - 只有 Timeline 和 Calendar */}
        <div className="grid grid-cols-2 gap-1 p-1 bg-slate-100 dark:bg-white/5 rounded-xl mb-8">
          <button 
            onClick={() => setViewMode('timeline')}
            className={`flex items-center justify-center gap-2 py-2 text-sm font-medium rounded-lg transition-all ${
              viewMode === 'timeline' 
                ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm scale-[1.02]' 
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-white/50 dark:hover:bg-white/5'
            }`}
          >
            <LayoutList className="w-4 h-4" />
            Timeline
          </button>
          <button 
            onClick={() => setViewMode('calendar')}
            className={`flex items-center justify-center gap-2 py-2 text-sm font-medium rounded-lg transition-all ${
              viewMode === 'calendar' 
                ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm scale-[1.02]' 
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-white/50 dark:hover:bg-white/5'
            }`}
          >
            <Calendar className="w-4 h-4" />
            Calendar
          </button>
        </div>

        {/* Primary Action */}
        <button 
            onClick={handleCreateTask}
            className="group mb-8 flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-500 transition-all shadow-lg shadow-indigo-500/20 active:scale-95 hover:shadow-indigo-500/30"
        >
          <Plus className="w-4 h-4 transition-transform group-hover:rotate-90" />
          Create New Task
        </button>

        {/* Overview - 快速统计 */}
        <div className="space-y-4 mb-6">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2">
            <div className="w-1 h-3 bg-indigo-500 rounded-full" />
            Quick Stats
          </h3>
          <div className="space-y-2">
            <div className="flex justify-between items-center p-2.5 rounded-lg bg-slate-50 dark:bg-white/5 border border-slate-100 dark:border-white/5">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
                <span className="text-xs text-slate-600 dark:text-slate-300">Schedules</span>
              </div>
              <span className="font-mono font-bold text-indigo-500 text-sm">{data.filter(n => n.type === 'future').length}</span>
            </div>
            
            <div className="flex justify-between items-center p-2.5 rounded-lg bg-slate-50 dark:bg-white/5 border border-slate-100 dark:border-white/5">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                <span className="text-xs text-slate-600 dark:text-slate-300">Done</span>
              </div>
              <span className="font-mono font-bold text-emerald-500 text-sm">{data.filter(n => n.type === 'past' && n.status === 'success').length}</span>
            </div>

            <div className="flex justify-between items-center p-2.5 rounded-lg bg-slate-50 dark:bg-white/5 border border-slate-100 dark:border-white/5">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-3 h-3 text-red-500" />
                <span className="text-xs text-slate-600 dark:text-slate-300">Failed</span>
              </div>
              <span className="font-mono font-bold text-red-500 text-sm">{data.filter(n => n.type === 'past' && n.status === 'failed').length}</span>
            </div>
          </div>
        </div>
        
        {/* Stats Panel - 紧凑版统计面板 */}
        <div className="mb-6">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
            <BarChart3 className="w-3.5 h-3.5" />
            Performance
          </h3>
          <StatsPanel compact />
        </div>
        
        <div className="mt-auto shrink-0">
          <div className="p-4 rounded-xl bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 border border-indigo-100 dark:border-indigo-500/10">
            <p className="text-xs text-indigo-600 dark:text-indigo-300 leading-relaxed italic">
              "{viewMode === 'timeline' 
                ? "Focus on the execution flow. One step at a time."
                : "Plan ahead. The future belongs to those who prepare for it."
              }"
            </p>
          </div>
        </div>
      </div>

      {/* 2. Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        {/* Header */}
        <header className="h-20 border-b border-slate-200 dark:border-white/5 flex items-center justify-between px-10 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md z-10 sticky top-0">
           <div>
             <h1 className="text-xl font-bold text-slate-800 dark:text-white tracking-tight">
               {viewMode === 'timeline' ? 'Execution Flow' : 'Planning View'}
             </h1>
             <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
               {viewMode === 'timeline' ? 'Real-time task monitoring and history' : 'Monthly overview and recurrence rules'}
             </p>
           </div>
           
           <div className="flex items-center gap-2">
             <button 
                onClick={loadData}
                className={`p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 transition-colors ${loading ? 'animate-spin' : ''}`}
             >
                <RefreshCw className="w-4 h-4 text-slate-500" />
             </button>
             <div className="flex items-center gap-2 text-sm font-mono text-slate-500 bg-white dark:bg-white/5 border border-slate-200 dark:border-white/10 px-4 py-2 rounded-lg shadow-sm">
               <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
               <span className="opacity-60">SYSTEM TIME:</span>
               <span className="font-bold text-slate-700 dark:text-slate-200">
                 {new Date().toLocaleTimeString('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit' })}
               </span>
             </div>
           </div>
        </header>

        {/* Error Banner - 显示在主内容区顶部 */}
        {error && (
          <div className="mx-10 mt-6 mb-4 p-4 rounded-xl bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-500/30 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                {error}
              </p>
              <p className="text-xs text-yellow-600 dark:text-yellow-400 mt-1">
                后端服务可能未启动或数据库需要更新。页面将继续显示，但数据可能不完整。
              </p>
            </div>
            <button 
              onClick={() => setError(null)}
              className="p-1 rounded-lg hover:bg-yellow-100 dark:hover:bg-yellow-800/30 transition-colors"
            >
              <XCircle className="w-4 h-4 text-yellow-600 dark:text-yellow-400" />
            </button>
          </div>
        )}

        {/* Content Body */}
        <div className="flex-1 overflow-hidden bg-slate-50/50 dark:bg-black/20">
          {viewMode === 'timeline' ? (
            <TimelineView 
              data={data} 
              onRefresh={loadData}
              onEdit={handleEdit}
              onSetDependency={handleSetDependency}
            />
          ) : (
            <CalendarView data={data} />
          )}
        </div>
      </div>

      {/* 编辑任务 Dialog */}
      <EditScheduleDialog
        schedule={editingSchedule}
        onClose={() => setEditingSchedule(null)}
        onSuccess={loadData}
      />

      {/* 依赖选择器 Dialog */}
      <DependencySelector
        schedule={dependencySchedule}
        onClose={() => setDependencySchedule(null)}
        onSuccess={loadData}
      />

      {/* 创建任务 Dialog */}
      <CreateScheduleDialog
        open={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        onSuccess={loadData}
      />

    </div>
  );
}
