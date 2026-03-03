import React from "react";
import { Activity } from "lucide-react";
import { cn } from "@/lib/utils";

interface SystemStatusProps {
  status: 'idle' | 'thinking' | 'executing' | 'error';
  isConnected: boolean;
}

export function SystemStatus({ status, isConnected }: SystemStatusProps) {
  const getStatusColor = () => {
    if (!isConnected) return "bg-slate-500";
    switch (status) {
      case 'idle': return "bg-emerald-500";
      case 'thinking': return "bg-blue-500";
      case 'executing': return "bg-purple-500";
      case 'error': return "bg-red-500";
      default: return "bg-emerald-500";
    }
  };

  const getStatusLabel = () => {
    if (!isConnected) return "Offline";
    switch (status) {
      case 'idle': return "Idle";
      case 'thinking': return "Thinking";
      case 'executing': return "Running";
      case 'error': return "Error";
      default: return "Idle";
    }
  };

  return (
    <div className="flex flex-col items-center gap-2 mt-auto pb-4">
      {/* Status Widget */}
      <div className="relative group cursor-pointer">
        {/* Pulse Effect */}
        <div className={cn(
          "absolute inset-0 rounded-full opacity-50 blur-sm transition-all duration-500",
          getStatusColor(),
          status === 'thinking' || status === 'executing' ? "animate-pulse" : ""
        )} />
        
        {/* Core Indicator */}
        <div className={cn(
          "relative w-3 h-3 rounded-full transition-colors duration-300 border border-black/50",
          getStatusColor()
        )} />

        {/* Tooltip-like Status Text (Visible on hover) */}
        <div className="absolute left-full ml-4 top-1/2 -translate-y-1/2 px-2 py-1 rounded bg-slate-800 dark:bg-black/80 text-[10px] font-mono text-white border border-slate-200 dark:border-white/10 backdrop-blur-md opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-50">
          CPU: 12% | MEM: 4.2GB
          <br/>
          STATUS: {getStatusLabel()}
        </div>
      </div>
    </div>
  );
}

