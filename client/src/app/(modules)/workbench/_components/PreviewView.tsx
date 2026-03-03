"use client";

import React from "react";
import { FileText } from "lucide-react";

export function PreviewView() {
  return (
    <div className="h-full flex flex-col bg-white dark:bg-slate-950">
      <div className="flex-1 flex flex-col items-center justify-center text-slate-400 text-sm gap-3">
        <div className="w-16 h-16 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
          <FileText className="w-8 h-8 opacity-20 text-slate-500" />
        </div>
        <div className="flex flex-col items-center gap-1">
          <span className="font-medium text-slate-500 dark:text-slate-400">No File Preview</span>
          <span className="text-xs text-slate-400">Generated files will appear here after task completion</span>
        </div>
      </div>
    </div>
  );
}
