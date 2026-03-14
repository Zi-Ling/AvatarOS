import React from "react";
import { Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface SystemStatusProps {
  status: 'idle' | 'thinking' | 'executing' | 'error';
  isConnected: boolean;
  onOpenSettings?: () => void;
}

export function SystemStatus({ onOpenSettings }: SystemStatusProps) {
  return (
    <div className="flex flex-col items-center pb-4">
      <TooltipProvider delayDuration={0}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onOpenSettings}
              className={cn(
                "flex items-center justify-center w-12 h-12 rounded-2xl transition-all duration-300",
                "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 hover:text-slate-800 dark:hover:text-white"
              )}
            >
              <Settings className="w-5 h-5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right" className="ml-2 bg-slate-800 dark:bg-black/80 text-white border-slate-200 dark:border-white/10 backdrop-blur-md">
            <p className="font-medium">Settings</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}

