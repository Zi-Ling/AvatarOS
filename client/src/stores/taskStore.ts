import { create } from 'zustand';
import type { TaskStep, TaskState } from '@/types/task';
import type { ApprovalRequest } from '@/types/chat';

// Re-export types for backward compatibility
export type { TaskStep, TaskState } from '@/types/task';

interface TaskStore {
  activeTask: TaskState | null;
  logs: string[];
  isCancelling: boolean;
  pendingApprovals: ApprovalRequest[];
  // Whether workbench was auto-switched to active tab for current task
  autoSwitchedForTask: string | null;

  // Actions
  setActiveTask: (task: TaskState | null) => void;
  updateTaskStatus: (status: TaskState['status']) => void;
  updateStep: (stepId: string, updates: Partial<TaskStep>) => void;
  setSteps: (steps: TaskStep[]) => void;
  setCurrentStepName: (name: string, completedCount?: number) => void;
  addLog: (log: string) => void;
  clearLogs: () => void;
  resetTask: () => void;
  setIsCancelling: (isCancelling: boolean) => void;
  addPendingApproval: (req: ApprovalRequest) => void;
  removePendingApproval: (requestId: string) => void;
  setAutoSwitchedForTask: (taskId: string | null) => void;
}

export const useTaskStore = create<TaskStore>((set) => ({
  activeTask: null,
  logs: [],
  isCancelling: false,
  pendingApprovals: [],
  autoSwitchedForTask: null,

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

  setCurrentStepName: (name, completedCount) =>
    set((state) => ({
      activeTask: state.activeTask
        ? {
            ...state.activeTask,
            currentStepName: name,
            ...(completedCount !== undefined ? { completedCount } : {}),
          }
        : null,
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
    const newLogs = [...state.logs, log];
    if (newLogs.length > 500) {
      return { logs: newLogs.slice(newLogs.length - 500) };
    }
    return { logs: newLogs };
  }),

  clearLogs: () => set({ logs: [] }),

  resetTask: () => set({ activeTask: null, isCancelling: false, autoSwitchedForTask: null }),

  setIsCancelling: (isCancelling) => set({ isCancelling }),

  addPendingApproval: (req) =>
    set((state) => ({
      pendingApprovals: [...state.pendingApprovals.filter(r => r.request_id !== req.request_id), req],
    })),

  removePendingApproval: (requestId) =>
    set((state) => ({
      pendingApprovals: state.pendingApprovals.filter(r => r.request_id !== requestId),
    })),

  setAutoSwitchedForTask: (taskId) => set({ autoSwitchedForTask: taskId }),
}));
