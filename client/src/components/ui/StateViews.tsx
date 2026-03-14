"use client";

import { Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * 统一的 loading 状态视图
 * size: "sm" = h-24, "md" = h-40 (default), "lg" = h-full
 */
export function LoadingSpinner({
  text = "加载中...",
  size = "md",
  className,
}: {
  text?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const heightCls = size === "sm" ? "h-24" : size === "lg" ? "h-full" : "h-40";
  return (
    <div className={cn("flex items-center justify-center gap-2 text-slate-400", heightCls, className)}>
      <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
      <span className="text-sm">{text}</span>
    </div>
  );
}

/**
 * 统一的 error 状态视图
 */
export function ErrorState({
  message,
  onRetry,
  size = "md",
  className,
}: {
  message?: string;
  onRetry?: () => void;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const heightCls = size === "sm" ? "h-24" : size === "lg" ? "h-full" : "h-40";
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 text-slate-400", heightCls, className)}>
      <AlertCircle className="w-8 h-8 text-red-400 opacity-70" />
      <p className="text-sm text-slate-500 dark:text-slate-400 text-center max-w-xs">
        {message ?? "加载失败"}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          重试
        </button>
      )}
    </div>
  );
}

/**
 * 统一的 empty 状态视图
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  size = "md",
  className,
}: {
  icon?: React.ElementType;
  title: string;
  description?: string;
  action?: React.ReactNode;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const heightCls = size === "sm" ? "h-24" : size === "lg" ? "h-full" : "h-40";
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 text-slate-400", heightCls, className)}>
      {Icon && (
        <div className="w-12 h-12 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-1">
          <Icon className="w-6 h-6 opacity-30" />
        </div>
      )}
      <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{title}</p>
      {description && <p className="text-xs text-slate-400 text-center max-w-xs">{description}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
