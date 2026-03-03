import React from 'react';
import { AlertCircle, AlertTriangle, Info, XCircle } from 'lucide-react';

interface ErrorDetails {
  error_type: string;
  severity: 'critical' | 'error' | 'warning' | 'info';
  message: string;
  suggestions: string[];
  retry_possible: boolean;
  technical_details?: string;
}

interface ErrorDisplayProps {
  error: string | ErrorDetails;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export function ErrorDisplay({ error, onRetry, onDismiss }: ErrorDisplayProps) {
  // 如果是简单字符串，转换为 ErrorDetails
  const errorDetails: ErrorDetails = typeof error === 'string' 
    ? {
        error_type: 'unknown_error',
        severity: 'error',
        message: error,
        suggestions: ['请尝试重新执行'],
        retry_possible: true,
      }
    : error;

  const severityConfig = {
    critical: {
      icon: XCircle,
      bgColor: 'bg-red-50 dark:bg-red-900/20',
      borderColor: 'border-red-200 dark:border-red-800',
      iconColor: 'text-red-500',
      textColor: 'text-red-800 dark:text-red-200',
    },
    error: {
      icon: AlertCircle,
      bgColor: 'bg-orange-50 dark:bg-orange-900/20',
      borderColor: 'border-orange-200 dark:border-orange-800',
      iconColor: 'text-orange-500',
      textColor: 'text-orange-800 dark:text-orange-200',
    },
    warning: {
      icon: AlertTriangle,
      bgColor: 'bg-yellow-50 dark:bg-yellow-900/20',
      borderColor: 'border-yellow-200 dark:border-yellow-800',
      iconColor: 'text-yellow-500',
      textColor: 'text-yellow-800 dark:text-yellow-200',
    },
    info: {
      icon: Info,
      bgColor: 'bg-blue-50 dark:bg-blue-900/20',
      borderColor: 'border-blue-200 dark:border-blue-800',
      iconColor: 'text-blue-500',
      textColor: 'text-blue-800 dark:text-blue-200',
    },
  };

  const config = severityConfig[errorDetails.severity];
  const Icon = config.icon;

  return (
    <div className={`rounded-lg border p-4 ${config.bgColor} ${config.borderColor}`}>
      <div className="flex items-start gap-3">
        <Icon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${config.iconColor}`} />
        <div className="flex-1 min-w-0">
          <h4 className={`font-semibold mb-2 ${config.textColor}`}>
            {errorDetails.message}
          </h4>
          
          {errorDetails.suggestions && errorDetails.suggestions.length > 0 && (
            <div className="mb-3">
              <p className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-1">
                建议：
              </p>
              <ul className="text-sm text-slate-600 dark:text-slate-400 space-y-1">
                {errorDetails.suggestions.map((suggestion, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-slate-400">•</span>
                    <span>{suggestion}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          
          {errorDetails.technical_details && (
            <details className="mt-3">
              <summary className="text-xs text-slate-500 dark:text-slate-500 cursor-pointer hover:text-slate-700 dark:hover:text-slate-300">
                技术详情
              </summary>
              <pre className="mt-2 text-xs bg-slate-900 dark:bg-slate-950 text-slate-300 p-3 rounded overflow-x-auto">
                {errorDetails.technical_details}
              </pre>
            </details>
          )}
          
          <div className="flex gap-2 mt-4">
            {errorDetails.retry_possible && onRetry && (
              <button
                onClick={onRetry}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-lg transition-colors"
              >
                重试
              </button>
            )}
            {onDismiss && (
              <button
                onClick={onDismiss}
                className="px-4 py-2 bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-300 text-sm rounded-lg transition-colors"
              >
                关闭
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

