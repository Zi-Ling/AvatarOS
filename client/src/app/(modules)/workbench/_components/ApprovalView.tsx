"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ShieldCheck,
  ShieldX,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTaskStore } from "@/stores/taskStore";
import { approvalApi, ApprovalHistoryRecord } from "@/lib/api/history";

type HistoryFilter = "all" | "pending" | "approved" | "rejected" | "expired";

const STATUS_CONFIG: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  pending:  { icon: Clock,        color: "text-amber-500",  label: "Pending"  },
  approved: { icon: CheckCircle2, color: "text-green-500",  label: "Approved" },
  rejected: { icon: XCircle,      color: "text-red-500",    label: "Rejected" },
  expired:  { icon: AlertTriangle,color: "text-slate-400",  label: "Expired"  },
};

export function ApprovalView() {
  const { pendingApprovals, removePendingApproval } = useTaskStore();
  const [submitting, setSubmitting] = useState<Record<string, boolean>>({});

  const [history, setHistory] = useState<ApprovalHistoryRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [filter, setFilter] = useState<HistoryFilter>("all");

  const fetchHistory = () => {
    setHistoryLoading(true);
    approvalApi
      .getHistory(filter === "all" ? undefined : filter, 50)
      .then((r) => setHistory(r.records))
      .catch(console.error)
      .finally(() => setHistoryLoading(false));
  };

  useEffect(() => { fetchHistory(); }, [filter]);

  const handleRespond = async (requestId: string, approved: boolean) => {
    setSubmitting((s) => ({ ...s, [requestId]: true }));
    try {
      await approvalApi.respond(requestId, approved);
      removePendingApproval(requestId);
      fetchHistory();
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting((s) => ({ ...s, [requestId]: false }));
    }
  };

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-50 dark:bg-slate-950">
      {/* 待审批队列 */}
      <div className="shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950">
        <div className="px-4 py-2.5 flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Pending
            {pendingApprovals.length > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 bg-amber-500 text-white rounded-full text-[9px]">
                {pendingApprovals.length}
              </span>
            )}
          </span>
        </div>

        <AnimatePresence>
          {pendingApprovals.length === 0 ? (
            <div className="px-4 pb-3 text-xs text-slate-400">No pending approvals</div>
          ) : (
            <div className="px-3 pb-3 space-y-2 max-h-52 overflow-y-auto custom-scrollbar">
              {pendingApprovals.map((req) => (
                <motion.div
                  key={req.request_id}
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  className="rounded-lg border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10 p-3"
                >
                  <div className="flex items-start gap-2 mb-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium text-slate-800 dark:text-slate-100 leading-snug">
                        {req.message}
                      </div>
                      <div className="text-[10px] font-mono text-slate-400 mt-0.5 truncate">
                        {req.operation}
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleRespond(req.request_id, true)}
                      disabled={submitting[req.request_id]}
                      className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-md bg-green-500 hover:bg-green-600 text-white text-xs font-medium transition-colors disabled:opacity-50"
                    >
                      {submitting[req.request_id] ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <ShieldCheck className="w-3 h-3" />
                      )}
                      Approve
                    </button>
                    <button
                      onClick={() => handleRespond(req.request_id, false)}
                      disabled={submitting[req.request_id]}
                      className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-md bg-red-500 hover:bg-red-600 text-white text-xs font-medium transition-colors disabled:opacity-50"
                    >
                      <ShieldX className="w-3 h-3" />
                      Reject
                    </button>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </AnimatePresence>
      </div>

      {/* 历史记录 */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="shrink-0 px-4 py-2 flex items-center justify-between border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950">
          <div className="flex gap-1">
            {(["all", "approved", "rejected", "pending", "expired"] as HistoryFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cn(
                  "px-2 py-0.5 rounded text-[10px] font-medium capitalize transition-colors",
                  filter === f
                    ? "bg-indigo-500 text-white"
                    : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                )}
              >
                {f}
              </button>
            ))}
          </div>
          <button
            onClick={fetchHistory}
            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar">
          {historyLoading ? (
            <div className="flex items-center justify-center h-24">
              <Loader2 className="w-4 h-4 text-indigo-500 animate-spin" />
            </div>
          ) : history.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-24 text-slate-400 gap-2">
              <ShieldCheck className="w-6 h-6 opacity-20" />
              <span className="text-xs">No records</span>
            </div>
          ) : (
            <div className="px-3 py-2 space-y-1">
              {history.map((r) => {
                const cfg = STATUS_CONFIG[r.status] ?? STATUS_CONFIG.pending;
                const Icon = cfg.icon;
                const date = r.created_at ? new Date(r.created_at) : null;
                return (
                  <div
                    key={r.request_id}
                    className="flex items-start gap-2.5 px-2 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800/50 transition-colors"
                  >
                    <Icon className={cn("w-3.5 h-3.5 shrink-0 mt-0.5", cfg.color)} />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-slate-700 dark:text-slate-300 leading-snug truncate">
                        {r.message}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] font-mono text-slate-400 truncate">{r.operation}</span>
                        {date && (
                          <span className="text-[10px] text-slate-400 shrink-0">
                            {date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}
                            {" "}
                            {date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false })}
                          </span>
                        )}
                      </div>
                      {r.user_comment && (
                        <div className="text-[10px] text-slate-400 italic mt-0.5 truncate">"{r.user_comment}"</div>
                      )}
                    </div>
                    <span className={cn("text-[9px] font-bold uppercase shrink-0 mt-0.5", cfg.color)}>
                      {cfg.label}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
