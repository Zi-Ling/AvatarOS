import React from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'danger' | 'warning' | 'info';
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmText = '确认',
  cancelText = '取消',
  variant = 'warning',
}: ConfirmDialogProps) {
  if (!isOpen) return null;

  const handleConfirm = () => {
    onConfirm();
    onClose();
  };

  const variantStyles = {
    danger: {
      icon: 'text-red-500',
      button: 'bg-red-500 hover:bg-red-600 text-white',
    },
    warning: {
      icon: 'text-yellow-500',
      button: 'bg-yellow-500 hover:bg-yellow-600 text-white',
    },
    info: {
      icon: 'text-blue-500',
      button: 'bg-blue-500 hover:bg-blue-600 text-white',
    },
  };

  const styles = variantStyles[variant];

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center">
      {/* 背景遮罩 */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* 对话框 */}
      <div className="relative bg-white dark:bg-slate-900 rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden border border-slate-200 dark:border-slate-800">
        {/* 关闭按钮 */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* 内容 */}
        <div className="p-6">
          {/* 图标和标题 */}
          <div className="flex items-start gap-4 mb-4">
            <div className={cn("flex-shrink-0 w-12 h-12 rounded-full flex items-center justify-center", 
              variant === 'danger' ? 'bg-red-100 dark:bg-red-900/30' : 
              variant === 'warning' ? 'bg-yellow-100 dark:bg-yellow-900/30' : 
              'bg-blue-100 dark:bg-blue-900/30'
            )}>
              <AlertTriangle className={cn("w-6 h-6", styles.icon)} />
            </div>
            <div className="flex-1 pt-1">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
                {title}
              </h3>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {message}
              </p>
            </div>
          </div>

          {/* 按钮 */}
          <div className="flex gap-3 mt-6">
            <button
              onClick={onClose}
              className="flex-1 px-4 py-2.5 rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors font-medium"
            >
              {cancelText}
            </button>
            <button
              onClick={handleConfirm}
              className={cn(
                "flex-1 px-4 py-2.5 rounded-lg transition-colors font-medium shadow-sm",
                styles.button
              )}
            >
              {confirmText}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

