"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { ChatInput } from "./_components/ChatInput";
import { MessageList } from "./_components/MessageList";
import { VoiceRecording } from "./_components/VoiceRecording";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { GatePrompt } from "@/components/ui/GatePrompt";
import { useLanguage } from "@/theme/i18n/LanguageContext";
import { useChatStore } from "@/stores/chatStore";
import { useChat } from "@/lib/hooks/useChat";
import { useTaskStore } from "@/stores/taskStore";

export default function ChatInterface() {
  const { language } = useLanguage();

  const {
    messages,
    inputValue,
    isTyping,
    isThinkEnabled,
    attachments,
    storedSessionId,
    canCancel,
    activeTask,
    setInputValue,
    toggleThinkMode,
    updateMessage,
    removeAttachment,
    addAttachment,
    handleSend,
    handleStopGeneration,
    handleNewChatConfirm,
    handleKeyPress,
    initSession,
  } = useChat();

  // Initialize session on mount
  useEffect(() => {
    initSession();
  }, [initSession]);

  const [showNewChatDialog, setShowNewChatDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [messageToDelete, setMessageToDelete] = useState<string | null>(null);

  const { pendingApprovals } = useTaskStore();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const { isRecording, isTranscribing, audioLevel, toggleRecording } = VoiceRecording();

  const handleToggleRecording = useCallback(async () => {
    const recognizedText = await toggleRecording();
    if (recognizedText) {
      setInputValue(recognizedText);
    }
  }, [toggleRecording, setInputValue]);

  const handleNewChatClick = useCallback(() => {
    setShowNewChatDialog(true);
  }, []);

  const handleFileUpload = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;

      Array.from(files).forEach((file) => {
        const blobUrl = URL.createObjectURL(file);
        addAttachment({
          id: `${Date.now()}-${Math.random()}`,
          name: file.name,
          size: file.size,
          type: file.type,
          url: blobUrl,
          file,
        });
      });

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    },
    [addAttachment]
  );

  // Revoke blob URLs on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      attachments.forEach((att) => {
        if (att.url?.startsWith("blob:")) {
          URL.revokeObjectURL(att.url);
        }
      });
    };
  }, []);

  const formatFileSize = useCallback((bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
  }, []);

  const handleDeleteMessage = useCallback((id: string) => {
    setMessageToDelete(id);
    setShowDeleteDialog(true);
  }, []);

  const confirmDeleteMessage = useCallback(() => {
    if (messageToDelete) {
      useChatStore.getState().deleteMessage(messageToDelete);
      setMessageToDelete(null);
    }
  }, [messageToDelete]);

  const handleLikeMessage = useCallback(
    (id: string) => {
      const msg = messages.find((m) => m.id === id);
      if (msg) {
        updateMessage(id, { liked: !msg.liked, disliked: false });
      }
    },
    [messages, updateMessage]
  );

  const handleDislikeMessage = useCallback(
    (id: string) => {
      const msg = messages.find((m) => m.id === id);
      if (msg) {
        updateMessage(id, { disliked: !msg.disliked, liked: false });
      }
    },
    [messages, updateMessage]
  );

  const handleRegenerateMessage = useCallback(
    (id: string) => {
      const messageIndex = messages.findIndex((msg) => msg.id === id);
      if (messageIndex === -1) return;
      const previousMessages = messages.slice(0, messageIndex);
      const lastUserMessage = [...previousMessages].reverse().find((msg) => msg.role === "user");
      if (!lastUserMessage) return;

      // Remove the AI message being regenerated
      useChatStore.getState().deleteMessage(id);

      // Pass content directly to handleSend to avoid async state issue
      handleSend(lastUserMessage.content);
    },
    [messages, handleSend]
  );

  return (
    <div className="flex h-full flex-col bg-white dark:bg-transparent transition-colors">
      <MessageList
        messages={messages}
        isTyping={isTyping}
        onRegenerate={handleRegenerateMessage}
        onLike={handleLikeMessage}
        onDislike={handleDislikeMessage}
        onDelete={handleDeleteMessage}
        formatFileSize={formatFileSize}
      />

      <GatePrompt />

      <ChatInput
        inputValue={inputValue}
        setInputValue={setInputValue}
        attachments={attachments}
        isRecording={isRecording}
        isTyping={isTyping}
        isThinkEnabled={isThinkEnabled}
        toggleThinkMode={toggleThinkMode}
        fileInputRef={fileInputRef}
        handleSend={handleSend}
        handleKeyPress={handleKeyPress}
        handleFileUpload={handleFileUpload}
        removeAttachment={removeAttachment}
        handleNewChat={handleNewChatClick}
        handleStopGeneration={handleStopGeneration}
        toggleRecording={handleToggleRecording}
        isTranscribing={isTranscribing}
        audioLevel={audioLevel}
        formatFileSize={formatFileSize}
        canCancel={canCancel}
        hasActiveTask={!!activeTask && activeTask.status === "executing"}
        pendingApprovalCount={pendingApprovals.length}
      />

      <ConfirmDialog
        isOpen={showNewChatDialog}
        onClose={() => setShowNewChatDialog(false)}
        onConfirm={() => {
          handleNewChatConfirm();
          setShowNewChatDialog(false);
        }}
        title={language === "zh" ? "开始新对话" : "Start New Chat"}
        message={
          language === "zh"
            ? "确定要开始新对话吗？当前对话内容将被清除。"
            : "Start a new chat? Current conversation will be cleared."
        }
        confirmText={language === "zh" ? "确认" : "Confirm"}
        cancelText={language === "zh" ? "取消" : "Cancel"}
        variant="warning"
      />

      <ConfirmDialog
        isOpen={showDeleteDialog}
        onClose={() => setShowDeleteDialog(false)}
        onConfirm={confirmDeleteMessage}
        title={language === "zh" ? "删除消息" : "Delete Message"}
        message={
          language === "zh"
            ? "确定要删除这条消息吗？"
            : "Are you sure you want to delete this message?"
        }
        confirmText={language === "zh" ? "删除" : "Delete"}
        cancelText={language === "zh" ? "取消" : "Cancel"}
        variant="danger"
      />
    </div>
  );
}
