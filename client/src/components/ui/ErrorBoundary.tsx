'use client';

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * React 错误边界组件
 * 
 * 功能：
 * 1. 捕获子组件树中的 JavaScript 错误
 * 2. 记录错误日志
 * 3. 显示友好的错误提示
 * 4. 提供恢复选项（刷新/返回首页）
 * 
 * 使用：
 * ```tsx
 * <ErrorBoundary>
 *   <YourComponent />
 * </ErrorBoundary>
 * ```
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): State {
    // 更新 state 使下一次渲染能够显示降级后的 UI
    return {
      hasError: true,
      error,
      errorInfo: null,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // 记录错误到日志服务
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    
    // 可以将错误发送到错误追踪服务（如 Sentry）
    // logErrorToService(error, errorInfo);
    
    this.setState({
      error,
      errorInfo,
    });
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  handleRefresh = () => {
    window.location.reload();
  };

  handleGoHome = () => {
    window.location.href = '/';
  };

  render() {
    if (this.state.hasError) {
      // 如果提供了自定义 fallback，使用它
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // 默认错误 UI
      return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-red-50 to-orange-50 dark:from-gray-900 dark:to-gray-800 p-4">
          <div className="max-w-2xl w-full bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-8">
            {/* 错误图标 */}
            <div className="flex justify-center mb-6">
              <div className="w-20 h-20 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center justify-center">
                <AlertTriangle className="w-12 h-12 text-red-600 dark:text-red-400" />
              </div>
            </div>

            {/* 错误标题 */}
            <h1 className="text-3xl font-bold text-center text-gray-900 dark:text-white mb-4">
              哎呀，出错了！
            </h1>

            {/* 错误描述 */}
            <p className="text-center text-gray-600 dark:text-gray-300 mb-6">
              应用遇到了一个意外错误。我们已经记录了这个问题，会尽快修复。
            </p>

            {/* 错误详情（可折叠） */}
            {this.state.error && (
              <details className="mb-6 bg-gray-50 dark:bg-gray-900 rounded-lg p-4">
                <summary className="cursor-pointer text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  查看错误详情
                </summary>
                <div className="mt-2 space-y-2">
                  <div className="text-sm">
                    <span className="font-semibold text-red-600 dark:text-red-400">错误类型：</span>
                    <span className="ml-2 text-gray-700 dark:text-gray-300">
                      {this.state.error.name}
                    </span>
                  </div>
                  <div className="text-sm">
                    <span className="font-semibold text-red-600 dark:text-red-400">错误消息：</span>
                    <pre className="mt-1 p-2 bg-white dark:bg-gray-800 rounded text-xs overflow-x-auto">
                      {this.state.error.message}
                    </pre>
                  </div>
                  {this.state.errorInfo && (
                    <div className="text-sm">
                      <span className="font-semibold text-red-600 dark:text-red-400">组件堆栈：</span>
                      <pre className="mt-1 p-2 bg-white dark:bg-gray-800 rounded text-xs overflow-x-auto max-h-40">
                        {this.state.errorInfo.componentStack}
                      </pre>
                    </div>
                  )}
                </div>
              </details>
            )}

            {/* 操作按钮 */}
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <button
                onClick={this.handleReset}
                className="flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors"
              >
                <RefreshCw className="w-5 h-5" />
                重试
              </button>
              <button
                onClick={this.handleRefresh}
                className="flex items-center justify-center gap-2 px-6 py-3 bg-gray-600 hover:bg-gray-700 text-white rounded-lg font-medium transition-colors"
              >
                <RefreshCw className="w-5 h-5" />
                刷新页面
              </button>
              <button
                onClick={this.handleGoHome}
                className="flex items-center justify-center gap-2 px-6 py-3 bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-900 dark:text-white rounded-lg font-medium transition-colors"
              >
                <Home className="w-5 h-5" />
                返回首页
              </button>
            </div>

            {/* 帮助提示 */}
            <div className="mt-6 text-center text-sm text-gray-500 dark:text-gray-400">
              <p>如果问题持续存在，请尝试：</p>
              <ul className="mt-2 space-y-1">
                <li>• 清除浏览器缓存</li>
                <li>• 使用无痕模式</li>
                <li>• 联系技术支持</li>
              </ul>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

/**
 * 轻量级错误边界（用于小组件）
 */
export function LightErrorBoundary({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary
      fallback={
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
            <AlertTriangle className="w-5 h-5" />
            <span className="font-medium">组件加载失败</span>
          </div>
          <p className="mt-2 text-sm text-red-600 dark:text-red-400">
            该组件遇到错误，请刷新页面重试。
          </p>
        </div>
      }
    >
      {children}
    </ErrorBoundary>
  );
}

