"use client";

import React from "react";
import { Workflow, Terminal, Wifi, WifiOff, History, LucideIcon, Code2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { useSocket } from "@/components/providers/SocketProvider";
import { ActiveTaskView } from "./_components/ActiveTaskView";
import { LogsView } from "./_components/LogsView";
import { HistoryView } from "./_components/HistoryView";
import { useTaskExecution } from "@/lib/hooks/useTaskExecution";
import { useWorkbenchStore, type WorkbenchTab } from "@/stores/workbenchStore";
import { useTaskStore } from "@/stores/taskStore";
import { WorkbenchEditor } from "./_components/WorkbenchEditor";

interface TabConfig {
  id: WorkbenchTab;
  label: string;
  icon: LucideIcon;
  badge?: number | string;
  color?: string;
}

export default function Workbench() {
  const { isConnected } = useSocket();
  const { activeTab, setActiveTab, openFiles } = useWorkbenchStore();
  const { task, logs } = useTaskExecution();
  const { pendingApprovals } = useTaskStore();

  const tabs: TabConfig[] = [
    {
      id: "active",
      label: "Active Task",
      icon: Workflow,
      badge: pendingApprovals.length > 0
        ? `⏸ ${pendingApprovals.length}`
        : task?.status === "executing" ? "●" : undefined,
      color: "text-indigo-500",
    },
    { id: "editor", label: "Editor", icon: Code2, badge: openFiles.length > 0 ? openFiles.length : undefined, color: "text-orange-500" },
    { id: "logs", label: "Logs", icon: Terminal, badge: logs.length > 0 ? logs.length : undefined, color: "text-blue-500" },
    { id: "history", label: "History", icon: History, color: "text-purple-500" },
  ];

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-950 border-r border-slate-200 dark:border-slate-800 w-full shadow-xl shadow-slate-200/50 dark:shadow-black/50 z-10">
      {/* Header */}
      <div className="h-14 border-b border-slate-200 dark:border-slate-800 flex items-center px-4 justify-between bg-white dark:bg-slate-950 text-slate-800 dark:text-slate-200">
        <div className="flex items-center gap-2 font-medium text-sm">
          <Workflow className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
          <span>Workbench</span>
        </div>
        <div className="flex items-center gap-3">
          <div className={cn("flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full", isConnected ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400")}>
            {isConnected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            <span>{isConnected ? "LIVE" : "OFFLINE"}</span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-x-auto scrollbar-hide relative">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "relative flex items-center gap-2 px-4 py-3 text-xs font-medium transition-all duration-200",
                "border-b-2 whitespace-nowrap",
                isActive
                  ? "border-indigo-500 text-slate-900 dark:text-white bg-slate-50 dark:bg-slate-800/50"
                  : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/30"
              )}
            >
              <Icon className={cn("w-3.5 h-3.5 transition-colors", isActive && tab.color)} />
              <span>{tab.label}</span>
              {tab.badge && (
                <motion.span
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  className={cn(
                    "ml-1 px-1.5 py-0.5 text-[10px] font-bold rounded-full",
                    isActive ? "bg-indigo-500 text-white" : "bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
                  )}
                >
                  {tab.badge}
                </motion.span>
              )}
              {isActive && (
                <motion.div
                  layoutId="activeTabIndicator"
                  className="absolute bottom-0 left-0 right-0 h-0.5 bg-indigo-500"
                  transition={{ type: "spring", stiffness: 500, damping: 30 }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden relative bg-white dark:bg-slate-950">
        <AnimatePresence mode="wait">
          {activeTab !== "editor" && (
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
              className="absolute inset-0"
            >
              {activeTab === "active" && (
                <div className="absolute inset-0 p-0">
                  {task ? (
                    <ActiveTaskView task={task} />
                  ) : (
                    <div className="flex flex-col items-center justify-center h-full text-slate-400 text-sm gap-3">
                      <div className="w-16 h-16 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                        <Workflow className="w-8 h-8 opacity-20 text-slate-500" />
                      </div>
                      <div className="flex flex-col items-center gap-1">
                        <span className="font-medium text-slate-500 dark:text-slate-400">No Active Task</span>
                        <span className="text-xs text-slate-400">Waiting for instructions...</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {activeTab === "logs" && <LogsView logs={logs} />}
              {activeTab === "history" && <HistoryView />}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Persistent Editor */}
        <div className={cn("absolute inset-0 bg-white dark:bg-slate-950", activeTab === "editor" ? "z-10 block" : "hidden")}>
          <WorkbenchEditor />
        </div>
      </div>
    </div>
  );
}
