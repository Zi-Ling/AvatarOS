"use client";

import { useState, useEffect } from "react";
import { getSocket } from "@/lib/socket";

interface ApprovalRequest {
  request_id: string;
  message: string;
  operation: string;
  details?: Record<string, any>;
  created_at: string;
  expires_at: string;
}

interface ApprovalDialogProps {
  onClose?: () => void;
}

export default function ApprovalDialog({ onClose }: ApprovalDialogProps) {
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [currentRequest, setCurrentRequest] = useState<ApprovalRequest | null>(null);
  const [userComment, setUserComment] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);

  useEffect(() => {
    const socket = getSocket();

    // 监听审批请求事件
    const handleApprovalRequest = (data: { payload: ApprovalRequest }) => {
      const request = data.payload;
      setRequests((prev) => [...prev, request]);
      
      // 如果当前没有显示的请求，自动显示新请求
      if (!currentRequest) {
        setCurrentRequest(request);
      }
    };

    socket.on("approval_request", handleApprovalRequest);

    return () => {
      socket.off("approval_request", handleApprovalRequest);
    };
  }, [currentRequest]);

  const handleApprove = async () => {
    if (!currentRequest || isProcessing) return;

    setIsProcessing(true);
    try {
      const socket = getSocket();
      
      // 发送审批响应
      socket.emit("approval_response", {
        request_id: currentRequest.request_id,
        approved: true,
        user_comment: userComment || undefined,
      });

      // 移除当前请求
      setRequests((prev) => prev.filter((r) => r.request_id !== currentRequest.request_id));
      
      // 显示下一个请求或关闭对话框
      const nextRequest = requests.find((r) => r.request_id !== currentRequest.request_id);
      if (nextRequest) {
        setCurrentRequest(nextRequest);
        setUserComment("");
      } else {
        setCurrentRequest(null);
        onClose?.();
      }
    } catch (error) {
      console.error("Failed to approve request:", error);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDeny = async () => {
    if (!currentRequest || isProcessing) return;

    setIsProcessing(true);
    try {
      const socket = getSocket();
      
      // 发送审批响应
      socket.emit("approval_response", {
        request_id: currentRequest.request_id,
        approved: false,
        user_comment: userComment || undefined,
      });

      // 移除当前请求
      setRequests((prev) => prev.filter((r) => r.request_id !== currentRequest.request_id));
      
      // 显示下一个请求或关闭对话框
      const nextRequest = requests.find((r) => r.request_id !== currentRequest.request_id);
      if (nextRequest) {
        setCurrentRequest(nextRequest);
        setUserComment("");
      } else {
        setCurrentRequest(null);
        onClose?.();
      }
    } catch (error) {
      console.error("Failed to deny request:", error);
    } finally {
      setIsProcessing(false);
    }
  };

  // 如果没有待审批请求，不显示对话框
  if (!currentRequest) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
        {/* 标题 */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            ⚠️ 需要审批
          </h2>
          {requests.length > 1 && (
            <span className="text-sm text-gray-500 dark:text-gray-400">
              {requests.indexOf(currentRequest) + 1} / {requests.length}
            </span>
          )}
        </div>

        {/* 审批消息 */}
        <div className="mb-4">
          <p className="text-gray-700 dark:text-gray-300 mb-2">
            {currentRequest.message}
          </p>
          <div className="text-sm text-gray-500 dark:text-gray-400">
            <p>操作类型: <span className="font-mono">{currentRequest.operation}</span></p>
            {currentRequest.details && Object.keys(currentRequest.details).length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer hover:text-gray-700 dark:hover:text-gray-200">
                  查看详情
                </summary>
                <pre className="mt-2 p-2 bg-gray-100 dark:bg-gray-700 rounded text-xs overflow-auto">
                  {JSON.stringify(currentRequest.details, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </div>

        {/* 用户评论 */}
        <div className="mb-4">
          <label
            htmlFor="user-comment"
            className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
          >
            备注（可选）
          </label>
          <textarea
            id="user-comment"
            value={userComment}
            onChange={(e) => setUserComment(e.target.value)}
            placeholder="添加审批备注..."
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md 
                     bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100
                     focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
            disabled={isProcessing}
          />
        </div>

        {/* 操作按钮 */}
        <div className="flex gap-3">
          <button
            onClick={handleDeny}
            disabled={isProcessing}
            className="flex-1 px-4 py-2 bg-red-500 hover:bg-red-600 disabled:bg-red-300 
                     text-white rounded-md transition-colors"
          >
            {isProcessing ? "处理中..." : "拒绝"}
          </button>
          <button
            onClick={handleApprove}
            disabled={isProcessing}
            className="flex-1 px-4 py-2 bg-green-500 hover:bg-green-600 disabled:bg-green-300 
                     text-white rounded-md transition-colors"
          >
            {isProcessing ? "处理中..." : "批准"}
          </button>
        </div>

        {/* 过期时间提示 */}
        <div className="mt-3 text-xs text-gray-500 dark:text-gray-400 text-center">
          请求将在 {new Date(currentRequest.expires_at).toLocaleTimeString()} 过期
        </div>
      </div>
    </div>
  );
}
