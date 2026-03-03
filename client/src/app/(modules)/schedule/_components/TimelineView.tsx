"use client";

import { useState } from "react";
import { 
  History, 
  ArrowRight,
  CheckCircle2,
  XCircle,
  Loader2,
  MoreHorizontal,
  Trash2,
  Play,
  Pause,
  Zap,
  Edit,
  Link2
} from "lucide-react";
import { cn } from "@/lib/utils";
import { scheduleApi } from "@/lib/api/schedule";
import { useToast } from "@/lib/hooks/useToast";

// 统一的时间线节点类型 (Exported for shared use if needed, but kept here for now)
export interface TimelineNode {
  id: string;
  type: 'past' | 'present' | 'future';
  timestamp: string;
  rawDate?: Date; // Added for Calendar mapping
  title: string;
  description?: string;
  status?: 'success' | 'failed' | 'running' | 'pending';
  meta?: string;
  isActive?: boolean; // 新增：任务是否激活（仅 future 类型）
}

function TimelineItem({ node, isLast, onAction, onClickHistory, onEdit, onSetDependency }: { 
  node: TimelineNode; 
  isLast: boolean;
  onAction?: (action: 'delete' | 'toggle' | 'run', id: string) => void;
  onClickHistory?: (id: string) => void;
  onEdit?: (id: string) => void;
  onSetDependency?: (id: string) => void;
}) {
  const isFuture = node.type === 'future';
  const isPast = node.type === 'past';
  const isRunning = node.status === 'running';
  const [showMenu, setShowMenu] = useState(false);

  const handleAction = (action: 'delete' | 'toggle' | 'run' | 'edit' | 'dependency') => {
    setShowMenu(false);
    if (action === 'edit' && onEdit) {
      onEdit(node.id);
    } else if (action === 'dependency' && onSetDependency) {
      onSetDependency(node.id);
    } else {
      onAction?.(action as any, node.id);
    }
  };

  const handleCardClick = () => {
    if (isPast && onClickHistory) {
      onClickHistory(node.id);
    }
  };

  return (
    <div className="relative flex gap-6 group">
      {/* Time Column */}
      <div className="w-24 pt-1 flex flex-col items-end shrink-0">
        <span className={cn(
          "text-sm font-medium",
          isFuture ? "text-indigo-400" : "text-slate-500 dark:text-slate-400"
        )}>
          {node.timestamp}
        </span>
        {isFuture && (
          <span className="text-[10px] text-slate-400 bg-slate-100 dark:bg-white/5 px-1.5 py-0.5 rounded mt-1">
            Scheduled
          </span>
        )}
      </div>

      {/* Line & Dot */}
      <div className="relative flex flex-col items-center">
        {/* Vertical Line */}
        {!isLast && (
          <div className={cn(
            "absolute top-3 bottom-[-40px] w-px z-0",
            isFuture ? "bg-indigo-200 dark:bg-indigo-500/20 border-l border-dashed border-indigo-300 dark:border-indigo-500/30 bg-transparent" : "bg-slate-200 dark:bg-white/10"
          )} />
        )}
        
        {/* Dot */}
        <div className={cn(
          "w-3 h-3 rounded-full z-10 ring-4 ring-slate-50 dark:ring-slate-900 mt-1.5 transition-all duration-300",
          isRunning ? "bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,0.5)] scale-125 animate-pulse" :
          isFuture ? "bg-white dark:bg-slate-900 border-2 border-indigo-400" :
          node.status === 'failed' ? "bg-red-500" :
          "bg-slate-300 dark:bg-slate-600 group-hover:bg-indigo-500 group-hover:scale-125"
        )} />
      </div>

      {/* Content Card */}
      <div className={cn(
        "flex-1 pb-8 transition-all duration-300",
        isFuture ? "opacity-80 group-hover:opacity-100" : "opacity-100"
      )}>
        <div 
          onClick={handleCardClick}
          className={cn(
            "relative p-4 rounded-xl border transition-all duration-300",
            isRunning 
              ? "bg-indigo-50/50 dark:bg-indigo-500/10 border-indigo-200 dark:border-indigo-500/30 shadow-lg shadow-indigo-500/10 scale-[1.01]" 
              : "bg-white dark:bg-slate-800 border-slate-200 dark:border-white/5 hover:shadow-md hover:border-indigo-200 dark:hover:border-indigo-500/30 hover:-translate-y-0.5",
            isPast && "cursor-pointer"
          )}
        >
          {/* Header */}
          <div className="flex items-start justify-between mb-2">
            <h3 className={cn(
              "font-semibold text-base",
              node.status === 'failed' ? "text-red-500" : 
              isFuture ? "text-indigo-600 dark:text-indigo-300" : "text-slate-800 dark:text-white"
            )}>
              {node.title}
            </h3>
            
            {/* Status Icon / Action Menu */}
            {node.status === 'failed' ? (
              <XCircle className="w-4 h-4 text-red-500" />
            ) : node.status === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-green-500 opacity-50" />
            ) : isRunning ? (
              <Loader2 className="w-4 h-4 text-indigo-500 animate-spin" />
            ) : isFuture ? (
              // 未来任务：显示操作菜单
              <div className="relative">
                <button 
                  onClick={() => setShowMenu(!showMenu)}
                  className="p-1 hover:bg-slate-100 dark:hover:bg-white/10 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <MoreHorizontal className="w-4 h-4 text-slate-400" />
                </button>
                
                {/* Dropdown Menu */}
                {showMenu && (
                  <>
                    {/* Backdrop */}
                    <div 
                      className="fixed inset-0 z-10" 
                      onClick={() => setShowMenu(false)}
                    />
                    {/* Menu */}
                    <div className="absolute right-0 top-8 w-48 bg-white dark:bg-slate-800 rounded-lg shadow-xl border border-slate-200 dark:border-slate-700 py-1 z-20 animate-in fade-in zoom-in-95 duration-100">
                      <button
                        onClick={() => handleAction('edit')}
                        className="w-full px-4 py-2 text-left text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 flex items-center gap-2"
                      >
                        <Edit className="w-3.5 h-3.5 text-slate-500" />
                        编辑时间/频率
                      </button>
                      <button
                        onClick={() => handleAction('dependency')}
                        className="w-full px-4 py-2 text-left text-sm text-slate-700 dark:text-slate-300 hover:bg-purple-50 dark:hover:bg-purple-500/10 flex items-center gap-2"
                      >
                        <Link2 className="w-3.5 h-3.5 text-purple-500" />
                        设置依赖
                      </button>
                      <button
                        onClick={() => handleAction('run')}
                        className="w-full px-4 py-2 text-left text-sm text-slate-700 dark:text-slate-300 hover:bg-indigo-50 dark:hover:bg-indigo-500/10 flex items-center gap-2"
                      >
                        <Zap className="w-3.5 h-3.5 text-indigo-500" />
                        立即执行一次
                      </button>
                      <button
                        onClick={() => handleAction('toggle')}
                        className="w-full px-4 py-2 text-left text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 flex items-center gap-2"
                      >
                        {node.isActive ? (
                          <>
                            <Pause className="w-3.5 h-3.5 text-amber-500" />
                            暂停任务
                          </>
                        ) : (
                          <>
                            <Play className="w-3.5 h-3.5 text-emerald-500" />
                            恢复任务
                          </>
                        )}
                      </button>
                      <div className="h-px bg-slate-200 dark:bg-slate-700 my-1" />
                      <button
                        onClick={() => handleAction('delete')}
                        className="w-full px-4 py-2 text-left text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 flex items-center gap-2"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        删除任务
                      </button>
                    </div>
                  </>
                )}
              </div>
            ) : null}
          </div>

          {/* Description */}
          {node.description && (
            <p className="text-sm text-slate-600 dark:text-slate-400 mb-3 line-clamp-2">
              {node.description}
            </p>
          )}

          {/* Footer Meta */}
          <div className="flex items-center gap-3 text-xs text-slate-400">
            {node.meta && (
              <span className="bg-slate-100 dark:bg-white/5 px-1.5 py-0.5 rounded font-mono">
                {node.meta}
              </span>
            )}
            {isFuture && (
              node.isActive ? (
                <span className="flex items-center gap-1 text-indigo-400">
                  <ArrowRight className="w-3 h-3" /> 等待执行
                </span>
              ) : (
                <span className="flex items-center gap-1 text-slate-400">
                  ⏸ 已暂停
                </span>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function TimelineView({ data, onRefresh, onClickHistory, onEdit, onSetDependency }: { 
  data: TimelineNode[];
  onRefresh?: () => void;
  onClickHistory?: (taskId: string) => void;
  onEdit?: (scheduleId: string) => void;
  onSetDependency?: (scheduleId: string) => void;
}) {
  const toast = useToast();
  
  // 动态计算 "Now" 分隔线位置
  const nowIndex = data.findIndex(node => node.type === 'past');
  const hasFuture = data.some(node => node.type === 'future');
  const hasPast = data.some(node => node.type === 'past');
  
  const handleAction = async (action: 'delete' | 'toggle' | 'run', id: string) => {
    try {
      if (action === 'delete') {
        if (confirm('确定要删除这个定时任务吗？')) {
          await scheduleApi.deleteSchedule(id);
          toast.success('删除成功', '定时任务已删除');
          onRefresh?.();
        }
      } else if (action === 'toggle') {
        // 查找当前节点状态
        const node = data.find(n => n.id === id);
        if (node) {
          await scheduleApi.toggleSchedule(id, !node.isActive);
          toast.success(
            node.isActive ? '已暂停' : '已恢复',
            node.isActive ? '任务已暂停执行' : '任务已恢复执行'
          );
          onRefresh?.();
        }
      } else if (action === 'run') {
        if (confirm('确定要立即执行一次此任务吗？')) {
          await scheduleApi.runScheduleOnce(id);
          toast.success('执行已启动', '请在 Workbench 查看执行状态');
        }
      }
    } catch (error) {
      console.error('操作失败:', error);
      toast.error('操作失败', error instanceof Error ? error.message : '未知错误');
    }
  };
  
  return (
    <div className="flex-1 overflow-y-auto p-8 scroll-smooth">
      <div className="max-w-3xl mx-auto">
        
        {/* Future Section Header - 仅在有未来任务时显示 */}
        {hasFuture && (
          <div className="flex items-center gap-4 mb-8 opacity-60">
            <div className="h-px flex-1 bg-indigo-200 dark:bg-indigo-500/30 border-t border-dashed border-indigo-300" />
            <span className="text-xs font-medium text-indigo-400 uppercase tracking-widest">Future Plans</span>
            <div className="h-px flex-1 bg-indigo-200 dark:bg-indigo-500/30 border-t border-dashed border-indigo-300" />
          </div>
        )}

        {/* Timeline Items */}
        <div className="space-y-0">
          {data.map((node, index) => (
            <div key={node.id} className="animate-in slide-in-from-bottom-4 fade-in duration-700" style={{ animationDelay: `${index * 100}ms` }}>
               {/* 动态 "Now" 分隔线 - 在未来和过去任务的交界处插入 */}
               {index === nowIndex && nowIndex > 0 && (
                  <div className="flex items-center gap-4 my-8">
                    <div className="h-px flex-1 bg-slate-200 dark:bg-white/10" />
                    <span className="text-xs font-bold text-slate-800 dark:text-white uppercase tracking-widest bg-slate-100 dark:bg-white/10 px-3 py-1 rounded-full">Now</span>
                    <div className="h-px flex-1 bg-slate-200 dark:bg-white/10" />
                  </div>
               )}
               
               <TimelineItem 
                 node={node} 
                 isLast={index === data.length - 1}
                 onAction={handleAction}
                 onClickHistory={onClickHistory}
                 onEdit={onEdit}
                 onSetDependency={onSetDependency}
               />
            </div>
          ))}
        </div>
        
         {/* Past Section End - 仅在有历史记录时显示 */}
         {hasPast && (
           <div className="flex items-center justify-center mt-8 mb-12">
              <button className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors flex items-center gap-1">
                 <History className="w-3 h-3" /> 加载更多历史记录
              </button>
           </div>
         )}
         
         {/* 空状态 - 当没有任何任务时 */}
         {data.length === 0 && (
           <div className="flex flex-col items-center justify-center py-20 text-center">
             <div className="w-20 h-20 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
               <History className="w-10 h-10 text-slate-300 dark:text-slate-600" />
             </div>
             <h3 className="text-lg font-semibold text-slate-600 dark:text-slate-300 mb-2">暂无任务记录</h3>
             <p className="text-sm text-slate-400 max-w-sm">
               在聊天窗口告诉我 "每天早上9点提醒我..." 来创建定时任务
             </p>
           </div>
         )}

      </div>
    </div>
  );
}

