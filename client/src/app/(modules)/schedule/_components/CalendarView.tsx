"use client";

import React, { useState } from "react";
import { ChevronLeft, ChevronRight, Plus, MoreHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { TimelineNode } from "./TimelineView";

// 模拟任务数据 (按日期)
type CalendarTask = {
  id: string;
  title: string;
  color: string; // Tailwind class
  type: 'work' | 'personal' | 'system';
};

export function CalendarView({ data }: { data: TimelineNode[] }) {
  // 默认显示当前月份
  const [currentDate, setCurrentDate] = useState(new Date()); 
  
  const formatDateKey = (date: Date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  // Transform TimelineNode[] to CalendarTask map
  const calendarData: Record<string, CalendarTask[]> = {};
  
  data.forEach(node => {
      if (!node.rawDate) return;
      try {
          // Ensure rawDate is a Date object (in case of serialization)
          const dateObj = new Date(node.rawDate);
          if (isNaN(dateObj.getTime())) return; // Invalid date

          const key = formatDateKey(dateObj);
          
          if (!calendarData[key]) calendarData[key] = [];
          
          calendarData[key].push({
              id: node.id,
              title: node.title,
              color: node.status === 'failed' ? "bg-red-500" : (node.type === 'future' ? "bg-indigo-500" : "bg-emerald-500"),
              type: 'system'
          });
      } catch (e) {
          console.error("Date parsing error for node", node.id, e);
      }
  });

  // Sort tasks by time inside each day (optional, for better visual)
  Object.values(calendarData).forEach(list => {
      // We don't have time info in CalendarTask directly, but we assume input data is sorted or just render as is
  });

  // Calculate grid dimensions dynamically based on the month
  const daysInMonth = new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 0).getDate();
  const firstDayOfMonth = new Date(currentDate.getFullYear(), currentDate.getMonth(), 1).getDay(); // 0 = Sunday
  
  // Generate calendar grid cells
  const days = [];
  for (let i = 0; i < firstDayOfMonth; i++) {
    days.push(null); // Padding for previous month
  }
  for (let i = 1; i <= daysInMonth; i++) {
    days.push(new Date(currentDate.getFullYear(), currentDate.getMonth(), i));
  }
  // Add padding for next month to fill the grid (optional, for visual balance)
  const remainingCells = 42 - days.length; // 6 rows * 7 cols = 42
  for(let i=0; i<remainingCells; i++) {
     // days.push(null); // Or render next month's days
  }

  const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

  const handlePrevMonth = () => {
    setCurrentDate(new Date(currentDate.getFullYear(), currentDate.getMonth() - 1, 1));
  };

  const handleNextMonth = () => {
    setCurrentDate(new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 1));
  };
  
  const handleToday = () => {
    setCurrentDate(new Date());
  };

  const isToday = (date: Date) => {
    const today = new Date();
    return date.getDate() === today.getDate() &&
           date.getMonth() === today.getMonth() &&
           date.getFullYear() === today.getFullYear();
  };

  // 检查是否有任务数据
  const totalTasks = Object.keys(calendarData).length;
  const hasAnyData = data.length > 0;
  
  return (
    <div className="flex flex-col h-full p-6 animate-in fade-in zoom-in-95 duration-500">
      {/* 空状态 - 当完全没有数据时 */}
      {!hasAnyData ? (
        <div className="flex flex-col items-center justify-center h-full">
          <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 flex items-center justify-center mb-6">
            <Calendar className="w-12 h-12 text-indigo-300 dark:text-indigo-600" />
          </div>
          <h3 className="text-xl font-semibold text-slate-600 dark:text-slate-300 mb-2">暂无任务</h3>
          <p className="text-sm text-slate-400 max-w-md text-center leading-relaxed">
            通过聊天窗口说 <span className="text-indigo-500 font-medium">"每天早上9点提醒我..."</span> 来创建定时任务
          </p>
        </div>
      ) : (
        <>
          {/* Calendar Header */}
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-4">
              <h2 className="text-2xl font-light text-slate-800 dark:text-white">
                {monthNames[currentDate.getMonth()]} <span className="font-semibold text-indigo-500">{currentDate.getFullYear()}</span>
              </h2>
              <div className="flex items-center gap-2">
                {/* 月份切换 */}
                <div className="flex items-center bg-white dark:bg-slate-800 rounded-lg p-1 border border-slate-200 dark:border-white/10 shadow-sm">
                  <button onClick={handlePrevMonth} className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-md transition-colors">
                    <ChevronLeft className="w-4 h-4 text-slate-500" />
                  </button>
                  <button onClick={handleNextMonth} className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-md transition-colors">
                    <ChevronRight className="w-4 h-4 text-slate-500" />
                  </button>
                </div>
                {/* 今日按钮 */}
                <button 
                  onClick={handleToday}
                  className="px-3 py-1.5 text-xs font-medium bg-indigo-500 hover:bg-indigo-600 text-white rounded-lg shadow-sm transition-colors"
                >
                  今日
                </button>
              </div>
            </div>
        
            {/* Legend */}
            <div className="flex items-center gap-4 text-xs text-slate-500">
              <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-indigo-500" /> 未来</div>
              <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-emerald-500" /> 已完成</div>
              <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-red-500" /> 失败</div>
            </div>
          </div>

          {/* 当月无任务提示 */}
          {totalTasks === 0 && (
            <div className="flex-1 flex flex-col items-center justify-center bg-white/50 dark:bg-slate-900/50 backdrop-blur-xl rounded-2xl border border-slate-200 dark:border-white/5 shadow-xl">
              <div className="text-center">
                <div className="w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto mb-4">
                  <Calendar className="w-8 h-8 text-slate-300 dark:text-slate-600" />
                </div>
                <h3 className="text-base font-semibold text-slate-500 dark:text-slate-400 mb-2">
                  {monthNames[currentDate.getMonth()]} 月暂无任务
                </h3>
                <p className="text-xs text-slate-400">
                  尝试切换到其他月份查看
                </p>
              </div>
            </div>
          )}

          {/* Calendar Grid Container - Glassmorphism */}
          {totalTasks > 0 && (
            <div className="flex-1 bg-white/50 dark:bg-slate-900/50 backdrop-blur-xl rounded-2xl border border-slate-200 dark:border-white/5 shadow-xl overflow-hidden flex flex-col">
        
        {/* Weekday Headers */}
        <div className="grid grid-cols-7 border-b border-slate-200 dark:border-white/5 bg-slate-50/80 dark:bg-slate-800/50">
          {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(day => (
            <div key={day} className="py-3 text-center text-xs font-bold text-slate-400 uppercase tracking-widest">
              {day}
            </div>
          ))}
        </div>

        {/* Days Grid */}
        <div className="flex-1 grid grid-cols-7 grid-rows-5"> 
          {days.map((date, index) => {
            if (!date) return <div key={`pad-${index}`} className="bg-slate-50/30 dark:bg-slate-900/20 border-r border-b border-slate-100 dark:border-white/5" />;
            
            const dateKey = formatDateKey(date);
            const tasks = calendarData[dateKey] || [];
            const today = isToday(date);

            return (
              <div 
                key={dateKey} 
                className={cn(
                  "relative border-r border-b border-slate-100 dark:border-white/5 p-2 transition-all hover:bg-white dark:hover:bg-slate-800/80 group cursor-pointer flex flex-col gap-1",
                  today && "bg-indigo-50/20 dark:bg-indigo-500/5"
                )}
              >
                {/* Date Number */}
                <div className="flex justify-between items-start">
                  <span className={cn(
                    "text-sm font-medium w-7 h-7 flex items-center justify-center rounded-full transition-all",
                    today 
                      ? "bg-indigo-600 text-white shadow-lg shadow-indigo-500/30 scale-110" 
                      : "text-slate-500 dark:text-slate-400 group-hover:text-slate-900 dark:group-hover:text-white"
                  )}>
                    {date.getDate()}
                  </span>
                  
                  {/* Add Button */}
                  <button className="opacity-0 group-hover:opacity-100 p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-full text-slate-400 transition-opacity">
                    <Plus className="w-3 h-3" />
                  </button>
                </div>

                {/* Task Stack */}
                <div className="flex flex-col gap-1 mt-1 overflow-hidden">
                  {tasks.slice(0, 3).map((task) => (
                    <div 
                      key={task.id} 
                      className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-white/80 dark:bg-slate-800/80 border border-slate-100 dark:border-white/5 hover:border-indigo-300 dark:hover:border-indigo-500 transition-all shadow-sm"
                    >
                      <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${task.color}`} />
                      <span className="text-[10px] font-medium text-slate-600 dark:text-slate-300 truncate">
                        {task.title}
                      </span>
                    </div>
                  ))}
                  
                  {/* Stack Indicator */}
                  {tasks.length > 3 && (
                    <div className="flex items-center gap-1 pl-2 mt-0.5">
                      <div className="flex -space-x-1">
                         {[...Array(Math.min(tasks.length - 3, 3))].map((_, i) => (
                           <div key={i} className={`w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 border border-white dark:border-slate-900`} />
                         ))}
                      </div>
                      <span className="text-[9px] text-slate-400 font-medium">
                        +{tasks.length - 3} more
                      </span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
          )}
        </>
      )}
    </div>
  );
}
