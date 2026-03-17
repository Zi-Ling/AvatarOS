import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { TaskStep, Attachment, Message } from '@/types/chat';

// Re-export types for backward compatibility
export type { TaskStep, Attachment, Message } from '@/types/chat';

interface ChatState {
  messages: Message[];
  inputValue: string;
  isTyping: boolean;
  isThinkEnabled: boolean;
  attachments: Attachment[];
  currentTaskMessageId: string | null;
  sessionId: string | null; // Session ID for maintaining conversation context
  canCancel: boolean; // 是否可以取消当前操作
  
  // Actions
  setInputValue: (value: string) => void;
  setIsTyping: (isTyping: boolean) => void;
  toggleThinkMode: () => void;
  addMessage: (message: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  setAttachments: (attachments: Attachment[]) => void;
  setCurrentTaskMessageId: (id: string | null) => void;
  setSessionId: (id: string) => void;
  setCanCancel: (canCancel: boolean) => void;
  clearChat: () => void;
  addAttachment: (attachment: Attachment) => void;
  removeAttachment: (id: string) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      inputValue: "",
      isTyping: false,
      isThinkEnabled: false,
      attachments: [],
      currentTaskMessageId: null,
      sessionId: null,
      canCancel: false,

      setInputValue: (value) => set({ inputValue: value }),
      setIsTyping: (isTyping) => set({ isTyping }),
      toggleThinkMode: () => set((state) => ({ isThinkEnabled: !state.isThinkEnabled })),
      
      addMessage: (message) => set((state) => ({ 
        messages: [...state.messages, message] 
      })),
      
      updateMessage: (id, updates) => set((state) => ({
        messages: state.messages.map((msg) => {
          if (msg.id !== id) return msg;
          // GUARD: never overwrite a run_block message's kind/subtype —
          // the execution block must remain visible even after completion.
          if (msg.kind === "run" && msg.subtype === "block") {
            const { kind: _k, subtype: _s, messageType: _mt, ...safeUpdates } = updates as any;
            return { ...msg, ...safeUpdates };
          }
          return { ...msg, ...updates };
        })
      })),

      setAttachments: (attachments) => set({ attachments }),
      
      addAttachment: (attachment) => set((state) => ({
        attachments: [...state.attachments, attachment]
      })),

      removeAttachment: (id) => set((state) => ({
        attachments: state.attachments.filter(a => a.id !== id)
      })),

      setCurrentTaskMessageId: (id) => set({ currentTaskMessageId: id }),
      
      setSessionId: (id) => set({ sessionId: id }),
      
      setCanCancel: (canCancel) => set({ canCancel }),
      
      clearChat: () => set({ 
        messages: [], 
        inputValue: "", 
        attachments: [], 
        currentTaskMessageId: null,
        canCancel: false
        // Note: sessionId is NOT cleared here, it persists across chat clears
        // Only reset when user explicitly starts a new session
      }),
    }),
    {
      name: 'chat-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        messages: state.messages,
        inputValue: state.inputValue,
        isThinkEnabled: state.isThinkEnabled,
        sessionId: state.sessionId
      }),
      // Migrate old messages that have isTask/taskSteps but no messageType
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        state.messages = state.messages.map((m) => {
          // Fix: messages that were incorrectly overwritten from run_block to summary
          // These have a runId (proving they were execution blocks) but kind got changed to "summary"
          if (m.runId && (m.kind === "summary" || m.messageType === "run_summary") && !m.id.startsWith("summary-")) {
            return { ...m, kind: "run" as const, subtype: "block" as const, messageType: "run_block" as const };
          }
          // Already migrated
          if (m.kind) return m;
          // Map legacy messageType → kind/subtype
          if (m.messageType === "run_block" || m.messageType === "task_progress") {
            return { ...m, kind: "run" as const, subtype: "block" as const };
          }
          if (m.messageType === "task_paused") {
            return { ...m, kind: "run" as const, subtype: "paused" as const };
          }
          if (m.messageType === "task_cancelled") {
            return { ...m, kind: "run" as const, subtype: "cancelled" as const };
          }
          if (m.messageType === "approval") {
            return { ...m, kind: "approval" as const };
          }
          if (m.messageType === "run_summary") {
            return { ...m, kind: "summary" as const };
          }
          // Old task messages with steps → plain chat
          if (m.isTask || m.taskSteps?.length) {
            return { ...m, kind: "chat" as const, taskSteps: undefined };
          }
          return m;
        });
      },
    }
  )
);

