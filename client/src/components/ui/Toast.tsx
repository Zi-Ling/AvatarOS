"use client";

import { useEffect, useState } from 'react';
import { CheckCircle2, XCircle, AlertCircle, Info, X } from 'lucide-react';
import { cn } from '@/lib/utils';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number;
}

interface ToastProps {
  toast: ToastMessage;
  onClose: (id: string) => void;
}

function Toast({ toast, onClose }: ToastProps) {
  useEffect(() => {
    const duration = toast.duration || 3000;
    const timer = setTimeout(() => {
      onClose(toast.id);
    }, duration);

    return () => clearTimeout(timer);
  }, [toast, onClose]);

  const icons = {
    success: <CheckCircle2 className="w-5 h-5 text-emerald-500" />,
    error: <XCircle className="w-5 h-5 text-red-500" />,
    warning: <AlertCircle className="w-5 h-5 text-amber-500" />,
    info: <Info className="w-5 h-5 text-blue-500" />,
  };

  const colors = {
    success: 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-500/30',
    error: 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-500/30',
    warning: 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-500/30',
    info: 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-500/30',
  };

  return (
    <div
      className={cn(
        "flex items-start gap-3 p-4 rounded-xl border shadow-lg animate-in slide-in-from-top-5 fade-in duration-300",
        colors[toast.type]
      )}
    >
      <div className="shrink-0 mt-0.5">{icons[toast.type]}</div>
      <div className="flex-1 min-w-0">
        <h4 className="text-sm font-semibold text-slate-900 dark:text-white">
          {toast.title}
        </h4>
        {toast.message && (
          <p className="text-xs text-slate-600 dark:text-slate-300 mt-1">
            {toast.message}
          </p>
        )}
      </div>
      <button
        onClick={() => onClose(toast.id)}
        className="shrink-0 p-1 hover:bg-black/5 dark:hover:bg-white/10 rounded-lg transition-colors"
      >
        <X className="w-4 h-4 text-slate-400" />
      </button>
    </div>
  );
}

export function ToastContainer({ toasts, onClose }: { toasts: ToastMessage[]; onClose: (id: string) => void }) {
  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onClose={onClose} />
      ))}
    </div>
  );
}

