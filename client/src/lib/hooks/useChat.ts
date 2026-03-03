"use client";

import { useRef, useCallback } from "react";
import { sendChatMessage, parseSSELine } from "@/lib/api/chat";
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

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() && attachments.length === 0) return;

    const currentSessionId = storedSessionId || SessionManager.getSessionId();
    if (!storedSessionId) {
      setSessionId(currentSessionId);
    }

    const userInput = inputValue;
    const userAttachments = [...attachments];

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: userInput,
      timestamp: new Date().toISOString(),
      attachments: userAttachments.length > 0 ? userAttachments : undefined,
    };

    addMessage(userMessage);
    setInputValue("");
    useChatStore.getState().setAttachments([]);
    useTaskStore.getState().resetTask();

    setIsTyping(true);
    setCanCancel(true);

    const aiMessageId = (Date.now() + 1).toString();
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
            const isTaskPlanning =
              accumulatedContent.includes("正在为您规划任务") ||
              accumulatedContent.includes("Planning task");
            if (isTaskPlanning) {
              console.log("Async Task started: Keeping message in streaming state.");
            } else {
              updateMessage(aiMessageId, { isStreaming: false });
              setCurrentTaskMessageId(null);
            }
          }
        }
      }
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
        addMessage({
          id: (Date.now() + 1).toString(),
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

    // 2. 取消活跃任务
    if (activeTask && storedSessionId && socket) {
      setIsCancelling(true);
      socket.emit("cancel_task", {
        session_id: storedSessionId,
        task_id: activeTask.id,
      });
      addMessage({
        id: `cancel-${Date.now()}`,
        role: "assistant",
        content: language === "zh" ? "⏸️ 正在停止任务..." : "⏸️ Stopping task...",
        timestamp: new Date().toISOString(),
      });
    }

    // 3. 更新状态
    setCanCancel(false);
    setCurrentTaskMessageId(null);
  }, [activeTask, storedSessionId, socket, language, setIsTyping, updateMessage, setIsCancelling, addMessage, setCanCancel, setCurrentTaskMessageId]);

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
          ? "你好！我是 IntelliAvatar 智能助手 🤖\n\n我可以和你聊天，回答问题，或者帮助你完成各种任务。\n\n有什么我可以帮助你的吗？"
          : "Hello! I'm IntelliAvatar AI Assistant 🤖\n\nI can chat with you, answer questions, or help you complete tasks.\n\nHow can I help you today?",
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
