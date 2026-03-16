"use client";

import React, { useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

interface LogsViewProps {
  logs: string[];
}

export function LogsView({ logs }: LogsViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const prevLengthRef = useRef<number>(logs.length);
  const isInitialMount = useRef(true);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    if (isInitialMount.current) {
      // 初次挂载：直接跳到底部，不做动画
      el.scrollTop = el.scrollHeight;
      isInitialMount.current = false;
      prevLengthRef.current = logs.length;
      return;
    }

    // 只有新增了日志才滚动
    if (logs.length > prevLengthRef.current) {
      // 判断用户是否已经手动滚上去了（距底部超过 100px 则不强制滚）
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (distanceFromBottom < 100) {
        el.scrollTop = el.scrollHeight;
      }
    }

    prevLengthRef.current = logs.length;
  }, [logs]);

  return (
    <div className="h-full flex flex-col bg-white dark:bg-slate-950 text-slate-700 dark:text-slate-300 font-mono">
      <div
        ref={containerRef}
        className="flex-1 overflow-auto p-4 space-y-1 text-xs leading-relaxed custom-scrollbar"
      >
        {logs.length === 0 && (
          <div className="text-slate-400 dark:text-slate-600 italic mt-2 text-center">-- No logs available --</div>
        )}
        {logs.map((log, i) => {
          const match = log.match(/^\[(.*?)\] \[(.*?)\] \[(.*?)\] (.*)$/);
          let time = "", level = "", module = "", msg = log;
          if (match) {
            time = match[1];
            level = match[2];
            module = match[3];
            msg = match[4];
          }
          return (
            <div key={i} className={[
              "break-all px-2 py-0.5 rounded transition-colors flex gap-2 font-mono",
              "hover:bg-slate-100 dark:hover:bg-white/5",
              "border-b border-slate-100 dark:border-white/5 last:border-0",
            ].join(" ")}>
              {match ? (
                <>
                  <span className="text-slate-400 dark:text-slate-500 select-none w-16 shrink-0">{time}</span>
                  <span className={cn(
                    "w-16 shrink-0 font-bold",
                    level === "INFO" ? "text-blue-600 dark:text-blue-400" :
                    level === "WARNING" ? "text-amber-600 dark:text-amber-400" :
                    level === "ERROR" ? "text-red-600 dark:text-red-400" :
                    "text-slate-500 dark:text-slate-400"
                  )}>{level}</span>
                  <span className="text-purple-600 dark:text-purple-400 w-24 shrink-0 truncate" title={module}>{module}</span>
                  <span className="text-slate-700 dark:text-slate-300 flex-1">{msg}</span>
                </>
              ) : (
                <span className="text-slate-700 dark:text-slate-300">{log}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
