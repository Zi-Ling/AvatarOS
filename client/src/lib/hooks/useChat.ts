"use client";

import { useRef, useCallback } from "react";
import { sendChatMessage, parseSSELine } from "@/lib/api/chat";
import { cancelTask as cancelTaskApi } from "@/lib/api/task";
import { useChatStore, Message } from "@/stores/chatStore";
import { useTaskStore } from "@/stores/taskStore";
import { SessionManager } from "@/lib/session";
import { useSocket } from "@/components/providers/SocketProvider";
import { useLanguage } from "@/theme/i18n/LanguageContext";

// 辅助函数：将 File 转换为 Base64
const fileToBase64 = (file: File): Promise<string> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const base64 = result.split(",")[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
};

export function useChat() {
  const { t, language } = useLanguage();
  const { socket } = useSocket();

  const {
    messages,
    inputValue,
    isTyping,
    isThinkEnabled,
    attachments,
    sessionId: storedSessionId,
    canCancel,
    setInputValue,
    setIsTyping,
    toggleThinkMode,
    addMessage,
    updateMessage,
    setCurrentTaskMessageId,
    setSessionId,
    setCanCancel,
    clearChat,
    addAttachment,
    removeAttachment,
  } = useChatStore();

  const { activeTask, setIsCancelling } = useTaskStore();

  const abortControllerRef = useRef<AbortController | null>(null);

  // Initialize or restore session ID
  const initSession = useCallback(() => {
    if (!storedSessionId) {
      const newSessionId = SessionManager.getSessionId();
      setSessionId(newSessionId);
    }
  }, [storedSessionId, setSessionId]);

  const handleSend = useCallback(async (overrideInput?: string) => {
    const sendInput = overrideInput ?? inputValue;
    if (!sendInput.trim() && attachments.length === 0) return;

    const currentSessionId = storedSessionId || SessionManager.getSessionId();
    if (!storedSessionId) {
      setSessionId(currentSessionId);
    }

    const userInput = sendInput;
    const userAttachments = [...attachments];

    // 使用 crypto.randomUUID 避免 Date.now() 毫秒级碰撞
    const userMessageId = typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

    const userMessage: Message = {
      id: userMessageId,
      role: "user",
      content: userInput,
      timestamp: new Date().toISOString(),
      attachments: userAttachments.length > 0 ? userAttachments : undefined,
    };

    addMessage(userMessage);
    setInputValue("");
    useChatStore.getState().setAttachments([]);

    // 只重置 UI 控制状态，不清除 activeTask — 避免破坏正在运行的任务的 UI
    useTaskStore.getState().setControlStatus("running");
    useTaskStore.getState().setAutoSwitchedForTask(null);

    setIsTyping(true);
    setCanCancel(true);

    const aiMessageId = typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    setCurrentTaskMessageId(aiMessageId);

    try {
      abortControllerRef.current = new AbortController();

      const imageAttachments = [];
      for (const att of userAttachments) {
        if (att.type.startsWith("image/") && att.file) {
          try {
            const base64 = await fileToBase64(att.file);
            imageAttachments.push({
              name: att.name,
              data: base64,
              mime_type: att.type,
            });
          } catch (err) {
            console.error("Failed to convert image to base64:", err);
          }
        }
      }

      const { reader, decoder } = await sendChatMessage(
        userInput,
        currentSessionId,
        isThinkEnabled,
        imageAttachments,
        abortControllerRef.current.signal
      );

      let accumulatedContent = "";
      let isFirstChunk = true;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        if (isFirstChunk) {
          isFirstChunk = false;
          const currentMessages = useChatStore.getState().messages;
          const hasTaskMsg = currentMessages.find((msg) => msg.id === aiMessageId);
          if (!hasTaskMsg) {
            setIsTyping(false);
            addMessage({
              id: aiMessageId,
              role: "assistant",
              content: "",
              timestamp: new Date().toISOString(),
              isStreaming: true,
            });
          }
        }

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n").filter((line) => line.trim() !== "");

        for (const line of lines) {
          const data = parseSSELine(line);
          if (data && data.content) {
            accumulatedContent += data.content;
            updateMessage(aiMessageId, { content: accumulatedContent });
          }
          if (data && data.done) {
            // Unified pipeline: SSE stream always ends with empty/minimal content.
            // Keep isStreaming=true and isTyping=true so the typing indicator
            // stays visible while waiting for socket events:
            //   - plan.generated → upgrades to execution block UI (task mode)
            //   - chat.direct_reply → replaces with chat message (Planner FINISH)
            const isTaskMode = accumulatedContent.trim() === "";
            if (isTaskMode) {
              updateMessage(aiMessageId, {
                messageType: "task_progress",
                content: "",
                isStreaming: true,
              });
              // Don't reset isTyping — keep the typing indicator visible
            } else {
              updateMessage(aiMessageId, { isStreaming: false });
              setCurrentTaskMessageId(null);
            }
          }
        }
      }

      // Stream finished normally
      // For task mode (empty content → waiting for socket events), keep isTyping
      // so the typing indicator stays visible until plan.generated or
      // chat.direct_reply arrives.
      const finalMsg = useChatStore.getState().messages.find((m: any) => m.id === aiMessageId);
      const isWaitingForTask = finalMsg?.messageType === "task_progress";
      if (!isWaitingForTask) {
        setIsTyping(false);
      }
      setCanCancel(false);
    } catch (error: any) {
      console.error("Chat API error:", error);
      setCurrentTaskMessageId(null);
      setCanCancel(false);

      if (error.name === "AbortError") {
        const currentMessages = useChatStore.getState().messages;
        const lastMsg = currentMessages[currentMessages.length - 1];
        if (lastMsg && lastMsg.isStreaming) {
          updateMessage(lastMsg.id, {
            content: lastMsg.content + "\n\n_[已停止]_",
            isStreaming: false,
          });
        }
        return;
      }

      const errorMessage =
        language === "zh"
          ? "抱歉，我遇到了一些问题。请确保后端服务正在运行。\n\n错误信息：" + error.message
          : "Sorry, I encountered an issue. Please ensure the backend service is running.\n\nError: " + error.message;

      const currentMessages = useChatStore.getState().messages;
      const exists = currentMessages.find((m) => m.id === aiMessageId);
      if (exists) {
        updateMessage(aiMessageId, { content: errorMessage, isStreaming: false });
      } else {
        const fallbackId = typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        addMessage({
          id: fallbackId,
          role: "assistant",
          content: errorMessage,
          timestamp: new Date().toISOString(),
          isStreaming: false,
        });
      }
    }
  }, [inputValue, attachments, storedSessionId, isThinkEnabled, language, addMessage, updateMessage, setInputValue, setIsTyping, setCanCancel, setCurrentTaskMessageId, setSessionId]);

  const handleStopGeneration = useCallback(() => {
    // 1. 取消 HTTP 流式请求
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsTyping(false);
      const currentMessages = useChatStore.getState().messages;
      currentMessages.forEach((msg) => {
        if (msg.isStreaming) {
          updateMessage(msg.id, { isStreaming: false });
        }
      });
    }

    // 2. 取消后台任务 — 统一走 REST API（单一控制通道），Socket 只负责广播状态变化
    if (activeTask && storedSessionId) {
      setIsCancelling(true);
      cancelTaskApi(activeTask.id).catch((e) => {
        console.error("cancel failed via REST:", e);
        // Fallback: try socket if REST fails
        if (socket) {
          socket.emit("cancel_task", {
            session_id: storedSessionId,
            task_id: activeTask.id,
          });
        }
      });
    }

    // 3. 更新状态
    setCanCancel(false);
    setCurrentTaskMessageId(null);
  }, [activeTask, storedSessionId, socket, setIsTyping, updateMessage, setIsCancelling, setCanCancel, setCurrentTaskMessageId]);

  const handleNewChatConfirm = useCallback(() => {
    clearChat();
    useTaskStore.getState().clearLogs();
    useTaskStore.getState().resetTask();
    const newSessionId = SessionManager.resetSession();
    setSessionId(newSessionId);

    addMessage({
      id: "1",
      role: "assistant",
      content:
        language === "zh"
          ? "新对话已开始，有什么需要执行的任务？"
          : "New session started. What would you like to do?",
      timestamp: new Date().toISOString(),
    });
  }, [language, clearChat, setSessionId, addMessage]);

  const handleKeyPress = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  return {
    // State
    messages,
    inputValue,
    isTyping,
    isThinkEnabled,
    attachments,
    storedSessionId,
    canCancel,
    activeTask,
    // Actions
    setInputValue,
    toggleThinkMode,
    addMessage,
    updateMessage,
    addAttachment,
    removeAttachment,
    handleSend,
    handleStopGeneration,
    handleNewChatConfirm,
    handleKeyPress,
    initSession,
  };
}
