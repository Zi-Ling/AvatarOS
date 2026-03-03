"use client";

import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { 
  Activity,
  CheckCircle2,
  Clock,
  LayoutDashboard,
  BrainCircuit,
  Pin,
  PinOff,
  Cpu,
  Zap
} from "lucide-react";
import { APP_REGISTRY, getAppById, AppId } from "@/lib/apps";
import { useDockApps } from "@/lib/hooks/useDockApps";
import { AvatarOrb } from "@/components/ui/AvatarOrb";
import { historyApi } from "@/lib/api/history";
import { scheduleApi } from "@/lib/api/schedule";

// HUD Widget Component (More Sci-fi/Minimal)
function HudWidget({ title, value, icon: Icon, color, position, loading }: any) {
  return (
    <div className={`absolute flex items-center gap-3 backdrop-blur-md bg-white/5 border border-white/10 rounded-2xl px-4 py-3 transition-all hover:bg-white/10 ${position} min-w-[140px]`}>
      <div className={`p-2 rounded-full ${color} bg-opacity-20 text-opacity-100`}>
        <Icon className={`w-5 h-5 ${color.replace('bg-', 'text-')}`} />
      </div>
      <div>
        <div className="text-[10px] font-medium text-slate-400 uppercase tracking-widest">{title}</div>
        {loading ? (
            <div className="h-6 w-16 bg-white/10 rounded animate-pulse mt-1" />
        ) : (
            <div className="text-lg font-bold text-white tabular-nums">{value}</div>
        )}
      </div>
    </div>
  );
}

// App Icon Component
function AppIcon({ app, isPinned, onPinToggle, onClick, isAvatarMode, isAvatarEnabled, onAvatarToggle }: any) {
  const Icon = app.icon;
  const colorClass = app.color.replace('text-', 'bg-'); 

  // Avatar Mode 特殊渲染
  if (isAvatarMode) {
    return (
      <div className="relative group">
        <button 
          onClick={onAvatarToggle}
          className={`w-full flex flex-col items-center justify-center gap-3 p-6 rounded-2xl backdrop-blur-sm border-2 transition-all relative overflow-hidden ${
            isAvatarEnabled 
              ? 'bg-gradient-to-br from-indigo-500/20 to-purple-500/20 dark:from-indigo-500/30 dark:to-purple-500/30 border-indigo-400/50 dark:border-indigo-400/60 shadow-lg shadow-indigo-500/20' 
              : 'bg-white/40 dark:bg-slate-800/40 border-white/20 dark:border-white/5 hover:bg-white/60 dark:hover:bg-slate-700/60'
          } hover:scale-[1.02]`}
        >
          {/* 背景动画效果 */}
          {isAvatarEnabled && (
            <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/10 via-purple-500/10 to-pink-500/10 animate-pulse" />
          )}
          
          {/* 图标 */}
          <div className={`relative w-12 h-12 rounded-xl flex items-center justify-center ${colorClass} text-white shadow-lg transition-transform ${
            isAvatarEnabled ? 'scale-110' : ''
          }`}>
            <Icon className="w-6 h-6" />
          </div>
          
          {/* 标签 */}
          <span className={`text-sm font-medium transition-colors ${
            isAvatarEnabled 
              ? 'text-indigo-700 dark:text-indigo-300' 
              : 'text-slate-700 dark:text-slate-200'
          }`}>
            {app.label}
          </span>
        </button>
      </div>
    );
  }

  // 普通应用渲染
  return (
    <div className="relative group">
      <button 
        onClick={onClick}
        disabled={app.comingSoon}
        className={`w-full flex flex-col items-center justify-center gap-3 p-6 rounded-2xl bg-white/40 dark:bg-slate-800/40 backdrop-blur-sm border border-white/20 dark:border-white/5 hover:bg-white/60 dark:hover:bg-slate-700/60 hover:scale-[1.02] transition-all relative ${app.comingSoon ? 'opacity-50 grayscale cursor-not-allowed' : 'shadow-sm'}`}
      >
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${colorClass} text-white shadow-lg`}>
          <Icon className="w-6 h-6" />
        </div>
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{app.label}</span>
        
        {app.comingSoon && (
          <span className="absolute top-2 right-2 text-[9px] font-bold bg-slate-200/50 dark:bg-slate-900/50 text-slate-500 px-1.5 py-0.5 rounded uppercase tracking-wide">
            Soon
          </span>
        )}
      </button>

      {/* 固定按钮 */}
      {!app.comingSoon && (
        <button 
          onClick={(e) => { e.stopPropagation(); onPinToggle(); }}
          className={`absolute top-2 right-2 p-1.5 rounded-full transition-all ${
            isPinned 
              ? 'bg-indigo-100 text-indigo-600 opacity-100' 
              : 'bg-slate-100/50 text-slate-400 opacity-0 group-hover:opacity-100 hover:bg-indigo-50 hover:text-indigo-500'
          }`}
          title={isPinned ? "Unpin from Dock" : "Pin to Dock"}
        >
          {isPinned ? <PinOff className="w-3 h-3" /> : <Pin className="w-3 h-3" />}
        </button>
      )}
    </div>
  );
}

export default function HomePage() {
  const router = useRouter();
  const { isPinned, togglePin } = useDockApps();
  const [stats, setStats] = useState({
      tasksCompleted: 0,
      successRate: 0,
      activeSchedules: 0,
      nextTaskTime: "--:--"
  });
  const [loading, setLoading] = useState(true);
  const [isAvatarEnabled, setIsAvatarEnabled] = useState(false);

  // Fetch Real Data
  useEffect(() => {
      const fetchData = async () => {
          try {
              // Parallel fetch
              const [tasks, schedules] = await Promise.all([
                  historyApi.listTasks(50),
                  scheduleApi.listSchedules()
              ]);

              // Calculate Stats
              const completed = tasks.filter(t => {
                  // Check if last run was successful
                  const lastRun = t.runs && t.runs[0];
                  return lastRun && lastRun.status === 'success';
              }).length;
              
              const total = tasks.length;
              const rate = total > 0 ? Math.round((completed / total) * 100) : 0;
              
              const activeScheds = schedules.filter(s => s.is_active).length;
              
              // Find next run time
              let nextTime = "--:--";
              const upcoming = schedules
                  .filter(s => s.is_active && s.next_run_at)
                  .map(s => new Date(s.next_run_at || "").getTime())
                  .sort((a,b) => a - b);
              
              if (upcoming.length > 0) {
                  const d = new Date(upcoming[0]);
                  nextTime = `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
              }

              setStats({
                  tasksCompleted: completed,
                  successRate: rate,
                  activeSchedules: activeScheds,
                  nextTaskTime: nextTime
              });
          } catch (e) {
              console.error("Failed to fetch dashboard data", e);
          } finally {
              setLoading(false);
          }
      };
      
      fetchData();
  }, []);

  // 检查桌面精灵球状态
  useEffect(() => {
    const checkFloatingWindow = async () => {
      const electronAPI = window.electronAPI as any;
      if (electronAPI?.isFloatingWindowVisible) {
        const isVisible = await electronAPI.isFloatingWindowVisible();
        setIsAvatarEnabled(isVisible);
      }
    };
    checkFloatingWindow();
  }, []);

  // 切换桌面精灵球
  const handleAvatarToggle = async () => {
    const electronAPI = window.electronAPI as any;
    if (electronAPI?.toggleFloatingWindow) {
      const newState = await electronAPI.toggleFloatingWindow();
      setIsAvatarEnabled(newState);
    }
  };

  // Dynamic Greeting
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good Morning" : hour < 18 ? "Good Afternoon" : "Good Evening";

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-slate-950 overflow-hidden relative">
      {/* Background Ambience */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
         <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-indigo-500/10 blur-[100px]" />
         <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-purple-500/10 blur-[100px]" />
      </div>

      {/* Top Section: Avatar Core & HUD */}
      <div className="flex-1 relative flex flex-col items-center justify-center min-h-[500px] pb-32">
        
        {/* Greeting */}
        <div className="text-center mb-8 z-10">
           <h1 className="text-4xl font-light tracking-tight text-slate-800 dark:text-white mb-2">
             {greeting}, <span className="font-semibold">User</span>
           </h1>
           <p className="text-slate-500 dark:text-slate-400 text-sm uppercase tracking-widest">
             System Nominal • All Systems Go
           </p>
        </div>

        {/* The Core */}
        <div className="relative z-10">
           <AvatarOrb state="idle" />
           
           {/* HUD Widgets Positioned Around Core */}
           <HudWidget 
             title="Completed Tasks" 
             value={stats.tasksCompleted} 
             icon={CheckCircle2} 
             color="bg-emerald-500" 
             position="absolute top-1/2 -left-[220px] -translate-y-1/2"
             loading={loading}
           />
           <HudWidget 
             title="Success Rate" 
             value={`${stats.successRate}%`} 
             icon={Activity} 
             color="bg-cyan-500" 
             position="absolute top-1/2 -right-[220px] -translate-y-1/2"
             loading={loading}
           />
           <HudWidget 
             title="Next Schedule" 
             value={stats.nextTaskTime} 
             icon={Clock} 
             color="bg-indigo-500" 
             position="absolute -bottom-[80px] left-1/2 -translate-x-1/2"
             loading={loading}
           />
        </div>
      </div>

      {/* Bottom Section: Control Deck (Apps) */}
      <div className="relative z-20 bg-white/30 dark:bg-slate-900/30 backdrop-blur-xl border-t border-white/10 p-8 pb-12">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between mb-6">
             <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider flex items-center gap-2">
               <LayoutDashboard className="w-4 h-4" />
               Control Deck
             </h2>
             <div className="h-px flex-1 bg-slate-200 dark:bg-white/5 ml-4" />
          </div>
          
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {APP_REGISTRY.map((app) => (
              <AppIcon 
                key={app.id}
                app={app}
                isPinned={isPinned(app.id)}
                onPinToggle={() => togglePin(app.id)}
                onClick={() => !app.comingSoon && app.path && router.push(app.path)}
                isAvatarMode={app.id === 'avatar'}
                isAvatarEnabled={isAvatarEnabled}
                onAvatarToggle={handleAvatarToggle}
              />
            ))}
          </div>
        </div>
      </div>

    </div>
  );
}
