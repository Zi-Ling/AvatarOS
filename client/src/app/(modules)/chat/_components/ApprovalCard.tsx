"use client";

import React, { useState } from "react";
import { ShieldAlert, CheckCircle2, XCircle, Clock, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { getSocket } from "@/lib/socket";
import type { ApprovalRequest, ApprovalStatus } from "@/types/chat";
import { useTaskStore } from "@/stores/taskStore";
import { useChatStore } from "@/stores/chatStore";

interface ApprovalCardProps {
  messageId: string;
  request: ApprovalRequest;
  status: ApprovalStatus;
  comment?: string;
}

export function ApprovalCard({ messageId, request, status, comment }: ApprovalCardProps) {
  const [userComment, setUserComment] = useState("");
  const [showDetails, setShowDetails] = useState(false);

  const isExpired = status === "expired" || new Date(request.expires_at) < new Date();
  const effectiveStatus: ApprovalStatus = isExpired && status === "pending" ? "expired" : status;

  const { removePendingApproval } = useTaskStore();
  const { updateMessage } = useChatStore();

  const submit = async (approved: boolean) => {
    if (effectiveStatus !== "pending") return;

    updateMessage(messageId, { approvalStatus: "submitting" });

    const socket = getSocket();
    socket.emit("approval_response", {
      request_id: request.request_id,
      approved,
      user_comment: userComment || undefined,
    });

    const finalStatus: ApprovalStatus = approved ? "approved" : "rejected";
    updateMessage(messageId, {
      approvalStatus: finalStatus,
      approvalComment: userComment || undefined,
    });
    removePendingApproval(request.request_id);
  };

  const statusConfig = {
    pending: { icon: ShieldAlert, color: "text-amber-500", bg: "bg-amber-50 dark:bg-amber-950/20", border: "border-amber-200 dark:border-amber-800", label: "等待审批" },
    submitting: { icon: Loader2, color: "text-indigo-500", bg: "bg-indigo-50 dark:bg-indigo-950/20", border: "border-indigo-200 dark:border-indigo-800", label: "处理中..." },
    approved: { icon: CheckCircle2, color: "text-green-500", bg: "bg-green-50 dark:bg-green-950/20", border: "border-green-200 dark:border-green-800", label: "已批准" },
    rejected: { icon: XCircle, color: "text-red-500", bg: "bg-red-50 dark:bg-red-950/20", border: "border-red-200 dark:border-red-800", label: "已拒绝" },
    expired: { icon: Clock, color: "text-slate-400", bg: "bg-slate-50 dark:bg-slate-900/50", border: "border-slate-200 dark:border-slate-700", label: "已过期" },
  };

  const cfg = statusConfig[effectiveStatus];
  const Icon = cfg.icon;
  const isPending = effectiveStatus === "pending";
  const isResolved = effectiveStatus === "approved" || effectiveStatus === "rejected" || effectiveStatus === "expired";

  // 已处理：缩小为紧凑行
  if (isResolved) {
    return (
      <div className={cn(
        "flex items-center gap-2 px-2 py-1.5 rounded-lg border text-xs",
        effectiveStatus === "approved"
          ? "border-green-200 dark:border-green-800/40 bg-green-50/50 dark:bg-green-950/10"
          : effectiveStatus === "rejected"
          ? "border-red-200 dark:border-red-800/40 bg-red-50/50 dark:bg-red-950/10"
          : "border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-900/30"
      )}>
        <Icon className={cn("w-3.5 h-3.5 shrink-0", cfg.color)} />
        <span className={cn("font-medium", cfg.color)}>{cfg.label}</span>
        <span className="text-slate-400 truncate flex-1">{request.operation}</span>
        {comment && <span className="text-slate-400 italic truncate max-w-[120px]">{comment}</span>}
        <span className="text-[10px] text-slate-400 font-mono shrink-0">
          {new Date(request.expires_at).toLocaleTimeString()}
        </span>
      </div>
    );
  }

  return (
    <div className={cn("mt-2 rounded-xl border p-3 space-y-2.5", cfg.bg, cfg.border)}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <Icon className={cn("w-4 h-4 shrink-0", cfg.color, effectiveStatus === "submitting" && "animate-spin")} />
        <span className={cn("text-xs font-semibold", cfg.color)}>{cfg.label}</span>
        <span className="ml-auto text-[10px] text-slate-400 font-mono">{request.operation}</span>
      </div>

      {/* Message */}
      <p className="text-sm text-slate-700 dark:text-slate-300">{request.message}</p>

      {/* Details toggle */}
      {request.details && Object.keys(request.details).length > 0 && (
        <button
          onClick={() => setShowDetails(v => !v)}
          className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 underline underline-offset-2"
        >
          {showDetails ? "收起详情" : "查看详情"}
        </button>
      )}
      {showDetails && request.details && (
        <pre className="text-[10px] font-mono bg-black/5 dark:bg-white/5 rounded p-2 overflow-auto max-h-32 text-slate-600 dark:text-slate-400">
          {JSON.stringify(request.details, null, 2)}
        </pre>
      )}

      {/* Comment (resolved) */}
      {!isPending && comment && (
        <p className="text-xs text-slate-500 italic">备注: {comment}</p>
      )}

      {/* Expiry */}
      {isPending && (
        <p className="text-[10px] text-slate-400">
          过期时间: {new Date(request.expires_at).toLocaleTimeString()}
        </p>
      )}

      {/* Actions */}
      {isPending && (
        <div className="space-y-2">
          <textarea
            value={userComment}
            onChange={e => setUserComment(e.target.value)}
            placeholder="备注（可选）"
            rows={2}
            className="w-full text-xs px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 resize-none focus:outline-none focus:ring-1 focus:ring-indigo-400"
          />
          <div className="flex gap-2">
            <button
              onClick={() => submit(false)}
              className="flex-1 py-1.5 text-xs font-medium rounded-lg bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
            >
              拒绝
            </button>
            <button
              onClick={() => submit(true)}
              className="flex-1 py-1.5 text-xs font-medium rounded-lg bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50 transition-colors"
            >
              批准
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
