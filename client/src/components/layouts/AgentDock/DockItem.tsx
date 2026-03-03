import React from "react";
import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface DockItemProps {
  icon: LucideIcon;
  label: string;
  isActive?: boolean;
  onClick?: () => void;
  shortcut?: string;
  isDraggable?: boolean;
}

export function DockItem({ icon: Icon, label, isActive, onClick, shortcut, isDraggable = false }: DockItemProps) {
  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={onClick}
            type="button"
            className={cn(
              "relative group flex items-center justify-center w-12 h-12 rounded-2xl transition-all duration-300",
              isActive
                ? "bg-indigo-100 dark:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400"
                : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-800 dark:hover:text-white"
            )}
          >
            {/* Active Indicator (Left Bar) */}
            {isActive && (
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-indigo-500 rounded-r-full" />
            )}
            
            <Icon className={cn("w-6 h-6 transition-transform duration-300", isActive ? "scale-110" : "group-hover:scale-110")} />
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" className="ml-2 bg-slate-800 dark:bg-black/80 text-white border-slate-200 dark:border-white/10 backdrop-blur-md">
          <p className="flex items-center gap-2">
            <span className="font-medium">{label}</span>
            {shortcut && <span className="text-xs text-white/50 bg-white/10 px-1 rounded">{shortcut}</span>}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
