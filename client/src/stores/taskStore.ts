import { create } from 'zustand';
import type { TaskStep, TaskState } from '@/types/task';

// Re-export types for backward compatibility
export type { TaskStep, TaskState } from '@/types/task';

interface TaskStore {
  activeTask: TaskState | null;
  logs: string[];
  isCancelling: boolean; // 任务是否正在取消中
  
  // Actions
  setActiveTask: (task: TaskState | null) => void;
  updateTaskStatus: (status: TaskState['status']) => void;
  updateStep: (stepId: string, updates: Partial<TaskStep>) => void;
  setSteps: (steps: TaskStep[]) => void;
  addLog: (log: string) => void;
  clearLogs: () => void;
  resetTask: () => void;
  setIsCancelling: (isCancelling: boolean) => void;
}

export const useTaskStore = create<TaskStore>((set) => ({
  activeTask: null,
  logs: [],
  isCancelling: false,

  setActiveTask: (task) => set({ activeTask: task }),

  updateTaskStatus: (status) => 
    set((state) => ({
      activeTask: state.activeTask 
        ? { ...state.activeTask, status }
        : null
    })),

  setSteps: (steps) =>
    set((state) => ({
      activeTask: state.activeTask
        ? { ...state.activeTask, steps }
        : null
    })),

  updateStep: (stepId, updates) =>
    set((state) => {
      if (!state.activeTask) return {};
      
      const newSteps = state.activeTask.steps.map((step) =>
        step.id === stepId ? { ...step, ...updates } : step
      );
      
      return {
        activeTask: {
          ...state.activeTask,
          steps: newSteps
        }
      };
    }),

  addLog: (log) => set((state) => {
      // Keep only last 500 logs (increased for better debugging)
      const newLogs = [...state.logs, log];
      if (newLogs.length > 500) {
          return { logs: newLogs.slice(newLogs.length - 500) };
      }
      return { logs: newLogs };
  }),

  clearLogs: () => set({ logs: [] }),

  // 只重置 activeTask (DAG 图)，不清空日志
  // 日志应该在整个会话中累积，只在新建对话时清空
  resetTask: () => set({ activeTask: null, isCancelling: false }),
  
  setIsCancelling: (isCancelling) => set({ isCancelling }),
}));

