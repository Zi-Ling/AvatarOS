"use client";

import React from "react";
import { History } from "lucide-react";

export function HistoryView() {
  return (
    <div className="h-full flex flex-col bg-white dark:bg-slate-950">
      <div className="flex-1 overflow-auto p-4">
        <div className="space-y-3">
          <div className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-4">
            Task History
          </div>
          <div className="flex flex-col items-center justify-center h-full text-slate-400 text-sm gap-3 py-20">
            <div className="w-16 h-16 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
              <History className="w-8 h-8 opacity-20 text-slate-500" />
            </div>
            <div className="flex flex-col items-center gap-1">
              <span className="font-medium text-slate-500 dark:text-slate-400">No History</span>
              <span className="text-xs text-slate-400">Task execution history will appear here</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
