import React from "react";
import { cn } from "@/lib/utils";
import { Clock, Play, Pause, MoreHorizontal, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface Task {
  id: string;
  name: string;
  cron: string;
  status: 'running' | 'paused' | 'idle';
  lastRun?: {
    status: 'success' | 'failed';
    time: string;
  };
  nextRun: string;
  description?: string;
}

interface TaskCardProps {
  task: Task;
  onRun?: () => void;
  onToggle?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}

export function TaskCard({ task, onRun, onToggle, onEdit, onDelete }: TaskCardProps) {
  const isRunning = task.status === 'running';

  return (
    <div
      className={cn(
        "group relative flex items-center gap-4 p-4 rounded-xl border bg-card/50 backdrop-blur-sm",
        "transition-all duration-300 ease-out",
        // 1. Levitation Effect (悬浮 + 阴影)
        "hover:-translate-y-[2px] hover:shadow-lg hover:border-indigo-500/30",
        // 2. Press Effect (按压)
        "active:scale-[0.99] active:duration-100",
        // 4. Running Breathing Effect (执行中呼吸灯)
        isRunning && "border-indigo-500/50 shadow-[0_0_15px_rgba(99,102,241,0.15)] animate-pulse-border"
      )}
    >
      {/* Status Indicator Line */}
      <div className={cn(
        "absolute left-0 top-4 bottom-4 w-1 rounded-r-full transition-colors",
        task.status === 'running' ? "bg-indigo-500" : 
        task.status === 'paused' ? "bg-slate-500" : "bg-emerald-500"
      )} />

      {/* Icon / Status */}
      <div className={cn(
        "flex items-center justify-center w-10 h-10 rounded-full shrink-0",
        task.status === 'running' ? "bg-indigo-500/10 text-indigo-400" : "bg-slate-800 text-slate-400"
      )}>
        {task.status === 'running' ? (
          <Loader2 className="w-5 h-5 animate-spin" />
        ) : (
          <Clock className="w-5 h-5" />
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <h3 className="font-semibold text-slate-200 truncate">{task.name}</h3>
          {task.lastRun && (
            <span className={cn(
              "text-[10px] px-1.5 py-0.5 rounded-full border flex items-center gap-1",
              task.lastRun.status === 'success' 
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400" 
                : "bg-red-500/10 border-red-500/20 text-red-400"
            )}>
              {task.lastRun.status === 'success' ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
              {task.lastRun.time}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <code className="bg-slate-950 px-1.5 py-0.5 rounded text-slate-400 font-mono">{task.cron}</code>
          <span>Next: {task.nextRun}</span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
        <button 
          onClick={(e) => { e.stopPropagation(); onRun?.(); }}
          className="p-2 rounded-lg hover:bg-indigo-500/20 hover:text-indigo-400 text-slate-400 transition-colors"
          title="Run Now"
        >
          <Play className="w-4 h-4" />
        </button>
        <button 
          onClick={(e) => { e.stopPropagation(); onToggle?.(); }}
          className="p-2 rounded-lg hover:bg-white/10 hover:text-white text-slate-400 transition-colors"
          title={task.status === 'paused' ? "Resume" : "Pause"}
        >
          {task.status === 'paused' ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
        </button>
        
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="p-2 rounded-lg hover:bg-white/10 hover:text-white text-slate-400 transition-colors">
              <MoreHorizontal className="w-4 h-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40 bg-slate-950 border-slate-800">
            <DropdownMenuItem onClick={onEdit}>Edit</DropdownMenuItem>
            <DropdownMenuItem onClick={onDelete} className="text-red-400 focus:text-red-400">Delete</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

