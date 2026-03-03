"use client";

import React, { createContext, useContext, useEffect, useState, useRef } from "react";
import { Socket } from "socket.io-client";
import { getSocket } from "@/lib/socket";

interface SocketContextType {
  socket: Socket | null;
  isConnected: boolean;
  reconnectAttempts: number;
  syncTaskStatus: (taskId: string) => Promise<void>;
}

const SocketContext = createContext<SocketContextType>({
  socket: null,
  isConnected: false,
  reconnectAttempts: 0,
  syncTaskStatus: async () => {},
});

export const useSocket = () => useContext(SocketContext);

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const SocketProvider = ({ children }: { children: React.ReactNode }) => {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const activeTasksRef = useRef<Set<string>>(new Set());
  const lastEventTimeRef = useRef<number>(0);
  const sessionIdRef = useRef<string>("");

  // 同步任务状态（用于重连后恢复）
  const syncTaskStatus = async (taskId: string) => {
    try {
      console.log(`[SocketProvider] Syncing task status for: ${taskId}`);
      const response = await fetch(`${API_BASE}/tasks/${taskId}/status`);
      
      if (!response.ok) {
        console.error(`[SocketProvider] Failed to sync task ${taskId}: ${response.status}`);
        return;
      }
      
      const status = await response.json();
      console.log(`[SocketProvider] Task ${taskId} status:`, status);
      
      window.dispatchEvent(new CustomEvent('task-status-synced', {
        detail: { taskId, status }
      }));
      
      if (status.status === 'completed' || status.status === 'failed') {
        activeTasksRef.current.delete(taskId);
      }
    } catch (error) {
      console.error(`[SocketProvider] Error syncing task ${taskId}:`, error);
    }
  };

  useEffect(() => {
    const socketInstance = getSocket();

    // ---- 连接/断开事件 ----
    // 底层重连由 Socket.IO 内置机制处理（指数退避，最多 10 次，最大 30s）
    // 这里只做业务层恢复

    function onConnect() {
      console.log("✅ Socket Connected:", socketInstance.id);
      setIsConnected(true);
      setReconnectAttempts(0);
      
      // 恢复 session_id
      if (!sessionIdRef.current) {
        const storedSessionId = localStorage.getItem('chat_session_id');
        if (storedSessionId) {
          sessionIdRef.current = storedSessionId;
        }
      }
      
      // 重连后请求错过的事件
      if (lastEventTimeRef.current > 0 && sessionIdRef.current) {
        console.log(`[SocketProvider] Requesting missed events since ${new Date(lastEventTimeRef.current * 1000).toISOString()}...`);
        socketInstance.emit('request_missed_events', {
          session_id: sessionIdRef.current,
          last_event_time: lastEventTimeRef.current
        });
      }
      
      // 重连后同步所有活跃任务状态
      if (activeTasksRef.current.size > 0) {
        console.log(`[SocketProvider] Reconnected! Syncing ${activeTasksRef.current.size} active tasks...`);
        activeTasksRef.current.forEach(taskId => {
          syncTaskStatus(taskId);
        });
      }
    }

    function onDisconnect(reason: string) {
      console.log("❌ Socket Disconnected:", reason);
      setIsConnected(false);
    }

    function onConnectError(error: Error) {
      console.error("❌ Socket Connection Error:", error);
      setIsConnected(false);
    }

    // Socket.IO 内置重连事件 — 仅用于 UI 展示重连次数
    function onReconnectAttempt(attempt: number) {
      console.log(`[SocketProvider] Reconnect attempt ${attempt}...`);
      setReconnectAttempts(attempt);
    }

    function onReconnectFailed() {
      console.error("[SocketProvider] All reconnect attempts failed.");
    }

    // ---- 业务事件 ----

    socketInstance.on("connect", onConnect);
    socketInstance.on("disconnect", onDisconnect);
    socketInstance.on("connect_error", onConnectError);

    // Socket.IO Manager 级别的重连事件
    socketInstance.io.on("reconnect_attempt", onReconnectAttempt);
    socketInstance.io.on("reconnect_failed", onReconnectFailed);

    socketInstance.on("task_started", (data: any) => {
      if (data.task_id) {
        activeTasksRef.current.add(data.task_id);
        console.log(`[SocketProvider] Task started: ${data.task_id}`);
      }
    });

    socketInstance.on("task_completed", (data: any) => {
      if (data.task_id) {
        activeTasksRef.current.delete(data.task_id);
        console.log(`[SocketProvider] Task completed: ${data.task_id}`);
      }
    });

    socketInstance.on("task_failed", (data: any) => {
      if (data.task_id) {
        activeTasksRef.current.delete(data.task_id);
        console.log(`[SocketProvider] Task failed: ${data.task_id}`);
      }
    });

    socketInstance.on("server_event", (data: any) => {
      lastEventTimeRef.current = Date.now() / 1000;
      if (data.type === 'task.completed' || data.type === 'plan.generated') {
        console.log(`[SocketProvider] Received important event: ${data.type}`);
      }
    });

    socketInstance.connect();
    setSocket(socketInstance);

    return () => {
      socketInstance.off("connect", onConnect);
      socketInstance.off("disconnect", onDisconnect);
      socketInstance.off("connect_error", onConnectError);
      socketInstance.io.off("reconnect_attempt", onReconnectAttempt);
      socketInstance.io.off("reconnect_failed", onReconnectFailed);
      socketInstance.off("task_started");
      socketInstance.off("task_completed");
      socketInstance.off("task_failed");
      socketInstance.off("server_event");
      socketInstance.disconnect();
    };
  }, []);

  return (
    <SocketContext.Provider value={{ socket, isConnected, reconnectAttempts, syncTaskStatus }}>
      {children}
    </SocketContext.Provider>
  );
};
