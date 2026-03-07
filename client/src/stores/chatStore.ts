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
        messages: state.messages.map((msg) => 
          msg.id === id ? { ...msg, ...updates } : msg
        )
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
          if (m.messageType) return m;
          // Old task messages with steps → treat as plain chat (history)
          if (m.isTask || m.taskSteps?.length) {
            return { ...m, messageType: 'chat' as const, taskSteps: undefined };
          }
          return m;
        });
      },
    }
  )
);

