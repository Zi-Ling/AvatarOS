import React from 'react';
import { Wifi, WifiOff, RefreshCw } from 'lucide-react';
import { useSocket } from '@/components/providers/SocketProvider';

export function ConnectionStatus() {
  const { isConnected, reconnectAttempts } = useSocket();

  // 如果已连接，不显示任何提示
  if (isConnected && reconnectAttempts === 0) {
    return null;
  }

  // 如果正在重连
  if (!isConnected && reconnectAttempts > 0) {
    return (
      <div className="fixed top-4 right-4 z-[9999] bg-yellow-500 text-white px-4 py-2 rounded-lg shadow-lg flex items-center gap-2 animate-pulse">
        <RefreshCw className="w-4 h-4 animate-spin" />
        <span className="text-sm font-medium">
          正在重连... (尝试 {reconnectAttempts}/10)
        </span>
      </div>
    );
  }

  // 如果断开连接
  if (!isConnected) {
    return (
      <div className="fixed top-4 right-4 z-[9999] bg-red-500 text-white px-4 py-2 rounded-lg shadow-lg flex items-center gap-2">
        <WifiOff className="w-4 h-4" />
        <span className="text-sm font-medium">连接已断开</span>
      </div>
    );
  }

  return null;
}

