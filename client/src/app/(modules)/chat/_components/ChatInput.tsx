"use client";

import { RefObject, useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { useLanguage } from "@/theme/i18n/LanguageContext";
import { cn } from "@/lib/utils";

type Attachment = {
  id: string;
  name: string;
  size: number;
  type: string;
  url?: string;
  file?: File;
};

interface ChatInputProps {
  inputValue: string;
  setInputValue: (value: string) => void;
  attachments: Attachment[];
  isRecording: boolean;
  isTranscribing?: boolean;
  isTyping: boolean;
  audioLevel?: number;
  isThinkEnabled: boolean;
  toggleThinkMode: () => void;
  fileInputRef: RefObject<HTMLInputElement | null>;
  handleSend: () => void;
  handleKeyPress: (e: React.KeyboardEvent) => void;
  handleFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  removeAttachment: (id: string) => void;
  handleNewChat: () => void;
  handleStopGeneration: () => void;
  toggleRecording: () => void;
  formatFileSize: (bytes: number) => string;
  canCancel?: boolean; // 是否可以取消当前操作
  hasActiveTask?: boolean; // 是否有活跃任务
}

export function ChatInput({
  inputValue,
  setInputValue,
  attachments,
  isRecording,
  isTranscribing = false,
  isTyping,
  audioLevel = 0,
  isThinkEnabled,
  toggleThinkMode,
  fileInputRef,
  handleSend,
  handleKeyPress,
  handleFileUpload,
  removeAttachment,
  handleNewChat,
  handleStopGeneration,
  toggleRecording,
  formatFileSize,
  canCancel = false,
  hasActiveTask = false,
}: ChatInputProps) {
  const { t, language } = useLanguage();
  
  // 判断是否应该显示停止按钮（正在输出或有活跃任务）
  const shouldShowStopButton = isTyping || hasActiveTask;
  
  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
  }>({ visible: false, x: 0, y: 0 });

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({
      visible: true,
      x: e.clientX,
      y: e.clientY
    });
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      setInputValue(inputValue + text);
      setContextMenu({ visible: false, x: 0, y: 0 });
    } catch (err) {
      console.error('Failed to read clipboard:', err);
    }
  };

  const closeContextMenu = () => {
    setContextMenu({ visible: false, x: 0, y: 0 });
  };

  // Close context menu when clicking anywhere
  useEffect(() => {
    if (contextMenu.visible) {
      const handleClick = () => closeContextMenu();
      document.addEventListener('click', handleClick);
      return () => document.removeEventListener('click', handleClick);
    }
  }, [contextMenu.visible]);

  return (
    <div className="sticky bottom-0 border-t border-slate-200 dark:border-white/10 bg-white dark:bg-slate-950/50 p-4 transition-colors backdrop-blur-lg z-10">
      <div className="mx-auto max-w-4xl">
        {/* 附件预览 */}
        {attachments.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {attachments.map((attachment) => (
              <div
                key={attachment.id}
                className="group relative flex items-center gap-2 rounded-lg border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 px-3 py-2 text-sm"
              >
                <svg
                  className="h-4 w-4 shrink-0 text-slate-400 dark:text-white/60"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                  />
                </svg>
                <span className="max-w-[150px] truncate text-slate-700 dark:text-white/80">
                  {attachment.name}
                </span>
                <span className="text-xs text-slate-400 dark:text-white/50">
                  {formatFileSize(attachment.size)}
                </span>
                <button
                  type="button"
                  onClick={() => removeAttachment(attachment.id)}
                  className="ml-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-100 dark:bg-red-500/20 text-red-500 dark:text-red-400 opacity-0 transition group-hover:opacity-100 hover:bg-red-200 dark:hover:bg-red-500/30"
                >
                  <svg
                    className="h-3 w-3"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {/* 输入框容器 - 统一背景 */}
        <div className="relative rounded-2xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-900/60 backdrop-blur-sm overflow-hidden transition-colors focus-within:border-indigo-400 dark:focus-within:border-indigo-500/50 shadow-sm">
          {/* 录音音频可视化 - 居中极简版 */}
          {isRecording && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-50/95 dark:bg-slate-900/95 backdrop-blur-sm z-10 transition-all duration-300">
              
              {/* 可点击的结束按钮 */}
              <button
                onClick={toggleRecording}
                className="group relative flex items-center justify-center mb-3 focus:outline-none"
                title={language === 'zh' ? "点击结束" : "Click to Stop"}
              >
                {/* 呼吸光圈 */}
                <div className="absolute inset-0 rounded-full bg-red-500/20 animate-ping group-hover:bg-red-500/30 transition-colors" />
                <div className="absolute inset-[-8px] rounded-full bg-red-500/10 animate-pulse group-hover:bg-red-500/20 transition-colors" />
                
                {/* 核心图标 - 悬停变大 */}
                <div className="relative h-12 w-12 rounded-full bg-gradient-to-br from-red-500 to-rose-600 flex items-center justify-center shadow-lg shadow-red-500/30 group-hover:scale-110 transition-transform duration-200 cursor-pointer">
                  <svg className="h-6 w-6 text-white animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                  {/* 停止图标 (悬停显示) */}
                  <div className="absolute inset-0 flex items-center justify-center bg-red-600 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                    <div className="h-4 w-4 bg-white rounded-sm" />
                  </div>
                </div>
              </button>
              
              {/* 状态文字 */}
              <span className="text-sm font-medium text-slate-600 dark:text-slate-300 animate-pulse">
                {language === 'zh' ? "正在聆听..." : "Listening..."}
              </span>
            </div>
          )}
          
          {/* 识别中遮罩 */}
          {isTranscribing && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-50/95 dark:bg-slate-900/95 backdrop-blur-sm z-10">
              <div className="text-center">
                <div className="flex items-center justify-center gap-2 mb-2">
                  <span className="h-3 w-3 rounded-full bg-indigo-500 animate-pulse" />
                  <span className="text-slate-700 dark:text-white font-medium">
                    {language === 'zh' ? "识别中..." : "Transcribing..."}
                  </span>
                </div>
                <p className="text-xs text-slate-400 dark:text-white/40">
                    {language === 'zh' ? "正在将语音转换为文字" : "Converting speech to text"}
                </p>
              </div>
            </div>
          )}

          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            onContextMenu={handleContextMenu}
            placeholder={t.chat.placeholder}
            className="w-full min-h-[100px] max-h-[240px] resize-none bg-transparent px-4 pt-3 pb-12 text-sm text-slate-800 dark:text-white placeholder:text-slate-400 dark:placeholder:text-white/40 focus:outline-none"
            disabled={isRecording || isTranscribing || isTyping}
          />

          {/* 功能按钮栏 - 无边框，统一背景 */}
          <div className="absolute bottom-0 left-0 right-0 flex items-center justify-between px-3 py-2">
            {/* 左侧：功能按钮组 */}
            <div className="flex items-center gap-0.5">
              {/* 文件上传 */}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileUpload}
                className="hidden"
                accept="image/*,text/*,.pdf,.doc,.docx,.txt"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 dark:text-white/50 transition hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white"
                title={language === 'zh' ? "上传文件" : "Upload File"}
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
              </button>

              {/* 新对话 */}
              <button
                type="button"
                onClick={handleNewChat}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 dark:text-white/50 transition hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white"
                title={t.common.sidebar.newChat}
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              </button>

              {/* 思考模式开关 */}
              <button
                type="button"
                onClick={toggleThinkMode}
                className={`flex h-7 w-7 items-center justify-center rounded-lg transition ${
                  isThinkEnabled
                    ? "bg-indigo-100 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-400"
                    : "text-slate-400 dark:text-white/50 hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white"
                }`}
                title={isThinkEnabled ? "Disable Thinking" : "Enable Thinking"}
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              </button>
            </div>

            {/* 右侧：主要操作按钮 */}
            <div className="flex items-center gap-1.5">
              {/* 语音输入 */}
              <button
                type="button"
                onClick={toggleRecording}
                disabled={isTranscribing || isTyping}
                className={`flex h-8 w-8 items-center justify-center rounded-lg transition ${
                  isRecording
                    ? "bg-red-500 text-white shadow-lg shadow-red-500/50"
                    : "text-slate-400 dark:text-white/60 hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-700 dark:hover:text-white disabled:opacity-30"
                }`}
                title={isRecording ? "Stop Recording" : "Voice Input"}
              >
                <svg className="h-4.5 w-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
              </button>

              {/* 发送/停止按钮 */}
              {shouldShowStopButton ? (
                /* 停止按钮 */
                <button
                  type="button"
                  onClick={handleStopGeneration}
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-500 hover:bg-red-600 text-white transition hover:shadow-lg hover:shadow-red-500/50"
                  title={language === 'zh' ? "停止" : "Stop"}
                >
                  <svg className="h-4.5 w-4.5" fill="currentColor" viewBox="0 0 24 24">
                    <rect x="6" y="6" width="12" height="12" rx="1" />
                  </svg>
                </button>
              ) : (
                /* 发送按钮 */
                <button
                  type="button"
                  onClick={handleSend}
                  disabled={(!inputValue.trim() && attachments.length === 0) || isRecording || isTranscribing}
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-r from-indigo-500 to-purple-600 text-white transition hover:shadow-lg hover:shadow-indigo-500/50 disabled:opacity-40 disabled:cursor-not-allowed"
                  title={t.common?.confirm || "Send"}
                >
                  <svg className="h-4.5 w-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                  </svg>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Context Menu - Using Portal to render at body level */}
        {contextMenu.visible && typeof window !== 'undefined' && createPortal(
          <div
            className="fixed z-[9999] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-xl py-0.5 min-w-[100px]"
            style={{
              left: `${contextMenu.x}px`,
              top: `${contextMenu.y}px`
            }}
          >
            <button
              onClick={handlePaste}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <span>粘贴</span>
            </button>
          </div>,
          document.body
        )}
      </div>
    </div>
  );
}
