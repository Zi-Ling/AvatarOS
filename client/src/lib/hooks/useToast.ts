import { create } from 'zustand';
import type { ToastMessage, ToastType } from '@/components/ui/Toast';

interface ToastStore {
  toasts: ToastMessage[];
  addToast: (type: ToastType, title: string, message?: string, duration?: number) => void;
  removeToast: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  
  addToast: (type, title, message, duration) => {
    const id = Math.random().toString(36).substr(2, 9);
    const toast: ToastMessage = {
      id,
      type,
      title,
      message,
      duration: duration || 3000,
    };
    
    set((state) => ({
      toasts: [...state.toasts, toast],
    }));
  },
  
  removeToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },
}));

export function useToast() {
  const { addToast } = useToastStore();
  
  return {
    success: (title: string, message?: string) => addToast('success', title, message),
    error: (title: string, message?: string) => addToast('error', title, message),
    warning: (title: string, message?: string) => addToast('warning', title, message),
    info: (title: string, message?: string) => addToast('info', title, message),
  };
}

